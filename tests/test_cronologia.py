from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from assistente.grafo import config_sessione, costruisci_grafo
from tests.modello_finto import ModelloFinto


def due_turni():
    modello = ModelloFinto(risposte=[AIMessage("Piacere, Jiawei."), AIMessage("Ti chiami Jiawei.")])
    grafo = costruisci_grafo(modello, "Europe/Rome", checkpointer=InMemorySaver())
    config = config_sessione()
    grafo.invoke({"messages": [HumanMessage("Mi chiamo Jiawei")]}, config)
    grafo.invoke({"messages": [HumanMessage("Come mi chiamo?")]}, config)
    return modello, grafo.get_state(config).values["messages"]


def test_due_turni_senza_duplicati():
    modello, messaggi = due_turni()

    assert [(type(m), m.content) for m in messaggi] == [
        (HumanMessage, "Mi chiamo Jiawei"),
        (AIMessage, "Piacere, Jiawei."),
        (HumanMessage, "Come mi chiamo?"),
        (AIMessage, "Ti chiami Jiawei."),
    ]
    secondo = modello.ricevuti[1]
    assert isinstance(secondo[0], SystemMessage)
    assert [m.content for m in secondo[1:]] == ["Mi chiamo Jiawei", "Piacere, Jiawei.", "Come mi chiamo?"]


def test_sistema_non_salvato():
    _, messaggi = due_turni()

    assert not any(isinstance(m, SystemMessage) for m in messaggi)
