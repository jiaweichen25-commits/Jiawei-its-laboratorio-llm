import httpx
import openai

from assistente.config import Configurazione
from assistente.modello import crea_modello, descrivi_errore

RICHIESTA = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")


def test_descrivi_errore():
    assert "Attesa scaduta" in descrivi_errore(openai.APITimeoutError(request=RICHIESTA))
    assert "Connessione a LM Studio fallita" in descrivi_errore(openai.APIConnectionError(request=RICHIESTA))
    assert descrivi_errore(ValueError()) is None


def test_crea_modello():
    cfg = Configurazione("http://localhost:1234/v1", "google/gemma-4-e4b", "Europe/Rome", "INFO")

    modello = crea_modello(cfg)

    assert modello.model_name == "google/gemma-4-e4b"
    assert modello.openai_api_base == "http://localhost:1234/v1"
    assert modello.max_retries == 0
