from langchain_core.messages import AIMessage, HumanMessage

from assistente.grafo import costruisci_grafo


def test_grafo_fisso_risponde_una_volta():
    stato = costruisci_grafo().invoke({"messages": [HumanMessage("ciao")]})

    assert len(stato["messages"]) == 2
    ultimo = stato["messages"][-1]
    assert isinstance(ultimo, AIMessage)
    assert ultimo.content == "Il grafo è in esecuzione."
