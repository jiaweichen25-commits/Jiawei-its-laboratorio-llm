"""Ricerca semantica: python -m rag.ricerca "domanda" [--k 5] [--capitolo NOME]

    domanda → embedding (stesso modello dei documenti) → i k punti più vicini in Qdrant → risultati con la fonte

Il modello generativo non c'entra: si leggono i passaggi recuperati e si giudica se rispondono
(slide 20). Se il passaggio giusto non arriva, va corretta l'ingestion, non il prompt.

Esempio (slide 17):   python -m rag.ricerca "Come si frigge il pollo?" --capitolo Fritti --k 3
"""

import argparse
import os
import sys
import textwrap

from dotenv import load_dotenv
from qdrant_client import QdrantClient

from rag.archivio import MASSIMO_K, Archivio, Risultato
from rag.config import ConfigurazioneRag, ErroreConfigurazione, carica_configurazione
from rag.embedding import EmbedderLMStudio
from rag.ingestion import descrivi_errore


def cerca(cfg: ConfigurazioneRag, domanda: str, k: int = 5, capitolo: str | None = None,
          client: QdrantClient | None = None, embedder=None) -> list[Risultato]:
    if not 1 <= k <= MASSIMO_K:  # controllato prima di chiamare il modello
        raise ValueError(f"k deve essere tra 1 e {MASSIMO_K}: {k}.")
    archivio = Archivio(client or QdrantClient(url=cfg.qdrant_url, timeout=60), cfg.collezione)
    embedder = embedder or EmbedderLMStudio(cfg.embedding_url, cfg.embedding_model, prefissi=cfg.prefissi)
    archivio.verifica_per_ricerca(embedder.modello, embedder.prefissi)
    return archivio.cerca(embedder.domanda(domanda), k=k, capitolo=capitolo)


def formatta(risultati: list[Risultato], larghezza: int = 100) -> str:
    """Una scheda per risultato: classifica, score, fonte e inizio del testo."""
    if not risultati:
        return "Nessun risultato."
    schede = []
    for r in risultati:
        intestazione = (f"{r.classifica}. score {r.score:.3f} · ricetta {r.numero} · {r.titolo} · {r.capitolo} · "
                        f"chunk {r.posizione + 1} di {r.chunk_totali}")
        anteprima = textwrap.shorten(r.testo.replace("\n\n", " ¶ "), width=360, placeholder=" …")
        schede.append(intestazione + "\n" + textwrap.indent(textwrap.fill(anteprima, larghezza - 3), "   "))
    return "\n\n".join(schede)


def main() -> int:
    for flusso in (sys.stdout, sys.stderr):
        flusso.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Ricerca semantica nel ricettario di Artusi.")
    parser.add_argument("domanda")
    parser.add_argument("--k", type=int, default=5, help=f"quanti risultati (da 1 a {MASSIMO_K}, predefinito 5)")
    parser.add_argument("--capitolo", help="cerca solo in questo capitolo, es. Fritti")
    argomenti = parser.parse_args()

    load_dotenv(override=False)
    try:
        cfg = carica_configurazione(os.environ)
    except ErroreConfigurazione as exc:
        print(exc, file=sys.stderr)
        return 1
    try:
        risultati = cerca(cfg, argomenti.domanda, k=argomenti.k, capitolo=argomenti.capitolo)
    except Exception as exc:
        messaggio = descrivi_errore(exc, cfg)
        if messaggio is None:
            raise
        print(messaggio, file=sys.stderr)
        return 1
    print(formatta(risultati))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
