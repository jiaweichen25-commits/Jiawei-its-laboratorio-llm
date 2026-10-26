"""Grafo LangGraph dell'assistente: stato, nodi e instradamento."""

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph

LIMITE_PASSAGGI = 10


def config_sessione() -> dict:
    """Configurazione di esecuzione: un solo thread per la sessione e limite ai passaggi."""
    return {"configurable": {"thread_id": "sessione"}, "recursion_limit": LIMITE_PASSAGGI}


def costruisci_grafo(checkpointer=None):
    def modello(state: MessagesState) -> dict:
        return {"messages": [AIMessage("Il grafo è in esecuzione.")]}

    grafo = StateGraph(MessagesState)
    grafo.add_node("modello", modello)
    grafo.add_edge(START, "modello")
    grafo.add_edge("modello", END)
    return grafo.compile(checkpointer=checkpointer)
