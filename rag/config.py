"""Configurazione della pipeline RAG dalle variabili d'ambiente (file .env).

Il modello di embedding sta nella configurazione e non nel codice (slide 10): cambiarlo
richiede di reindicizzare tutto il corpus in una collezione nuova.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent


class ErroreConfigurazione(Exception):
    """Configurazione mancante o non valida."""


@dataclass(frozen=True)
class ConfigurazioneRag:
    corpus_file: Path                         # CORPUS_FILE, predefinito dati/artusi.txt
    embedding_url: str                        # LM_BASE_URL: lo stesso server LM Studio dell'agente
    embedding_model: str                      # EMBEDDING_MODEL: l'ID restituito da LM Studio
    prefissi: bool = True                     # EMBEDDING_PREFISSI: «search_document:» / «search_query:»
    qdrant_url: str = "http://localhost:6333"  # QDRANT_URL
    collezione: str = "ricette"               # QDRANT_COLLEZIONE
    chunk_dimensione: int = 1200              # CHUNK_DIMENSIONE, caratteri
    chunk_overlap: int = 200                  # CHUNK_OVERLAP, caratteri


def _intero(env: Mapping[str, str], nome: str, predefinito: int) -> int:
    testo = env.get(nome, "").strip()
    if not testo:
        return predefinito
    try:
        return int(testo)
    except ValueError:
        raise ErroreConfigurazione(f"{nome} deve essere un numero intero: «{testo}».") from None


def carica_configurazione(env: Mapping[str, str]) -> ConfigurazioneRag:
    mancanti = [n for n in ("LM_BASE_URL", "EMBEDDING_MODEL") if not env.get(n, "").strip()]
    if mancanti:
        raise ErroreConfigurazione(f"Variabili mancanti: {', '.join(mancanti)}. Vedi .env.example.")

    dimensione = _intero(env, "CHUNK_DIMENSIONE", 1200)
    overlap = _intero(env, "CHUNK_OVERLAP", 200)
    if dimensione <= 0:
        raise ErroreConfigurazione(f"CHUNK_DIMENSIONE deve essere maggiore di 0: «{dimensione}».")
    if not 0 <= overlap < dimensione:
        raise ErroreConfigurazione(f"CHUNK_OVERLAP deve essere tra 0 e CHUNK_DIMENSIONE escluso ({dimensione}): «{overlap}».")

    prefissi = env.get("EMBEDDING_PREFISSI", "").strip().lower() or "si"
    if prefissi not in ("si", "sì", "no"):
        raise ErroreConfigurazione(f"EMBEDDING_PREFISSI vale «si» oppure «no»: «{prefissi}».")

    corpus = Path(env.get("CORPUS_FILE", "").strip() or "dati/artusi.txt")
    return ConfigurazioneRag(
        corpus_file=corpus if corpus.is_absolute() else RADICE / corpus,
        embedding_url=env["LM_BASE_URL"].strip().rstrip("/"),
        embedding_model=env["EMBEDDING_MODEL"].strip(),
        prefissi=prefissi != "no",
        qdrant_url=(env.get("QDRANT_URL", "").strip() or "http://localhost:6333").rstrip("/"),
        collezione=env.get("QDRANT_COLLEZIONE", "").strip() or "ricette",
        chunk_dimensione=dimensione,
        chunk_overlap=overlap,
    )
