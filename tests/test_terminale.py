import io

from langgraph.checkpoint.memory import InMemorySaver

from assistente.grafo import config_sessione, costruisci_grafo
from assistente.terminale import conversa


def lettore(*righe):
    righe = iter(righe)

    def leggi(prompt=""):
        try:
            return next(righe)
        except StopIteration:
            raise EOFError

    return leggi


def test_risposta_fissa_ed_esci():
    out = io.StringIO()

    conversa(costruisci_grafo(InMemorySaver()), config_sessione(), lettore("ciao", "esci"), out)

    assert "Il grafo è in esecuzione." in out.getvalue()
