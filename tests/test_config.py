import urllib.error
import urllib.request

import pytest

from assistente.config import (
    AMBITO_PREDEFINITO,
    Configurazione,
    ErroreConfigurazione,
    carica_configurazione,
    scarica_id_modelli,
    verifica_modello,
)

ENV = {
    "LM_BASE_URL": "http://localhost:1234/v1/",
    "LM_MODEL": "google/gemma-4-e4b",
    "TZ_PREDEFINITO": "Europe/Rome",
}


def cfg(**modifiche):
    return Configurazione(**{
        "base_url": "http://localhost:1234/v1",
        "modello": "google/gemma-4-e4b",
        "fuso_predefinito": "Europe/Rome",
        "log_level": "INFO",
        **modifiche,
    })


def test_configurazione_valida():
    c = carica_configurazione(ENV)

    assert c.base_url == "http://localhost:1234/v1"
    assert c.modello == "google/gemma-4-e4b"
    assert c.fuso_predefinito == "Europe/Rome"
    assert c.log_level == "INFO"


@pytest.mark.parametrize("nome", ["LM_BASE_URL", "LM_MODEL", "TZ_PREDEFINITO"])
def test_variabile_mancante(nome):
    env = {k: v for k, v in ENV.items() if k != nome}

    with pytest.raises(ErroreConfigurazione, match=nome):
        carica_configurazione(env)


def test_fuso_predefinito_non_valido():
    with pytest.raises(ErroreConfigurazione, match="Marte/Base"):
        carica_configurazione({**ENV, "TZ_PREDEFINITO": "Marte/Base"})


def test_modello_presente():
    verifica_modello(cfg(), scarica=lambda url: ["google/gemma-4-e4b"])


def test_modello_assente_elenca_id():
    with pytest.raises(ErroreConfigurazione) as errore:
        verifica_modello(cfg(modello="x"), scarica=lambda url: ["a", "b"])

    messaggio = str(errore.value)
    assert "«x»" in messaggio
    assert "a" in messaggio and "b" in messaggio


def test_server_irraggiungibile():
    with pytest.raises(ErroreConfigurazione, match="LM Studio"):
        scarica_id_modelli("http://127.0.0.1:9/v1")


def test_404_suggerisce_v1(monkeypatch):
    def urlopen(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    with pytest.raises(ErroreConfigurazione, match="/v1"):
        scarica_id_modelli("http://localhost:1234")


class RispostaFinta:
    def __init__(self, corpo: bytes):
        self.corpo = corpo

    def read(self, *args):
        return self.corpo

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_200_con_errore_suggerisce_v1(monkeypatch):
    corpo = b'{"error":"Unexpected endpoint or method. (GET /models)"}'
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: RispostaFinta(corpo))

    with pytest.raises(ErroreConfigurazione) as errore:
        scarica_id_modelli("http://localhost:1234")

    assert "/v1" in str(errore.value)
    assert "Unexpected endpoint" in str(errore.value)


def test_corpo_non_json_suggerisce_v1(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: RispostaFinta(b"<html>no</html>"))

    with pytest.raises(ErroreConfigurazione, match="/v1"):
        scarica_id_modelli("http://localhost:1234")


def test_log_level_non_valido():
    with pytest.raises(ErroreConfigurazione, match="VERBOSE"):
        carica_configurazione({**ENV, "LOG_LEVEL": "verbose"})


def test_log_level_minuscolo_valido():
    assert carica_configurazione({**ENV, "LOG_LEVEL": "debug"}).log_level == "DEBUG"


# ---------------------------------------------------------------- lezione 5: variante dell'orologio

def test_variante_predefinita_mcp():
    c = carica_configurazione(ENV)

    assert c.variante == "mcp"
    assert c.orologio_api_url == "http://localhost:8000"


@pytest.mark.parametrize("valore, attesa", [("locale", "locale"), ("FASTAPI", "fastapi"), (" mcp ", "mcp")])
def test_variante_valida(valore, attesa):
    assert carica_configurazione({**ENV, "VARIANTE_OROLOGIO": valore}).variante == attesa


def test_variante_non_valida_elenca_i_valori_ammessi():
    with pytest.raises(ErroreConfigurazione) as errore:
        carica_configurazione({**ENV, "VARIANTE_OROLOGIO": "sole"})

    messaggio = str(errore.value)
    assert "«sole»" in messaggio
    assert "locale" in messaggio and "fastapi" in messaggio and "mcp" in messaggio


def test_url_api_personalizzato_senza_barra_finale():
    c = carica_configurazione({**ENV, "OROLOGIO_API_URL": "http://127.0.0.1:9000/"})

    assert c.orologio_api_url == "http://127.0.0.1:9000"


# ---------------------------------------------------------------- lezione 6: ambito, revisioni, riassunto

def test_predefiniti_lezione_6():
    c = carica_configurazione(ENV)

    assert c.ambito == AMBITO_PREDEFINITO
    assert (c.limite_revisioni, c.soglia_riassunto, c.messaggi_da_conservare) == (2, 12, 6)


def test_ambito_personalizzato_senza_spazi():
    assert carica_configurazione({**ENV, "AMBITO_AGENTE": " solo calcoli "}).ambito == "solo calcoli"


def test_ambito_vuoto_usa_il_predefinito():
    assert carica_configurazione({**ENV, "AMBITO_AGENTE": "  "}).ambito == AMBITO_PREDEFINITO


@pytest.mark.parametrize("nome, valore", [
    ("LIMITE_REVISIONI", "tante"),
    ("SOGLIA_RIASSUNTO", "-1"),
    ("MESSAGGI_DA_CONSERVARE", "2.5"),
])
def test_intero_non_valido_nomina_la_variabile(nome, valore):
    with pytest.raises(ErroreConfigurazione, match=nome):
        carica_configurazione({**ENV, nome: valore})


def test_messaggi_da_conservare_deve_stare_sotto_la_soglia():
    with pytest.raises(ErroreConfigurazione, match="MESSAGGI_DA_CONSERVARE"):
        carica_configurazione({**ENV, "SOGLIA_RIASSUNTO": "4", "MESSAGGI_DA_CONSERVARE": "6"})


def test_soglia_zero_spegne_il_riassunto():
    c = carica_configurazione({**ENV, "SOGLIA_RIASSUNTO": "0", "LIMITE_REVISIONI": "0"})

    assert (c.soglia_riassunto, c.limite_revisioni) == (0, 0)


# ---------------------------------------------------------------- lezione 6, step 6: configurazione della CLI

def test_configurazione_cli_predefinita_senza_variabili_di_lm_studio():
    from assistente.config import carica_configurazione_cli

    c = carica_configurazione_cli({})

    assert (c.agente_url, c.agente_timeout, c.log_level) == ("http://localhost:8001", 600.0, "INFO")


def test_configurazione_cli_personalizzata():
    from assistente.config import carica_configurazione_cli

    c = carica_configurazione_cli({"AGENTE_URL": "http://127.0.0.1:9000/", "AGENTE_TIMEOUT": "30", "LOG_LEVEL": "warning"})

    assert (c.agente_url, c.agente_timeout, c.log_level) == ("http://127.0.0.1:9000", 30.0, "WARNING")


@pytest.mark.parametrize("valore", ["zero", "0", "-5"])
def test_timeout_cli_non_valido(valore):
    from assistente.config import carica_configurazione_cli

    with pytest.raises(ErroreConfigurazione, match="AGENTE_TIMEOUT"):
        carica_configurazione_cli({"AGENTE_TIMEOUT": valore})
