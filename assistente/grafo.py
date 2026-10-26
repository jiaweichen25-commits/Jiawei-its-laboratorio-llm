"""Grafo LangGraph dell'assistente: stato, nodi e instradamento."""

import logging
import time
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph

LIMITE_PASSAGGI = 10

log = logging.getLogger("assistente.grafo")


def config_sessione() -> dict:
    """Configurazione di esecuzione: un solo thread per la sessione e limite ai passaggi."""
    return {"configurable": {"thread_id": "sessione"}, "recursion_limit": LIMITE_PASSAGGI}


def messaggio_sistema(fuso: str) -> SystemMessage:
    return SystemMessage(
        "Rispondi in italiano. Per conoscere data o ora usa sempre lo strumento `orologio`, "
        f"senza inventarle. Se l'utente non indica un fuso orario, usa `{fuso}`."
    )


def costruisci_grafo(
    modello: BaseChatModel,
    fuso_predefinito: str,
    strumenti: Sequence[BaseTool] = (),
    checkpointer=None,
):
    llm = modello.bind_tools(list(strumenti)) if strumenti else modello

    def nodo_modello(state: MessagesState) -> dict:
        # Il messaggio di sistema si ricostruisce a ogni chiamata e non entra nello stato.
        log.info("modello: inizio chiamata")
        inizio = time.perf_counter()
        risposta = llm.invoke([messaggio_sistema(fuso_predefinito), *state["messages"]])
        log.info(
            "modello: fine chiamata (%.1f s, tool_calls=%d)",
            time.perf_counter() - inizio,
            len(getattr(risposta, "tool_calls", [])),
        )
        return {"messages": [risposta]}

    grafo = StateGraph(MessagesState)
    grafo.add_node("modello", nodo_modello)
    grafo.add_edge(START, "modello")
    grafo.add_edge("modello", END)
    return grafo.compile(checkpointer=checkpointer)
