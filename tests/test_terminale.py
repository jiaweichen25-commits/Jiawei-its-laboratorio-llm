import io
import os
import subprocess
import sys
from pathlib import Path

import httpx
import openai
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from assistente.grafo import config_sessione, costruisci_grafo
from assistente.modello import descrivi_errore
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


class OutRegistrato(io.StringIO):
    """Registra ogni scrittura separatamente, per vedere i frammenti dello streaming."""

    def __init__(self):
        super().__init__()
        self.scritture = []

    def write(self, testo):
        self.scritture.append(testo)
        return super().write(testo)


def test_streaming_in_ordine():
    modello, grafo = grafo_con(AIMessage("Sono le dieci"))
    out = OutRegistrato()

    conversa(grafo, config_sessione(), lettore("che ore sono?"), out)

    assert [s for s in out.scritture if s in ("Sono ", "le ", "dieci")] == ["Sono ", "le ", "dieci"]
    assert out.getvalue().count("Sono") == 1
    assert len(modello.ricevuti) == 1


def test_uscite():
    modello, grafo = grafo_con()

    conversa(grafo, config_sessione(), lettore("   ", "  ESCI ", "non letto"), io.StringIO())
    conversa(grafo, config_sessione(), lettore(), io.StringIO())

    assert modello.ricevuti == []


def test_errore_connessione_e_ripresa():
    richiesta = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    modello, grafo = grafo_con(openai.APIConnectionError(request=richiesta), AIMessage("ok"))
    config = config_sessione()
    out = io.StringIO()

    conversa(grafo, config, lettore("a", "b", "esci"), out, descrivi_errore=descrivi_errore)

    testo = out.getvalue()
    assert "Connessione a LM Studio fallita" in testo
    assert testo.index("Connessione a LM Studio fallita") < testo.index("ok")
    messaggi = grafo.get_state(config).values["messages"]
    assert [(type(m), m.content) for m in messaggi] == [(HumanMessage, "b"), (AIMessage, "ok")]
    assert "a" not in [m.content for m in modello.ricevuti[1]]


def test_limite_passaggi_e_ripresa():
    _, grafo = grafo_con(GraphRecursionError("troppi"), AIMessage("ok"))
    out = io.StringIO()

    conversa(grafo, config_sessione(), lettore("a", "b"), out)

    assert "Troppi passaggi" in out.getvalue()
    assert "ok" in out.getvalue()


def test_ctrl_c_durante_risposta():
    _, grafo = grafo_con(KeyboardInterrupt())

    conversa(grafo, config_sessione(), lettore("a", "b"), io.StringIO())


def test_output_cp1252():
    radice = Path(__file__).resolve().parent.parent
    comando = "from assistente.__main__ import configura_output; configura_output(); print('→ «x»')"

    esito = subprocess.run(
        [sys.executable, "-c", comando],
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        cwd=radice,
        capture_output=True,
    )

    assert esito.returncode == 0, esito.stderr
