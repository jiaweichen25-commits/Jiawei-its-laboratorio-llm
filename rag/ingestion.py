"""Ingestion: python -m rag.ingestion

Script separato, da eseguire quando il corpus cambia, non a ogni domanda (slide 11).
Non è uno strumento dell'agente: l'agente userà soltanto la ricerca.

    caricare → pulire → dividere in ricette → chunk → embedding (LM Studio) → upsert in Qdrant

Rieseguirlo non duplica nulla: ID stabili e rimozione dei punti orfani (slide 18). Alla fine
stampa il numero di punti prima e dopo, il controllo richiesto dalla slide.
"""

import logging
import os
import sys
import time

from dotenv import load_dotenv
from qdrant_client import QdrantClient

from rag.archivio import Archivio, ErroreArchivio
from rag.chunking import dividi
from rag.config import ConfigurazioneRag, ErroreConfigurazione, carica_configurazione
from rag.corpus import leggi_ricette, pulisci
from rag.embedding import EmbedderLMStudio, ErroreEmbedding

log = logging.getLogger("rag.ingestion")


def esegui(cfg: ConfigurazioneRag, client: QdrantClient | None = None, embedder=None, stampa=lambda _: None) -> dict:
    """Esegue l'ingestion completa e restituisce i conteggi."""
    if not cfg.corpus_file.is_file():
        raise FileNotFoundError(
            f"Corpus non trovato: {cfg.corpus_file}. Scaricare il ricettario (Project Gutenberg n. 59047) e salvarlo lì."
        )
    client = client or QdrantClient(url=cfg.qdrant_url, timeout=60)
    embedder = embedder or EmbedderLMStudio(cfg.embedding_url, cfg.embedding_model, prefissi=cfg.prefissi)
    archivio = Archivio(client, cfg.collezione)
    inizio = time.perf_counter()

    # 1-4) Caricare, pulire, dividere in ricette e in chunk (con i metadati).
    ricette = leggi_ricette(pulisci(cfg.corpus_file.read_text(encoding="utf-8")))
    chunk = [c for r in ricette for c in dividi(r, cfg.chunk_dimensione, cfg.chunk_overlap)]
    stampa(f"ricette: {len(ricette)} · chunk: {len(chunk)} "
           f"(dimensione {cfg.chunk_dimensione}, overlap {cfg.chunk_overlap})")

    # Prima di calcolare 1000 vettori si controlla la collezione con uno solo: se il modello è
    # cambiato ci si ferma subito, senza minuti di calcolo inutile.
    prova = embedder.documenti([chunk[0].testo])[0]
    archivio.prepara(embedder.modello, len(prova), embedder.prefissi)
    punti_prima = archivio.conta()
    stampa(f"collezione «{cfg.collezione}»: {punti_prima} punti prima · modello {embedder.modello}, "
           f"dimensione {len(prova)}, prefissi {'sì' if embedder.prefissi else 'no'}")

    # 5) Embedding a lotti.  6) Upsert e rimozione degli orfani.
    vettori = [prova] + embedder.documenti([c.testo for c in chunk[1:]])
    esito = archivio.salva(chunk, vettori)
    punti_dopo = archivio.conta()
    risultato = {"ricette": len(ricette), "chunk": len(chunk), "punti_prima": punti_prima,
                 "punti_dopo": punti_dopo, "rimossi": esito.rimossi, "secondi": round(time.perf_counter() - inizio, 1)}
    stampa(f"punti dopo: {punti_dopo} · scritti {esito.scritti} · rimossi {esito.rimossi} · "
           f"{risultato['secondi']} s")
    return risultato


def descrivi_errore(exc: BaseException, cfg: ConfigurazioneRag) -> str | None:
    """Messaggio comprensibile per gli errori di servizio; None per i difetti del programma."""
    if isinstance(exc, (ErroreConfigurazione, ErroreArchivio, ErroreEmbedding, FileNotFoundError, ValueError)):
        return str(exc)
    modulo = type(exc).__module__
    if modulo.startswith(("qdrant_client", "httpx", "httpcore")) or isinstance(exc, ConnectionError):
        return (f"Qdrant non raggiungibile su {cfg.qdrant_url}: avviarlo con «docker compose up -d qdrant» "
                f"e controllare QDRANT_URL ({type(exc).__name__}).")
    return None


def main() -> int:
    for flusso in (sys.stdout, sys.stderr):
        flusso.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(override=False)
    try:
        cfg = carica_configurazione(os.environ)
    except ErroreConfigurazione as exc:
        print(exc, file=sys.stderr)
        return 1
    try:
        esegui(cfg, stampa=print)
    except Exception as exc:
        messaggio = descrivi_errore(exc, cfg)
        if messaggio is None:
            raise
        print(messaggio, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
