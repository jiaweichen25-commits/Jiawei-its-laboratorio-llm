"""Lezione 6: i nodi nuovi del grafo (router, rifiuto, revisore, riassunto) con il modello finto.

Il modello finto è uno solo e consuma le risposte in ordine: prima quella del router,
poi quella dell'agente, e così via, nello stesso ordine in cui i nodi vengono eseguiti.
"""

import json
import logging
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

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


# ---------------------------------------------------------------- step 2: revisore

SOLO_REVISORE = OpzioniGrafo(limite_revisioni=2)


def revisore(coerente, motivo="m"):
    """Risposta JSON che il nodo revisore si aspetta dal modello."""
    return AIMessage(json.dumps({"coerente": coerente, "motivo": motivo}))


def chiamata(fuso, id="c1"):
    return AIMessage("", tool_calls=[{"name": "orologio", "args": {"fuso": fuso}, "id": id}])


def test_revisore_approva_al_primo_passaggio(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    modello, stato = esegui(SOLO_REVISORE, AIMessage("Sono le 10."), revisore(True))

    assert [type(m) for m in stato["messages"]] == [HumanMessage, AIMessage]
    assert stato["messages"][-1].content == "Sono le 10."
    assert "revisore: coerente" in caplog.text
    assert modello.risposte == []


def test_revisore_boccia_poi_approva(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    _, stato = esegui(
        SOLO_REVISORE,
        AIMessage("Sono le 10."), revisore(False, "manca il calcolo"),
        AIMessage("Sono le 10 e fa 96."), revisore(True),
    )

    messaggi = stato["messages"]
    assert messaggi[-1].content == "Sono le 10 e fa 96."
    assert messaggi[2].content.startswith("[Revisione]") and "manca il calcolo" in messaggi[2].content
    assert stato["revisioni"] == 1
    assert "revisore: non coerente (revisione 1 di 2) motivo=manca il calcolo" in caplog.text


def test_l_agente_riceve_l_indicazione_del_revisore():
    modello, _ = esegui(
        SOLO_REVISORE, AIMessage("Sono le 10."), revisore(False, "manca il calcolo"), AIMessage("ok"), revisore(True)
    )

    # ricevuti: [0] agente, [1] revisore, [2] agente dopo la bocciatura
    assert "manca il calcolo" in modello.ricevuti[2][-1].content


def test_revisore_che_rifiuta_sempre_si_ferma_al_limite(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    modello, stato = esegui(
        SOLO_REVISORE,
        AIMessage("bozza1"), revisore(False), AIMessage("bozza2"), revisore(False), AIMessage("bozza3"), revisore(False),
    )

    assert stato["messages"][-1].content == "bozza3"
    assert stato["revisioni"] == 2
    assert "limite di revisioni raggiunto" in caplog.text
    assert modello.risposte == []  # tre bozze e tre giudizi: nessuna chiamata oltre il limite


def test_dopo_la_bocciatura_l_agente_puo_usare_uno_strumento():
    _, stato = esegui(
        SOLO_REVISORE,
        AIMessage("Non so."), revisore(False, "non dice l'ora"),
        chiamata("Asia/Tokyo"), AIMessage("Sono le 00:42"), revisore(True),
    )

    assert any(isinstance(m, ToolMessage) and m.content == ORA_TOKYO for m in stato["messages"])
    assert stato["messages"][-1].content == "Sono le 00:42"
    assert stato["revisioni"] == 1


def test_il_revisore_riceve_domanda_risultati_e_risposta():
    modello, _ = esegui(SOLO_REVISORE, chiamata("Asia/Tokyo"), AIMessage("Sono le 00:42"), revisore(True))

    richiesta = modello.ricevuti[-1][1].content
    assert "Che ore sono a Tokyo?" in richiesta
    assert ORA_TOKYO in richiesta
    assert "Sono le 00:42" in richiesta


def test_revisore_output_non_valido_approva(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    _, stato = esegui(SOLO_REVISORE, AIMessage("Sono le 10."), AIMessage("boh"))

    assert stato["messages"][-1].content == "Sono le 10."
    assert "WARNING" in caplog.text


def test_router_e_revisore_insieme():
    opzioni = OpzioniGrafo(ambito="data e ora", limite_revisioni=2)

    modello, stato = esegui(opzioni, router("conversazione"), AIMessage("Sono le 10."), revisore(True))
    assert stato["messages"][-1].content == "Sono le 10." and modello.risposte == []

    modello, stato = esegui(opzioni, router("fuori_ambito"))
    assert stato["messages"][-1].content == risposta_rifiuto("data e ora")
    assert len(modello.ricevuti) == 1  # fuori ambito: né agente né revisore
