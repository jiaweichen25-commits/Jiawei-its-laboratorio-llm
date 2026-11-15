"""Configurazione da variabili d'ambiente e controlli all'avvio."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

OBBLIGATORIE = ("LM_BASE_URL", "LM_MODEL", "TZ_PREDEFINITO")
LIVELLI_LOG = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
# Lezione 5 (slide 17): le tre varianti con cui il nodo strumenti raggiunge l'orologio.
VARIANTI = ("locale", "fastapi", "mcp")
# Lezione 6 (slide 4): l'ambito dell'agente sta in configurazione, non nel codice. Questo è solo
# il valore usato quando AMBITO_AGENTE non è impostata.
AMBITO_PREDEFINITO = (
    "Assistente del laboratorio del corso su LLM e agenti: saluti e conversazione sulla sessione "
    "in corso, spiegazioni su LLM, agenti, MCP e argomenti di informatica, data e ora nei fusi "
    "orari, calcoli aritmetici, conversioni di unità di misura."
)


class ErroreConfigurazione(Exception):
    """Configurazione mancante o non valida: l'applicazione non può partire."""


@dataclass(frozen=True)
class Configurazione:
    base_url: str
    modello: str
    fuso_predefinito: str
    log_level: str
    # Lezione 5: valori predefiniti, così le configurazioni della lezione 4 restano valide.
    variante: str = "mcp"                               # VARIANTE_OROLOGIO
    orologio_api_url: str = "http://localhost:8000"     # OROLOGIO_API_URL (solo variante fastapi)
    # Lezione 6: i tre nodi nuovi del grafo. Con 0 il revisore o il riassunto restano spenti.
    ambito: str = AMBITO_PREDEFINITO                    # AMBITO_AGENTE (router)
    limite_revisioni: int = 2                           # LIMITE_REVISIONI (revisore)
    soglia_riassunto: int = 12                          # SOGLIA_RIASSUNTO (riassunto)
    messaggi_da_conservare: int = 6                     # MESSAGGI_DA_CONSERVARE (riassunto)


def fuso_valido(nome: str) -> bool:
    try:
        ZoneInfo(nome)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def _intero(env: Mapping[str, str], nome: str, predefinito: int) -> int:
    """Legge un intero non negativo facoltativo; l'errore nomina la variabile."""
    testo = env.get(nome, "").strip()
    if not testo:
        return predefinito
    try:
        valore = int(testo)
    except ValueError:
        valore = -1
    if valore < 0:
        raise ErroreConfigurazione(f"{nome} deve essere un numero intero maggiore o uguale a 0: «{testo}».")
    return valore


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

    livello = env.get("LOG_LEVEL", "").strip().upper() or "INFO"
    if livello not in LIVELLI_LOG:
        raise ErroreConfigurazione(
            f"LOG_LEVEL non valido: «{livello}». Valori ammessi: {', '.join(LIVELLI_LOG)}."
        )

    # Variante dell'orologio: facoltativa, predefinita «mcp»; maiuscole e spazi non contano.
    variante = env.get("VARIANTE_OROLOGIO", "").strip().lower() or "mcp"
    if variante not in VARIANTI:
        raise ErroreConfigurazione(
            f"VARIANTE_OROLOGIO non valida: «{variante}». Valori ammessi: {', '.join(VARIANTI)}."
        )

    limite_revisioni = _intero(env, "LIMITE_REVISIONI", 2)
    soglia_riassunto = _intero(env, "SOGLIA_RIASSUNTO", 12)
    da_conservare = _intero(env, "MESSAGGI_DA_CONSERVARE", 6)
    # Il riassunto deve lasciare qualcosa da comprimere: se si conservano tutti i messaggi non serve.
    if soglia_riassunto > 0 and not 2 <= da_conservare < soglia_riassunto:
        raise ErroreConfigurazione(
            f"MESSAGGI_DA_CONSERVARE deve essere almeno 2 e minore di SOGLIA_RIASSUNTO "
            f"({soglia_riassunto}): «{da_conservare}»."
        )

    return Configurazione(
        base_url=env["LM_BASE_URL"].strip().rstrip("/"),
        modello=env["LM_MODEL"].strip(),
        fuso_predefinito=fuso,
        log_level=livello,
        variante=variante,
        orologio_api_url=(env.get("OROLOGIO_API_URL", "").strip() or "http://localhost:8000").rstrip("/"),
        ambito=env.get("AMBITO_AGENTE", "").strip() or AMBITO_PREDEFINITO,
        limite_revisioni=limite_revisioni,
        soglia_riassunto=soglia_riassunto,
        messaggi_da_conservare=da_conservare,
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
    except ValueError as exc:  # corpo non JSON (JSONDecodeError)
        raise ErroreConfigurazione(
            f"Risposta inattesa da {url}: non è l'elenco dei modelli. LM_BASE_URL deve terminare con /v1."
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ErroreConfigurazione(
            f"LM Studio non raggiungibile su {base_url}: controllare che il server sia avviato, URL e porta."
        ) from exc
    if not isinstance(dati, dict) or not isinstance(dati.get("data"), list):
        dettaglio = dati.get("error") if isinstance(dati, dict) else None
        raise ErroreConfigurazione(
            f"Risposta inattesa da {url}: LM_BASE_URL deve terminare con /v1."
            + (f" Il server dice: {dettaglio}" if dettaglio else "")
        )
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
