"""Lezione 7: lettura e pulizia del ricettario, divisione in ricette e chunk (logica pura).

I test sul libro intero usano dati/artusi.txt: se il file manca (è fuori da Git) vengono saltati.
"""

from pathlib import Path

import pytest

from rag.chunking import Chunk, dividi, id_punto
from rag.corpus import CAPITOLI, Ricetta, leggi_ricette, pulisci

LIBRO = Path(__file__).resolve().parent.parent / "dati" / "artusi.txt"


@pytest.fixture(scope="module")
def ricette():
    if not LIBRO.is_file():
        pytest.skip("dati/artusi.txt non presente (è escluso da Git): vedi README, lezione 7.")
    return leggi_ricette(pulisci(LIBRO.read_text(encoding="utf-8")))


# ---------------------------------------------------------------- pulizia

GREZZO = (
    "The Project Gutenberg eBook of La scienza in cucina\r\n\r\n"
    "*** START OF THE PROJECT GUTENBERG EBOOK LA SCIENZA IN CUCINA ***\r\n"
    "Testo\u0007 del libro\r\n"
    "*** END OF THE PROJECT GUTENBERG EBOOK LA SCIENZA IN CUCINA ***\r\nLicenza...\r\n"
)


def test_pulisci_toglie_gutenberg_crlf_e_caratteri_di_controllo():
    pulito = pulisci(GREZZO)

    assert pulito.strip() == "Testo del libro"
    assert "\r" not in pulito and "Gutenberg" not in pulito and "Licenza" not in pulito


# ---------------------------------------------------------------- ricette sul libro vero

def test_790_ricette_numerate_senza_buchi(ricette):
    assert [r.numero for r in ricette] == list(range(1, 791))


def test_23_capitoli_nell_ordine_del_libro(ricette):
    trovati = list(dict.fromkeys(r.capitolo for r in ricette))  # in ordine di apparizione, senza ripetizioni

    assert len(CAPITOLI) == 23
    assert trovati == list(CAPITOLI)


def test_ricette_delle_slide(ricette):
    per_numero = {r.numero: r for r in ricette}

    assert (per_numero[89].titolo, per_numero[89].capitolo) == ("Gnocchi di patate", "Minestre asciutte e di magro")
    assert (per_numero[208].titolo, per_numero[208].capitolo) == ("Pollo alla cacciatora", "Fritti")
    assert per_numero[455].capitolo == per_numero[456].capitolo == "Piatti di pesce"
    assert per_numero[790].titolo == "Spezie fini"


def test_righe_spezzate_riunite_e_paragrafi_conservati(ricette):
    gnocchi = next(r for r in ricette if r.numero == 89)

    assert "gli gnocchi in brodo" in gnocchi.testo  # nel file «gli gnocchi» e «in brodo» stanno su due righe
    assert all("\n" not in paragrafo for paragrafo in gnocchi.testo.split("\n\n"))
    assert len(gnocchi.testo.split("\n\n")) > 1


def test_una_riga_che_comincia_con_un_numero_non_e_un_titolo(ricette):
    # Nella ricetta 175 un rimando va a capo: «…un poco di balsamella N.» / «137. Mettete il composto…».
    # Quella riga sembra il titolo di una ricetta, ma è testo della 175.
    per_numero = {r.numero: r for r in ricette}

    assert per_numero[137].titolo == "Balsamella"
    assert "N. 137. Mettete il composto al fuoco" in per_numero[175].testo
    assert not any("APPENDICE" in r.testo or "STOMACHI DEBOLI" in r.testo for r in ricette)


def test_le_introduzioni_ai_capitoli_non_finiscono_nella_ricetta_precedente(ricette):
    # «MINESTRE» raggruppa due capitoli ed è seguita da un'introduzione: non fa parte della ricetta 6.
    # «QUALITÀ E STAGIONE DEI PESCI» introduce il capitolo del pesce: non fa parte della 454 né della 455.
    per_numero = {r.numero: r for r in ricette}

    assert "MINESTRE" not in per_numero[6].testo
    assert "QUALITÀ E STAGIONE" not in per_numero[454].testo + per_numero[455].testo


def test_le_sotto_ricette_restano_nella_loro_ricetta(ricette):
    # «PASTA FROLLA» è la pasta che copre il pasticcio della 421, non un capitolo.
    pasticcio = next(r for r in ricette if r.numero == 421)

    assert "PASTA FROLLA" in pasticcio.testo and pasticcio.capitolo == "Erbaggi e legumi"


def test_nessuna_ricetta_vuota_e_titoli_senza_spazi_in_eccesso(ricette):
    assert all(r.testo.strip() and r.titolo == r.titolo.strip() for r in ricette)


# ---------------------------------------------------------------- chunking

def ricetta(testo, numero=7):
    return Ricetta(numero=numero, titolo="Titolo", capitolo="Fritti", testo=testo)


def test_ricetta_breve_un_chunk_solo():
    [chunk] = dividi(ricetta("Primo paragrafo.\n\nSecondo paragrafo."), dimensione=1200, overlap=200)

    assert chunk == Chunk(documento_id="ricetta-007", numero=7, titolo="Titolo", capitolo="Fritti",
                          posizione=0, chunk_totali=1, testo="Primo paragrafo.\n\nSecondo paragrafo.")


def paragrafi(n, lunghezza):
    return "\n\n".join(f"Paragrafo {i} " + "parola " * (lunghezza // 7) for i in range(n))


def test_ricetta_lunga_divisa_senza_superare_la_dimensione():
    chunk = dividi(ricetta(paragrafi(10, 300)), dimensione=1200, overlap=200)

    assert len(chunk) > 1
    assert all(len(c.testo) <= 1200 for c in chunk)
    assert [c.posizione for c in chunk] == list(range(len(chunk)))
    assert all(c.chunk_totali == len(chunk) for c in chunk)


def test_overlap_tra_chunk_consecutivi_inizia_a_parola_intera():
    chunk = dividi(ricetta(paragrafi(10, 300)), dimensione=1200, overlap=200)

    for precedente, successivo in zip(chunk, chunk[1:]):
        inizio = successivo.testo.split("\n\n")[0]
        assert precedente.testo.endswith(inizio), (precedente.testo[-250:], inizio)
        assert 0 < len(inizio) <= 200
        assert not inizio.startswith(" ")


def test_ricomponendo_i_chunk_non_si_perde_testo():
    testo = paragrafi(12, 450)

    chunk = dividi(ricetta(testo), dimensione=1200, overlap=200)

    parole_originali = testo.split()
    unione = " ".join(c.testo for c in chunk).split()
    assert all(parola in unione for parola in set(parole_originali))
    assert chunk[0].testo.split()[:3] == parole_originali[:3] and chunk[-1].testo.split()[-3:] == parole_originali[-3:]


def test_paragrafo_piu_lungo_della_dimensione_tagliato_a_finestra():
    lungo = "parola " * 400  # circa 2800 caratteri, un paragrafo solo

    chunk = dividi(ricetta(lungo.strip()), dimensione=1200, overlap=200)

    assert len(chunk) >= 3 and all(len(c.testo) <= 1200 for c in chunk)


def test_parametri_diversi_danno_chunk_diversi():
    testo = paragrafi(10, 300)

    assert len(dividi(ricetta(testo), 600, 100)) > len(dividi(ricetta(testo), 1200, 200))


@pytest.mark.parametrize("dimensione, overlap", [(0, 0), (100, 100), (100, 150), (100, -1)])
def test_parametri_non_validi(dimensione, overlap):
    with pytest.raises(ValueError):
        dividi(ricetta("testo"), dimensione, overlap)


def test_libro_intero_in_chunk(ricette):
    chunk = [c for r in ricette for c in dividi(r, 1200, 200)]

    assert all(len(c.testo) <= 1200 for c in chunk)
    assert sum(1 for c in chunk if c.chunk_totali == 1) / len(ricette) > 0.65  # la maggior parte resta intera
    assert len({(c.documento_id, c.posizione) for c in chunk}) == len(chunk)


# ---------------------------------------------------------------- identificativi

def test_id_stabile_e_diverso_tra_chunk_diversi():
    assert id_punto("ricetta-089", 0) == id_punto("ricetta-089", 0)
    assert len({id_punto("ricetta-089", 0), id_punto("ricetta-089", 1), id_punto("ricetta-090", 0)}) == 3
    assert len(id_punto("ricetta-089", 0)) == 36  # formato UUID, richiesto da Qdrant
