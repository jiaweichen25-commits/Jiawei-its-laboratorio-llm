"""Configurazione da variabili d'ambiente e controlli all'avvio."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

OBBLIGATORIE = ("LM_BASE_URL", "LM_MODEL", "TZ_PREDEFINITO")


class ErroreConfigurazione(Exception):
    """Configurazione mancante o non valida: l'applicazione non può partire."""


@dataclass(frozen=True)
class Configurazione:
    base_url: str
    modello: str
    fuso_predefinito: str
    log_level: str


def fuso_valido(nome: str) -> bool:
    try:
        ZoneInfo(nome)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def carica_configurazione(env: Mapping[str, str]) -> Configurazione:
    mancanti = [nome for nome in OBBLIGATORIE if not env.get(nome, "").strip()]
    if mancanti:
        raise ErroreConfigurazione(
            "Variabili mancanti: " + ", ".join(mancanti) + ". Vedi .env.example."
        )

    fuso = env["TZ_PREDEFINITO"].strip()
    if not fuso_valido(fuso):
        raise ErroreConfigurazione(
            f"TZ_PREDEFINITO non è un fuso orario IANA valido: «{fuso}» (esempio: Europe/Rome)."
        )

    return Configurazione(
        base_url=env["LM_BASE_URL"].strip().rstrip("/"),
        modello=env["LM_MODEL"].strip(),
        fuso_predefinito=fuso,
        log_level=env.get("LOG_LEVEL", "").strip().upper() or "INFO",
    )


def scarica_id_modelli(base_url: str) -> list[str]:
    """Restituisce gli ID dei modelli esposti da LM Studio (GET /models)."""
    url = f"{base_url}/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as risposta:
            dati = json.load(risposta)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ErroreConfigurazione(
                f"Endpoint non trovato ({url}): LM_BASE_URL deve terminare con /v1."
            ) from exc
        raise ErroreConfigurazione(f"LM Studio ha risposto con errore HTTP {exc.code} su {url}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ErroreConfigurazione(
            f"LM Studio non raggiungibile su {base_url}: controllare che il server sia avviato, URL e porta."
        ) from exc
    return [modello["id"] for modello in dati["data"]]


def verifica_modello(
    cfg: Configurazione, scarica: Callable[[str], list[str]] = scarica_id_modelli
) -> None:
    disponibili = scarica(cfg.base_url)
    if cfg.modello not in disponibili:
        raise ErroreConfigurazione(
            f"Il modello «{cfg.modello}» non è tra quelli esposti da LM Studio. "
            f"Disponibili: {', '.join(disponibili) or 'nessuno'}."
        )
