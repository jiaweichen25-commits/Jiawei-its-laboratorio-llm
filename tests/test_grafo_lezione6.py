"""Lezione 6: i nodi nuovi del grafo (router, rifiuto, revisore, riassunto) con il modello finto.

Il modello finto è uno solo e consuma le risposte in ordine: prima quella del router,
poi quella dell'agente, e così via, nello stesso ordine in cui i nodi vengono eseguiti.
"""

import json
import logging
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage

from assistente.grafo import LIMITE_PASSAGGI, OpzioniGrafo, costruisci_grafo, risposta_rifiuto
from assistente.strumenti import crea_orologio
from tests.modello_finto import ModelloFinto

ISTANTE = datetime(2026, 10, 26, 15, 42, 10, tzinfo=timezone.utc)
ORA_TOKYO = "2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì"


def router(categoria, motivo="m"):
    """Risposta JSON che il nodo router si aspetta dal modello."""
    return AIMessage(json.dumps({"categoria": categoria, "motivo": motivo}))


def esegui(opzioni, *risposte, domanda="Che ore sono a Tokyo?"):
    modello = ModelloFinto(risposte=list(risposte))
    grafo = costruisci_grafo(modello, "Europe/Rome", strumenti=[crea_orologio(lambda: ISTANTE)], opzioni=opzioni)
    stato = grafo.invoke({"messages": [HumanMessage(domanda)]}, {"recursion_limit": LIMITE_PASSAGGI})
    return modello, stato


# ---------------------------------------------------------------- step 1: router

SOLO_ROUTER = OpzioniGrafo(ambito="data e ora")


def test_router_in_ambito_passa_all_agente(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    _, stato = esegui(SOLO_ROUTER, router("conversazione"), AIMessage("Ciao!"))

    assert stato["messages"][-1].content == "Ciao!"
    assert "router: categoria=conversazione motivo=m" in caplog.text
    assert "modello: inizio chiamata" in caplog.text


def test_router_fuori_ambito_rifiuta_senza_agente(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    modello, stato = esegui(SOLO_ROUTER, router("fuori_ambito"), domanda="Dammi una ricetta")

    assert stato["messages"][-1].content == risposta_rifiuto("data e ora")
    assert len(modello.ricevuti) == 1  # solo la chiamata del router: l'agente non è stato eseguito
    assert "modello: inizio chiamata" not in caplog.text
    assert "router: categoria=fuori_ambito" in caplog.text


def test_router_output_non_valido_lascia_passare(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    _, stato = esegui(SOLO_ROUTER, AIMessage("boh"), AIMessage("Ciao!"))

    assert stato["messages"][-1].content == "Ciao!"
    assert "WARNING" in caplog.text


def test_router_non_vede_gli_strumenti():
    modello, _ = esegui(SOLO_ROUTER, router("conversazione"), AIMessage("Ciao!"))

    assert "orologio" not in modello.ricevuti[0][0].content


def test_la_decisione_del_router_non_entra_nella_cronologia():
    _, stato = esegui(SOLO_ROUTER, router("conversazione"), AIMessage("Ciao!"))

    assert [type(m) for m in stato["messages"]] == [HumanMessage, AIMessage]


def test_senza_opzioni_il_grafo_e_quello_della_lezione_5():
    grafo = costruisci_grafo(ModelloFinto(risposte=[]), "Europe/Rome")

    assert set(grafo.get_graph().nodes) == {"__start__", "modello", "strumenti", "__end__"}
