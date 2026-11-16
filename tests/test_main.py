"""Test dell'avvio senza LM Studio: la CLI (__main__) e la costruzione dell'agente del servizio."""

import pytest

import assistente.__main__ as avvio
import assistente.agente as agente_mod
from assistente.client_mcp import ErroreCollegamentoMCP, trasporto_stdio
from assistente.config import carica_configurazione

ENV = {
    "LM_BASE_URL": "http://localhost:1234/v1",
    "LM_MODEL": "google/gemma-4-e4b",
    "TZ_PREDEFINITO": "Europe/Rome",
}


def test_crea_agente_con_server_mcp_che_non_parte(monkeypatch):
    monkeypatch.setattr(agente_mod, "trasporto_stdio", lambda: trasporto_stdio(modulo="assistente.non_esiste"))

    with pytest.raises(ErroreCollegamentoMCP):
        agente_mod.crea_agente(carica_configurazione(ENV))


def test_cli_con_servizio_spento_esce_con_codice_1(monkeypatch, capsys):
    monkeypatch.setattr(avvio, "load_dotenv", lambda **kw: None)  # niente .env reale
    monkeypatch.setenv("AGENTE_URL", "http://127.0.0.1:9")         # porta su cui non risponde nessuno

    assert avvio.main() == 1
    assert "uvicorn" in capsys.readouterr().err


def test_cli_con_modello_spento_esce_con_codice_1(monkeypatch, capsys):
    class ClienteFinto:
        def __init__(self, *a, **k):
            pass

        def stato(self):
            return {"agente": "ok", "server_mcp": "ok", "modello": "LM Studio non raggiungibile"}

    monkeypatch.setattr(avvio, "load_dotenv", lambda **kw: None)
    monkeypatch.setattr(avvio, "ClienteAgente", ClienteFinto)

    assert avvio.main() == 1
    assert "LM Studio non raggiungibile" in capsys.readouterr().err
