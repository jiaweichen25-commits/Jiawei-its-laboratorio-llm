import urllib.error
import urllib.request

import pytest

from assistente.config import (
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
