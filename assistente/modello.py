"""Collegamento al modello servito da LM Studio (API compatibile OpenAI)."""

import openai
from langchain_openai import ChatOpenAI

from assistente.config import Configurazione


def crea_modello(cfg: Configurazione) -> ChatOpenAI:
    # LM Studio ignora la chiave, ma il client ne richiede una.
    return ChatOpenAI(
        base_url=cfg.base_url,
        api_key="lm-studio",
        model=cfg.modello,
        temperature=0.2,
        timeout=120,
        max_retries=0,
    )


def descrivi_errore(exc: BaseException) -> str | None:
    """Messaggio per l'utente se l'errore viene da LM Studio, altrimenti None."""
    # APITimeoutError è una sottoclasse di APIConnectionError: va controllato prima.
    if isinstance(exc, openai.APITimeoutError):
        return "Attesa scaduta: LM Studio non ha risposto in tempo."
    if isinstance(exc, openai.APIConnectionError):
        return "Connessione a LM Studio fallita: controllare server, URL e porta."
    if isinstance(exc, openai.APIStatusError):
        return f"Errore HTTP {exc.status_code} da LM Studio: {exc.message}"
    return None
