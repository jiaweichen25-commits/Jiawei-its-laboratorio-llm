import io
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import openai
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from assistente.grafo import OpzioniGrafo, config_sessione, costruisci_grafo, risposta_rifiuto
from assistente.modello import descrivi_errore
from assistente.strumenti import crea_orologio
from assistente.terminale import conversa, formatta_traccia
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


def test_formatta_traccia():
    assert formatta_traccia("orologio", {"fuso": "Asia/Tokyo"}, "X") == '[strumento] orologio(fuso="Asia/Tokyo") → X'


def test_testo_poi_traccia():
    chiamata = AIMessage("Controllo l'ora.", tool_calls=[
        {"name": "orologio", "args": {"fuso": "Asia/Tokyo"}, "id": "c1"},
    ])
    modello = ModelloFinto(risposte=[chiamata, AIMessage("Sono le 00:42.")])
    orologio = crea_orologio(lambda: datetime(2026, 10, 26, 15, 42, 10, tzinfo=timezone.utc))
    grafo = costruisci_grafo(modello, "Europe/Rome", strumenti=[orologio], checkpointer=InMemorySaver())
    out = io.StringIO()

    conversa(grafo, config_sessione(), lettore("Che ore sono a Tokyo?"), out)

    traccia = '[strumento] orologio(fuso="Asia/Tokyo") → 2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì'
    assert f"Controllo l'ora.\n{traccia}\nSono le 00:42." in out.getvalue()


def test_due_chiamate_due_tracce_in_ordine():
    chiamate = AIMessage("", tool_calls=[
        {"name": "orologio", "args": {"fuso": "Europe/Rome"}, "id": "c1"},
        {"name": "orologio", "args": {"fuso": "Asia/Tokyo"}, "id": "c2"},
    ])
    modello = ModelloFinto(risposte=[chiamate, AIMessage("Fatto.")])
    orologio = crea_orologio(lambda: datetime(2026, 10, 26, 15, 42, 10, tzinfo=timezone.utc))
    grafo = costruisci_grafo(modello, "Europe/Rome", strumenti=[orologio], checkpointer=InMemorySaver())
    out = io.StringIO()

    conversa(grafo, config_sessione(), lettore("Ora a Roma e a Tokyo?"), out)

    tracce = [r for r in out.getvalue().splitlines() if r.startswith("[strumento]")]
    assert len(tracce) == 2
    assert 'orologio(fuso="Europe/Rome")' in tracce[0]
    assert 'orologio(fuso="Asia/Tokyo")' in tracce[1]


# ---------------------------------------------------------------- lezione 6

def grafo_lezione6(opzioni, *risposte):
    modello = ModelloFinto(risposte=list(risposte))
    return modello, costruisci_grafo(modello, "Europe/Rome", checkpointer=InMemorySaver(), opzioni=opzioni)


def test_rifiuto_mostrato_all_utente():
    _, grafo = grafo_lezione6(
        OpzioniGrafo(ambito="data e ora"), AIMessage('{"categoria": "fuori_ambito", "motivo": "ricetta"}')
    )
    out = io.StringIO()

    conversa(grafo, config_sessione(), lettore("Dammi una ricetta"), out)

    assert risposta_rifiuto("data e ora") in out.getvalue()
    assert "categoria" not in out.getvalue()  # il JSON del router non va mostrato


def test_revisione_mostrata_e_contatore_azzerato_al_turno_successivo():
    no = AIMessage('{"coerente": false, "motivo": "manca il calcolo"}')
    si = AIMessage('{"coerente": true, "motivo": "ok"}')
    _, grafo = grafo_lezione6(
        OpzioniGrafo(limite_revisioni=1),
        AIMessage("Sono le 10."), no, AIMessage("Sono le 10 e fa 96."), no,   # primo turno: limite 1 raggiunto
        AIMessage("Ciao."), no, AIMessage("Ciao di nuovo."), si,              # secondo turno: si può rivedere ancora
    )
    config = config_sessione()
    out = io.StringIO()

    conversa(grafo, config, lettore("Che ore sono e quanto fa 12 * 8?", "ciao"), out)

    righe = out.getvalue().splitlines()
    assert "[revisore] non coerente: manca il calcolo" in righe
    assert righe.index("Sono le 10.") < righe.index("[revisore] non coerente: manca il calcolo") < righe.index("Sono le 10 e fa 96.")
    assert "Ciao di nuovo." in righe  # al secondo turno il contatore è ripartito da zero
    assert "coerente\"" not in out.getvalue()  # il JSON del revisore non va mostrato


def test_riassunto_mostrato_e_cronologia_coerente_dopo_un_turno_fallito():
    richiesta = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    _, grafo = grafo_lezione6(
        OpzioniGrafo(soglia_riassunto=4, messaggi_da_conservare=2),
        AIMessage("r1"), AIMessage("r2"),
        AIMessage("riassunto"), openai.APIConnectionError(request=richiesta),  # terzo turno: comprime, poi l'agente cade
        AIMessage("r4"),
    )
    config = config_sessione()
    out = io.StringIO()

    conversa(grafo, config, lettore("d1", "d2", "d3", "d4"), out, descrivi_errore=descrivi_errore)

    assert "[riassunto] cronologia compressa: 2 messaggi sostituiti" in out.getvalue().splitlines()
    stato = grafo.get_state(config).values
    assert [m.content for m in stato["messages"]] == ["d2", "r2", "d4", "r4"]  # del turno fallito non resta d3
    assert stato["riassunto"] == "riassunto"
