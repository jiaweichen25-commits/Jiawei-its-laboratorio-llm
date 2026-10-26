import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from assistente.grafo import costruisci_grafo
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
