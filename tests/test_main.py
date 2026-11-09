"""Test dell'avvio (__main__) senza LM Studio: il controllo del modello viene sostituito."""

import assistente.__main__ as avvio
from assistente.client_mcp import trasporto_stdio

ENV = {
    "LM_BASE_URL": "http://localhost:1234/v1",
    "LM_MODEL": "google/gemma-4-e4b",
    "TZ_PREDEFINITO": "Europe/Rome",
}


def test_server_mcp_che_non_parte_esce_con_codice_1(monkeypatch, capsys):
    for nome, valore in ENV.items():
        monkeypatch.setenv(nome, valore)
    monkeypatch.setattr(avvio, "load_dotenv", lambda **kw: None)     # niente .env reale
    monkeypatch.setattr(avvio, "verifica_modello", lambda cfg: None)  # niente LM Studio
    monkeypatch.setattr(avvio, "trasporto_stdio", lambda: trasporto_stdio(modulo="assistente.non_esiste"))

    assert avvio.main() == 1
    assert "server MCP" in capsys.readouterr().err
