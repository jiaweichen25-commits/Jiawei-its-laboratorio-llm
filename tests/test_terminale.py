import io

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from assistente.grafo import config_sessione, costruisci_grafo
from assistente.terminale import conversa
from tests.modello_finto import ModelloFinto


def lettore(*righe):
    righe = iter(righe)

    def leggi(prompt=""):
        try:
            return next(righe)
        except StopIteration:
            raise EOFError

    return leggi


def grafo_con(*risposte):
    modello = ModelloFinto(risposte=list(risposte))
    return modello, costruisci_grafo(modello, "Europe/Rome", checkpointer=InMemorySaver())


def test_risposta_ed_esci():
    _, grafo = grafo_con(AIMessage("Ciao!"))
    out = io.StringIO()

    conversa(grafo, config_sessione(), lettore("ciao", "esci"), out)

    assert "Ciao!" in out.getvalue()
