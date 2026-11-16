"""Lezione 6, step 4: preferenze dell'utente lette dalla resource MCP e validate dall'host."""

import json
import logging

import pytest

from assistente.preferenze import Preferenze, carica_preferenze


def da_testo(testo):
    return lambda: testo


def test_preferenze_valide():
    testo = json.dumps({"lingua": "inglese", "fuso_predefinito": "America/New_York", "stile": "dettagliato"})

    p = carica_preferenze(da_testo(testo), "Europe/Rome")

    assert p == Preferenze(lingua="inglese", fuso_predefinito="America/New_York", stile="dettagliato")


def test_campo_mancante_preso_dai_predefiniti():
    p = carica_preferenze(da_testo('{"lingua": "inglese"}'), "Europe/Rome")

    assert (p.lingua, p.fuso_predefinito, p.stile) == ("inglese", "Europe/Rome", "sintetico")


def test_campo_in_piu_ignorato():
    p = carica_preferenze(da_testo('{"stile": "dettagliato", "colore": "blu"}'), "Europe/Rome")

    assert p.stile == "dettagliato"


def errore_di_lettura():
    raise RuntimeError("resource non trovata")


@pytest.mark.parametrize("leggi", [
    da_testo("{non è json"),
    da_testo('{"fuso_predefinito": "Mars/Olympus"}'),
    da_testo('{"stile": "poetico"}'),
    da_testo('{"lingua": "   "}'),
    da_testo("[1, 2]"),
    errore_di_lettura,
], ids=["json-rotto", "fuso-inesistente", "stile-sconosciuto", "lingua-vuota", "non-oggetto", "lettura-fallita"])
def test_errore_porta_ai_predefiniti_con_avviso(leggi, caplog):
    caplog.set_level(logging.WARNING, logger="assistente")

    p = carica_preferenze(leggi, "Asia/Tokyo")

    assert p == Preferenze(lingua="italiano", fuso_predefinito="Asia/Tokyo", stile="sintetico")
    assert "WARNING" in caplog.text and "preferenze" in caplog.text
