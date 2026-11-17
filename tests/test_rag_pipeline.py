"""Lezione 7: embedding, archivio Qdrant, ingestion, ricerca e valutazione.

Tutto con l'embedder finto e Qdrant IN MEMORIA (QdrantClient(":memory:")): i test passano con
LM Studio e il server Qdrant spenti, come chiede la slide 25.
"""

import json
from pathlib import Path

import httpx
import pytest
from qdrant_client import QdrantClient

from rag.archivio import Archivio, ErroreArchivio, MASSIMO_K
from rag.chunking import Chunk, id_punto
from rag.config import ErroreConfigurazione, carica_configurazione
from rag.embedding import PREFISSO_DOCUMENTO, PREFISSO_DOMANDA, EmbedderLMStudio, ErroreEmbedding
from rag.ingestion import esegui
from rag.ricerca import cerca, formatta
from rag.valutazione import Domanda, carica_domande, tabella_markdown, valuta
from tests.embedder_finto import DIMENSIONE, EmbedderFinto

CORPUS = """*** START OF THE PROJECT GUTENBERG EBOOK PROVA ***
Prefazione che non è una ricetta e va scartata.

RICETTE

BRODI, GELATINA E SUGHI

1. Brodo

Il brodo si fa con la carne di manzo e un poco di sale.

2. Sugo di carne

Il sugo di carne si fa con manzo, cipolla e burro.

MINESTRE

Introduzione alle minestre, da scartare.

MINESTRE IN BRODO

3. Gnocchi di patate

Patate farinose e farina: per 400 grammi di patate bastano 150 grammi di farina.

FRITTI

4. Pollo alla cacciatora

Tagliate il pollo a pezzi e versate un dito di vino rosso nel tegame.
*** END OF THE PROJECT GUTENBERG EBOOK PROVA ***
"""


def configurazione(tmp_path, **altro):
    file = tmp_path / "artusi.txt"
    file.write_text(CORPUS, encoding="utf-8")
    env = {"LM_BASE_URL": "http://localhost:1234/v1", "EMBEDDING_MODEL": "modello-finto",
           "CORPUS_FILE": str(file), **altro}
    return carica_configurazione(env)


@pytest.fixture
def client():
    c = QdrantClient(":memory:")
    yield c
    c.close()


# ---------------------------------------------------------------- configurazione

def test_configurazione_predefinita(tmp_path):
    cfg = configurazione(tmp_path)

    assert (cfg.qdrant_url, cfg.collezione, cfg.prefissi) == ("http://localhost:6333", "ricette", True)
    assert (cfg.chunk_dimensione, cfg.chunk_overlap, cfg.embedding_url) == (1200, 200, "http://localhost:1234/v1")


@pytest.mark.parametrize("env, variabile", [
    ({"EMBEDDING_MODEL": ""}, "EMBEDDING_MODEL"),
    ({"CHUNK_DIMENSIONE": "tanti"}, "CHUNK_DIMENSIONE"),
    ({"CHUNK_DIMENSIONE": "100", "CHUNK_OVERLAP": "100"}, "CHUNK_OVERLAP"),
    ({"EMBEDDING_PREFISSI": "forse"}, "EMBEDDING_PREFISSI"),
])
def test_configurazione_non_valida(tmp_path, env, variabile):
    with pytest.raises(ErroreConfigurazione, match=variabile):
        configurazione(tmp_path, **env)


def test_prefissi_spenti(tmp_path):
    assert configurazione(tmp_path, EMBEDDING_PREFISSI="no").prefissi is False


# ---------------------------------------------------------------- client di LM Studio

def lm_studio_finto(registro):
    def gestore(richiesta: httpx.Request) -> httpx.Response:
        corpo = json.loads(richiesta.content)
        registro.append(corpo)
        # LM Studio risponde con un elemento per testo; l'ordine si ricostruisce con «index».
        dati = [{"index": i, "embedding": [float(len(t)), 1.0, 0.0]} for i, t in enumerate(corpo["input"])]
        return httpx.Response(200, json={"data": list(reversed(dati))})
    return httpx.MockTransport(gestore)


def test_embedder_lm_studio_prefissi_lotti_e_ordine():
    registro = []
    embedder = EmbedderLMStudio("http://lm.test/v1", "nomic", prefissi=True, lotto=2, transport=lm_studio_finto(registro))

    vettori = embedder.documenti(["a", "bb", "ccc"])
    domanda = embedder.domanda("dd")

    assert [r["input"] for r in registro] == [
        [PREFISSO_DOCUMENTO + "a", PREFISSO_DOCUMENTO + "bb"], [PREFISSO_DOCUMENTO + "ccc"], [PREFISSO_DOMANDA + "dd"],
    ]
    assert all(r["model"] == "nomic" for r in registro)
    assert [v[0] for v in vettori] == [len(PREFISSO_DOCUMENTO) + n for n in (1, 2, 3)]  # ordine giusto
    assert domanda[0] == len(PREFISSO_DOMANDA) + 2


def test_embedder_senza_prefissi():
    registro = []
    EmbedderLMStudio("http://lm.test/v1", "nomic", prefissi=False, transport=lm_studio_finto(registro)).domanda("x")

    assert registro[0]["input"] == ["x"]


def test_embedder_lm_studio_spento():
    def rifiuta(richiesta):
        raise httpx.ConnectError("rifiutata", request=richiesta)

    with pytest.raises(ErroreEmbedding, match="LM Studio non raggiungibile"):
        EmbedderLMStudio("http://lm.test/v1", "nomic", transport=httpx.MockTransport(rifiuta)).domanda("x")


def test_embedder_modello_non_caricato():
    errore = httpx.MockTransport(lambda r: httpx.Response(404, json={"error": "model not found"}))

    with pytest.raises(ErroreEmbedding, match="nomic.*model not found"):
        EmbedderLMStudio("http://lm.test/v1", "nomic", transport=errore).domanda("x")


# ---------------------------------------------------------------- ingestion

def test_ingestion_crea_un_punto_per_chunk_con_payload_completo(tmp_path, client):
    esito = esegui(configurazione(tmp_path), client=client, embedder=EmbedderFinto())

    assert (esito["ricette"], esito["chunk"], esito["punti_prima"], esito["punti_dopo"]) == (4, 4, 0, 4)
    [punto] = client.retrieve("ricette", ids=[id_punto("ricetta-003", 0)], with_payload=True)
    assert punto.payload == {
        "documento_id": "ricetta-003", "numero": 3, "titolo": "Gnocchi di patate", "capitolo": "Minestre in brodo",
        "posizione": 0, "chunk_totali": 1,
        "testo": "Patate farinose e farina: per 400 grammi di patate bastano 150 grammi di farina.",
        "fonte": "Artusi, La scienza in cucina e l'arte di mangiar bene (1891), ricetta 3",
    }


def test_due_ingestion_stesso_numero_di_punti(tmp_path, client):
    cfg = configurazione(tmp_path)

    prima = esegui(cfg, client=client, embedder=EmbedderFinto())
    seconda = esegui(cfg, client=client, embedder=EmbedderFinto())

    assert prima["punti_dopo"] == seconda["punti_prima"] == seconda["punti_dopo"] == 4
    assert seconda["rimossi"] == 0


def test_chunking_diverso_rimuove_i_punti_orfani(tmp_path, client):
    esegui(configurazione(tmp_path, CHUNK_DIMENSIONE="40", CHUNK_OVERLAP="10"), client=client, embedder=EmbedderFinto())
    molti = client.count("ricette").count

    esito = esegui(configurazione(tmp_path), client=client, embedder=EmbedderFinto())  # torna a 1200: meno chunk

    assert molti > 4
    assert esito["punti_dopo"] == 4 and esito["rimossi"] == molti - 4


def test_modello_e_dimensione_registrati_nella_collezione(tmp_path, client):
    esegui(configurazione(tmp_path), client=client, embedder=EmbedderFinto())

    metadati = client.get_collection("ricette").config.metadata
    assert metadati == {"modello_embedding": "modello-finto", "dimensione": DIMENSIONE, "prefissi": True}


def test_cambio_di_modello_bloccato(tmp_path, client):
    esegui(configurazione(tmp_path), client=client, embedder=EmbedderFinto())

    with pytest.raises(ErroreArchivio, match="modello-finto.*altro-modello"):
        esegui(configurazione(tmp_path, EMBEDDING_MODEL="altro-modello"), client=client,
               embedder=EmbedderFinto(modello="altro-modello"))
    assert client.count("ricette").count == 4  # nulla è stato scritto


def test_cambio_dei_prefissi_bloccato(tmp_path, client):
    esegui(configurazione(tmp_path), client=client, embedder=EmbedderFinto())

    with pytest.raises(ErroreArchivio, match="prefissi"):
        esegui(configurazione(tmp_path, EMBEDDING_PREFISSI="no"), client=client, embedder=EmbedderFinto(prefissi=False))


def test_corpus_mancante(tmp_path, client):
    cfg = carica_configurazione({"LM_BASE_URL": "http://x/v1", "EMBEDDING_MODEL": "m", "CORPUS_FILE": str(tmp_path / "no.txt")})

    with pytest.raises(FileNotFoundError, match="no.txt"):
        esegui(cfg, client=client, embedder=EmbedderFinto())


# ---------------------------------------------------------------- ricerca

@pytest.fixture
def indice(tmp_path, client):
    cfg = configurazione(tmp_path)
    esegui(cfg, client=client, embedder=EmbedderFinto())
    return cfg


def test_ricerca_top_k_con_fonte(indice, client):
    risultati = cerca(indice, "farina per le patate degli gnocchi", k=2, client=client, embedder=EmbedderFinto())

    assert len(risultati) == 2
    primo = risultati[0]
    assert (primo.numero, primo.titolo, primo.capitolo, primo.posizione, primo.chunk_totali) == (
        3, "Gnocchi di patate", "Minestre in brodo", 0, 1)
    assert primo.classifica == 1 and risultati[0].score >= risultati[1].score


def test_ricerca_filtro_per_capitolo(indice, client):
    risultati = cerca(indice, "carne di manzo", k=5, capitolo="Fritti", client=client, embedder=EmbedderFinto())

    assert [r.capitolo for r in risultati] == ["Fritti"]  # al massimo k, tutti del capitolo


def test_ricerca_capitolo_inesistente_elenca_quelli_validi(indice, client):
    with pytest.raises(ErroreArchivio, match="Fritto.*Fritti"):
        cerca(indice, "pollo", capitolo="Fritto", client=client, embedder=EmbedderFinto())


@pytest.mark.parametrize("k", [0, MASSIMO_K + 1])
def test_ricerca_k_fuori_intervallo(indice, client, k):
    with pytest.raises(ValueError, match=str(MASSIMO_K)):
        cerca(indice, "pollo", k=k, client=client, embedder=EmbedderFinto())


def test_ricerca_prima_dell_ingestion(tmp_path, client):
    with pytest.raises(ErroreArchivio, match="ingestion"):
        cerca(configurazione(tmp_path), "pollo", client=client, embedder=EmbedderFinto())


def test_ricerca_con_un_modello_diverso_da_quello_dell_indice(indice, client):
    with pytest.raises(ErroreArchivio, match="altro"):
        cerca(indice, "pollo", client=client, embedder=EmbedderFinto(modello="altro"))


def test_formatta_risultati(indice, client):
    testo = formatta(cerca(indice, "vino per il pollo", k=1, client=client, embedder=EmbedderFinto()))

    assert "1." in testo and "ricetta 4 · Pollo alla cacciatora" in testo and "Fritti" in testo and "chunk 1 di 1" in testo


# ---------------------------------------------------------------- valutazione

def test_valutazione_posizione_della_fonte_attesa(indice, client):
    domande = [
        Domanda("vino per il pollo", [4]),
        Domanda("farina per le patate", [3]),
        Domanda("tiramisù al caffè", []),          # nessuna risposta nel corpus
        Domanda("brodo di manzo", [99]),           # fonte attesa che non compare
    ]

    righe = valuta(domande, lambda d, k, c: cerca(indice, d, k=k, capitolo=c, client=client, embedder=EmbedderFinto()), k=2)

    assert righe[0].posizione == 1 and righe[1].posizione == 1
    assert righe[2].posizione is None and righe[2].attese == []
    assert righe[3].posizione is None and righe[3].score_fonte is None
    assert all(r.score_primo is not None for r in righe)


def test_tabella_markdown_con_riepilogo(indice, client):
    righe = valuta([Domanda("vino per il pollo", [4]), Domanda("ricetta inesistente", [99]), Domanda("tiramisù", [])],
                   lambda d, k, c: cerca(indice, d, k=k, capitolo=c, client=client, embedder=EmbedderFinto()), k=2)

    tabella = tabella_markdown(righe, k=2)

    assert tabella.startswith("| Domanda |")
    assert "| vino per il pollo | 4 | 1 |" in tabella
    assert "assente" in tabella and "— (nessuna)" in tabella
    assert "Fonte attesa trovata tra i primi 2: 1 su 2" in tabella


def test_domande_del_progetto_valide():
    domande = carica_domande(Path(__file__).resolve().parent.parent / "rag" / "domande.json")

    con_risposta = [d for d in domande if d.attese]
    assert len(con_risposta) >= 8 and len(domande) - len(con_risposta) >= 2
    assert sum(d.propria for d in domande) >= 3  # slide 27: almeno tre domande proprie
    assert all(1 <= n <= 790 for d in domande for n in d.attese)
