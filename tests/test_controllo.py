"""Lezione 6: logica dei nodi di controllo (router, revisore, riassunto), senza grafo."""

import logging

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from assistente.controllo import (
    DecisioneRouter,
    chiedi_strutturato,
    e_revisione,
    indicazione_revisione,
    messaggi_revisore,
    messaggi_router,
    trascrivi,
)
from tests.modello_finto import ModelloFinto


# ---------------------------------------------------------------- output strutturato

def test_chiedi_strutturato_valido():
    modello = ModelloFinto(risposte=[AIMessage('{"categoria": "fuori_ambito", "motivo": "ricetta"}')])

    decisione = chiedi_strutturato(modello, DecisioneRouter, [HumanMessage("x")])

    assert (decisione.categoria, decisione.motivo) == ("fuori_ambito", "ricetta")


@pytest.mark.parametrize("testo", ["non so", '{"categoria": "boh", "motivo": "x"}', ""])
def test_chiedi_strutturato_non_valido_restituisce_none(testo, caplog):
    caplog.set_level(logging.WARNING, logger="assistente")
    modello = ModelloFinto(risposte=[AIMessage(testo)])

    assert chiedi_strutturato(modello, DecisioneRouter, [HumanMessage("x")]) is None
    assert "WARNING" in caplog.text


# ---------------------------------------------------------------- trascrizione

def test_trascrivi():
    messaggi = [
        HumanMessage("ciao"),
        AIMessage("", tool_calls=[{"name": "orologio", "args": {}, "id": "c1"}]),
        ToolMessage("10:00", tool_call_id="c1", name="orologio"),
        AIMessage("Sono le 10"),
    ]

    assert trascrivi(messaggi) == "Utente: ciao\nStrumento orologio: 10:00\nAssistente: Sono le 10"


def test_e_revisione():
    assert e_revisione(HumanMessage("[Revisione] manca una parte"))
    assert not e_revisione(HumanMessage("ciao"))
    assert not e_revisione(AIMessage("[Revisione] non sono un messaggio utente"))


# ---------------------------------------------------------------- router

def test_messaggi_router_contiene_ambito_e_contesto():
    cronologia = [HumanMessage("Che ore sono a Roma?"), AIMessage("Le 10."), HumanMessage("e a Tokyo?")]

    sistema, utente = messaggi_router("data e ora", "", cronologia)

    assert isinstance(sistema, SystemMessage)
    assert "data e ora" in sistema.content
    assert "Che ore sono a Roma?" in utente.content and "e a Tokyo?" in utente.content


def test_messaggi_router_include_il_riassunto():
    _, utente = messaggi_router("data e ora", "L'utente si chiama Jiawei.", [HumanMessage("Come mi chiamo?")])

    assert "L'utente si chiama Jiawei." in utente.content


def test_messaggi_router_solo_ultimi_quattro_senza_strumenti_ne_revisioni():
    cronologia = [
        HumanMessage("vecchissima"), AIMessage("r0"),
        HumanMessage("d1"), AIMessage("", tool_calls=[{"name": "orologio", "args": {}, "id": "c1"}]),
        ToolMessage("10:00", tool_call_id="c1", name="orologio"), AIMessage("r1"),
        HumanMessage("[Revisione] manca una parte"), AIMessage("r1 completa"),
        HumanMessage("d2"),
    ]

    _, utente = messaggi_router("data e ora", "", cronologia)

    assert "vecchissima" not in utente.content
    assert "10:00" not in utente.content and "[Revisione]" not in utente.content
    assert all(testo in utente.content for testo in ("d1", "r1", "r1 completa", "d2"))


# ---------------------------------------------------------------- revisore

def test_messaggi_revisore_domanda_risultati_e_risposta():
    cronologia = [
        HumanMessage("turno vecchio"), AIMessage("risposta vecchia"),
        HumanMessage("Che ore sono a Tokyo e quanto fa 12 * 8?"),
        AIMessage("", tool_calls=[{"name": "orologio", "args": {}, "id": "c1"}]),
        ToolMessage("00:42", tool_call_id="c1", name="orologio"),
        AIMessage("A Tokyo sono le 00:42."),
    ]

    sistema, utente = messaggi_revisore(cronologia)

    assert isinstance(sistema, SystemMessage)
    assert "Che ore sono a Tokyo e quanto fa 12 * 8?" in utente.content
    assert "Strumento orologio: 00:42" in utente.content
    assert "A Tokyo sono le 00:42." in utente.content
    assert "turno vecchio" not in utente.content and "risposta vecchia" not in utente.content


def test_messaggi_revisore_la_domanda_non_e_l_indicazione_di_revisione():
    cronologia = [
        HumanMessage("Che ore sono a Tokyo e quanto fa 12 * 8?"), AIMessage("A Tokyo sono le 00:42."),
        indicazione_revisione("manca il calcolo"), AIMessage("Sono le 00:42 e fa 96."),
    ]

    _, utente = messaggi_revisore(cronologia)

    assert "Che ore sono a Tokyo e quanto fa 12 * 8?" in utente.content
    assert "Sono le 00:42 e fa 96." in utente.content
    assert "A Tokyo sono le 00:42." not in utente.content  # la bozza scartata non è la risposta da valutare


def test_indicazione_revisione():
    indicazione = indicazione_revisione("manca il calcolo")

    assert e_revisione(indicazione)
    assert "manca il calcolo" in indicazione.content
