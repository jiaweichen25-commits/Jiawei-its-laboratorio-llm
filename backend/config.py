"""Configurazione del back-end da variabili d'ambiente (file .env)."""

from collections.abc import Mapping
from dataclasses import dataclass

LIVELLI_LOG = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ErroreConfigurazione(Exception):
    """Configurazione mancante o non valida: il back-end non può partire."""


@dataclass(frozen=True)
class Configurazione:
    database_url: str                           # DATABASE_URL, es. postgresql+psycopg://utente:password@localhost:5433/chat
    agente_url: str = "http://localhost:8001"   # AGENTE_URL: il servizio dell'agente (step 6)
    agente_timeout: float = 600.0               # AGENTE_TIMEOUT, secondi: le risposte lunghe durano minuti
    log_level: str = "INFO"                     # LOG_LEVEL


def carica_configurazione(env: Mapping[str, str]) -> Configurazione:
    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        raise ErroreConfigurazione("Variabile mancante: DATABASE_URL. Vedi .env.example.")

    livello = env.get("LOG_LEVEL", "").strip().upper() or "INFO"
    if livello not in LIVELLI_LOG:
        raise ErroreConfigurazione(f"LOG_LEVEL non valido: «{livello}». Valori ammessi: {', '.join(LIVELLI_LOG)}.")

    testo = env.get("AGENTE_TIMEOUT", "").strip()
    try:
        timeout = float(testo) if testo else 600.0
    except ValueError:
        timeout = -1.0
    if timeout <= 0:
        raise ErroreConfigurazione(f"AGENTE_TIMEOUT deve essere un numero di secondi maggiore di 0: «{testo}».")

    return Configurazione(
        database_url=database_url,
        agente_url=(env.get("AGENTE_URL", "").strip() or "http://localhost:8001").rstrip("/"),
        agente_timeout=timeout,
        log_level=livello,
    )
