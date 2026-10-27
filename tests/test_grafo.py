import logging
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from assistente.grafo import LIMITE_PASSAGGI, costruisci_grafo
from assistente.strumenti import crea_orologio
from tests.modello_finto import ModelloFinto


def test_risposta_del_modello():
    modello = ModelloFinto(risposte=[AIMessage("Ciao!")])

    stato = costruisci_grafo(modello, "Europe/Rome").invoke({"messages": [HumanMessage("ciao")]})

    assert stato["messages"][-1].content == "Ciao!"
    sistema = modello.ricevuti[0][0]
    assert isinstance(sistema, SystemMessage)
    assert "Europe/Rome" in sistema.content
    assert "orologio" in sistema.content


def test_log_inizio_fine_modello(caplog):
    caplog.set_level(logging.INFO, logger="assistente")
    modello = ModelloFinto(risposte=[AIMessage("Ciao!")])

    costruisci_grafo(modello, "Europe/Rome").invoke({"messages": [HumanMessage("ciao")]})

    assert "modello: inizio chiamata" in caplog.text
    assert "modello: fine chiamata" in caplog.text


ISTANTE = datetime(2026, 10, 26, 15, 42, 10, tzinfo=timezone.utc)
ORA_TOKYO = "2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì"


def chiamata(fuso, id="c1", nome="orologio", args=None):
    return AIMessage("", tool_calls=[{"name": nome, "args": {"fuso": fuso} if args is None else args, "id": id}])


def esegui(*risposte, domanda="Che ore sono a Tokyo?"):
    modello = ModelloFinto(risposte=list(risposte))
    grafo = costruisci_grafo(modello, "Europe/Rome", strumenti=[crea_orologio(lambda: ISTANTE)])
    return modello, grafo.invoke({"messages": [HumanMessage(domanda)]}, {"recursion_limit": LIMITE_PASSAGGI})


def test_senza_strumenti_va_a_end():
    _, stato = esegui(AIMessage("Ciao!"))

    assert not any(isinstance(m, ToolMessage) for m in stato["messages"])


def test_ciclo_orologio():
    modello, stato = esegui(chiamata("Asia/Tokyo"), AIMessage("Sono le 00:42"))

    tipi = [type(m) for m in stato["messages"]]
    assert tipi == [HumanMessage, AIMessage, ToolMessage, AIMessage]
    risultato = stato["messages"][2]
    assert risultato.content == ORA_TOKYO
    assert risultato.tool_call_id == "c1"
    assert len(modello.ricevuti) == 2
    assert modello.ricevuti[1][-1].content == ORA_TOKYO


def test_strumento_sconosciuto():
    _, stato = esegui(chiamata("Europe/Rome", nome="meteo"), AIMessage("Non posso."))

    assert stato["messages"][2].content.startswith("Errore: strumento sconosciuto")


def test_argomenti_non_validi():
    _, stato = esegui(chiamata(None, args={}), AIMessage("Riprovo."))

    assert stato["messages"][2].content.startswith("Errore:")


def test_limite_passaggi():
    with pytest.raises(GraphRecursionError):
        esegui(*[chiamata("UTC", id=f"c{i}") for i in range(20)])


def test_log_strumenti(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    esegui(chiamata("Asia/Tokyo"), AIMessage("Sono le 00:42"))

    assert "strumenti: richiesta orologio" in caplog.text
    assert "strumenti: risultato orologio" in caplog.text


def test_due_chiamate_in_ordine():
    due = AIMessage("", tool_calls=[
        {"name": "orologio", "args": {"fuso": "Europe/Rome"}, "id": "c1"},
        {"name": "orologio", "args": {"fuso": "Asia/Tokyo"}, "id": "c2"},
    ])

    _, stato = esegui(due, AIMessage("Fatto."))

    risultati = [m for m in stato["messages"] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in risultati] == ["c1", "c2"]
    assert risultati[1].content == ORA_TOKYO
