"""Lezione 6: logica dei nodi di controllo (router, revisore, riassunto), senza grafo."""

import logging

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from assistente.controllo import (
    DecisioneRouter,
    chiedi_strutturato,
    e_revisione,
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
