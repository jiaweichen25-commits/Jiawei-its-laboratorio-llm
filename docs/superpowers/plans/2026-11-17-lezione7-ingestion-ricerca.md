# Lezione 7, esercizio 1 — Ingestion e ricerca: piano di implementazione

**Goal:** pipeline RAG ripetibile sul ricettario di Artusi: corpus → chunk → embedding → Qdrant, ricerca top-k con
filtro per capitolo, valutazione su domande con fonte attesa.

**Spec:** `docs/superpowers/specs/2026-11-17-lezione7-ingestion-ricerca-design.md`

**Tech stack:** Python, qdrant-client 1.20.0 (server 1.20.2 in Docker Compose), httpx verso `/v1/embeddings` di LM
Studio, pytest. Test con embedder finto e `QdrantClient(":memory:")`.

## Global constraints

- Ricette 790, numerate senza buchi; 23 capitoli. Chunk 1200 caratteri, overlap 200, dalla configurazione.
- ID dei punti: UUID v5 di `f"{documento_id}:{posizione}"`. Upsert + rimozione degli orfani; mai ricreare la collezione.
- Modello, dimensione e prefissi registrati nei metadati della collezione; differenza → errore.
- `k` massimo 20. Filtro per capitolo durante la ricerca; capitolo sconosciuto → errore con l'elenco.
- Test senza LM Studio né Qdrant; prove reali marcate `qdrant`.

## Interfacce

```python
# rag/corpus.py
@dataclass(frozen=True) class Ricetta: numero: int; titolo: str; capitolo: str; testo: str   # testo: paragrafi separati da "\n\n"
def pulisci(testo_grezzo: str) -> str                    # toglie Gutenberg, CRLF, controlli
def leggi_ricette(testo: str) -> list[Ricetta]
CAPITOLI: tuple[str, ...]                                 # i 23 capitoli, nell'ordine del libro

# rag/chunking.py
@dataclass(frozen=True) class Chunk: documento_id: str; numero: int; titolo: str; capitolo: str; posizione: int; chunk_totali: int; testo: str
def dividi(ricetta: Ricetta, dimensione: int, overlap: int) -> list[Chunk]
def id_punto(documento_id: str, posizione: int) -> str   # UUID v5

# rag/embedding.py
class Embedder(Protocol): modello: str; dimensione: int | None; def documenti(testi) -> list[list[float]]; def domanda(testo) -> list[float]
class EmbedderLMStudio: (base_url, modello, prefissi=True, lotto=32, transport=None)

# rag/archivio.py
class ErroreArchivio(Exception)
class Archivio: (client: QdrantClient, collezione: str)
    prepara(modello: str, dimensione: int, prefissi: bool) -> None     # crea o verifica i metadati
    conta() -> int; capitoli() -> list[str]
    salva(chunk: list[Chunk], vettori) -> EsitoSalvataggio(scritti, rimossi)   # upsert + orfani
    cerca(vettore, k=5, capitolo=None) -> list[Risultato]
@dataclass Risultato: posizione_classifica, score, numero, titolo, capitolo, posizione, chunk_totali, testo

# rag/ingestion.py   def esegui(cfg, client=None, embedder=None) -> dict (punti_prima, punti_dopo, ricette, chunk, rimossi)
# rag/ricerca.py     def cerca(cfg, domanda, k, capitolo, client=None, embedder=None) -> list[Risultato]
# rag/valutazione.py def valuta(domande, cerca_fn, k) -> list[Riga]; def tabella_markdown(righe) -> str
```

## Task

1. Corpus e chunking (logica pura) — test sul file vero in `dati/` (saltati se manca) e su testi piccoli.
2. Embedding, archivio, ingestion, ricerca — embedder finto e Qdrant in memoria.
3. Valutazione e domande — calcolo della posizione della fonte attesa.
4. Qdrant in Compose, configurazione, README, CLAUDE.md; prove reali; `docs/retrieval.md`; commit e push.
