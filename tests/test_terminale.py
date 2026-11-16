"""Terminale: dallo step 6 della lezione 6 è un CLIENT del servizio dell'agente.

Il servizio qui è finto: un oggetto con le stesse operazioni di ClienteAgente. Le prove sul
grafo (rifiuto, revisore, riassunto, strumenti) sono in test_agente.py e test_servizio_agente.py.
"""

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp.types import Prompt, PromptArgument

from assistente.cliente_agente import ErroreServizio
from assistente.terminale import conversa, formatta_traccia


def lettore(*righe):
    righe = iter(righe)

    def leggi(prompt=""):
        try:
            return next(righe)
        except StopIteration:
            raise EOFError

    return leggi


def esito(risposta, cronologia, **altro):
    return {"risposta": risposta, "strumenti_usati": [], "cronologia": cronologia, "riassunto": "",
            "rifiutata": False, "revisioni": [], "messaggi_riassunti": 0, **altro}


class ServizioFinto:
    """Risponde con gli esiti prestabiliti e registra le richieste ricevute."""

    def __init__(self, *esiti):
        self.esiti = list(esiti)
        self.richieste = []

    def conversazione(self, cronologia, riassunto="", domanda=None, prompt=None):
        self.richieste.append({"cronologia": list(cronologia), "riassunto": riassunto, "domanda": domanda, "prompt": prompt})
        prossimo = self.esiti.pop(0)
        if isinstance(prossimo, BaseException):
            raise prossimo
        return prossimo

    def prompts(self):
        return [Prompt(name="spiega", description="Spiega un argomento.", arguments=[
            PromptArgument(name="argomento", description="concetto", required=True),
        ])]


def u(testo):
    return {"ruolo": "utente", "testo": testo}


def a(testo):
    return {"ruolo": "assistente", "testo": testo}


def test_risposta_ed_esci():
    servizio = ServizioFinto(esito("Ciao!", [u("ciao"), a("Ciao!")]))
    out = io.StringIO()

    conversa(servizio, lettore("ciao", "esci", "non letto"), out)

    assert "Ciao!" in out.getvalue()
    assert servizio.richieste == [{"cronologia": [], "riassunto": "", "domanda": "ciao", "prompt": None}]


def test_la_cronologia_restituita_dal_servizio_viene_rimandata():
    servizio = ServizioFinto(
        esito("Piacere.", [u("Mi chiamo Jiawei"), a("Piacere.")], riassunto="r1"),
        esito("Jiawei.", [u("Mi chiamo Jiawei"), a("Piacere."), u("Come mi chiamo?"), a("Jiawei.")]),
    )

    conversa(servizio, lettore("Mi chiamo Jiawei", "Come mi chiamo?"), io.StringIO())

    seconda = servizio.richieste[1]
    assert seconda["cronologia"] == [u("Mi chiamo Jiawei"), a("Piacere.")]
    assert seconda["riassunto"] == "r1"


def test_uscite_senza_chiamate():
    servizio = ServizioFinto()

    conversa(servizio, lettore("   ", "  ESCI ", "non letto"), io.StringIO())
    conversa(servizio, lettore(), io.StringIO())

    assert servizio.richieste == []


def test_tracce_di_strumenti_revisore_e_riassunto():
    servizio = ServizioFinto(esito(
        "Sono le 00:42.", [u("Che ore sono a Tokyo?"), a("Sono le 00:42.")],
        strumenti_usati=[{"nome": "orologio", "argomenti": {"fuso": "Asia/Tokyo"}, "risultato": "00:42"}],
        revisioni=["manca il giorno"], messaggi_riassunti=4,
    ))
    out = io.StringIO()

    conversa(servizio, lettore("Che ore sono a Tokyo?"), out)

    righe = out.getvalue().splitlines()
    assert "[riassunto] cronologia compressa: 4 messaggi sostituiti" in righe
    assert '[strumento] orologio(fuso="Asia/Tokyo") → 00:42' in righe
    assert "[revisore] non coerente: manca il giorno" in righe
    assert righe.index('[strumento] orologio(fuso="Asia/Tokyo") → 00:42') < righe.index("Sono le 00:42.")


def test_errore_del_servizio_e_ripresa_con_la_cronologia_di_prima():
    servizio = ServizioFinto(
        ErroreServizio("Errore 503 dal servizio agente: Connessione a LM Studio fallita"),
        esito("ok", [u("b"), a("ok")]),
    )
    out = io.StringIO()

    conversa(servizio, lettore("a", "b"), out)

    testo = out.getvalue()
    assert testo.index("Connessione a LM Studio fallita") < testo.index("ok")
    assert servizio.richieste[1]["cronologia"] == []  # il turno fallito non ha lasciato tracce


def test_ctrl_c_durante_la_risposta():
    servizio = ServizioFinto(KeyboardInterrupt())

    conversa(servizio, lettore("a", "b"), io.StringIO())

    assert len(servizio.richieste) == 1


# ---------------------------------------------------------------- comandi (step 5, ora via servizio)

def test_comando_prompts():
    servizio = ServizioFinto()
    out = io.StringIO()

    conversa(servizio, lettore("  /PROMPTS  "), out)

    assert "argomento (obbligatorio)" in out.getvalue() and servizio.richieste == []


def test_comando_prompt_valido():
    servizio = ServizioFinto(esito("Spiegazione.", [u("Spiegami «MCP»."), a("Spiegazione.")]))
    out = io.StringIO()

    conversa(servizio, lettore('/prompt spiega argomento="Model Context Protocol"'), out)

    assert servizio.richieste[0]["prompt"] == {"nome": "spiega", "argomenti": {"argomento": "Model Context Protocol"}}
    assert servizio.richieste[0]["domanda"] is None
    assert "Spiegazione." in out.getvalue()


@pytest.mark.parametrize("riga", [
    "/prompt spiega",                            # obbligatorio mancante
    "/prompt spiega argomento=MCP colore=blu",   # argomento sconosciuto
    "/prompt inventato",                         # prompt sconosciuto
    '/prompt spiega argomento="MCP',             # virgolette non chiuse
    "/boh",                                      # comando sconosciuto
])
def test_comando_non_valido_non_chiama_il_servizio(riga):
    servizio = ServizioFinto()
    out = io.StringIO()

    conversa(servizio, lettore(riga), out)

    assert out.getvalue().strip() and servizio.richieste == []


def test_servizio_spento_durante_prompts():
    class Spento(ServizioFinto):
        def prompts(self):
            raise ErroreServizio("Servizio agente non raggiungibile")

    out = io.StringIO()

    conversa(Spento(), lettore("/prompts"), out)

    assert "non raggiungibile" in out.getvalue()


# ---------------------------------------------------------------- formattazione e codifica

def test_formatta_traccia():
    assert formatta_traccia("orologio", {"fuso": "Asia/Tokyo"}, "X") == '[strumento] orologio(fuso="Asia/Tokyo") → X'


def test_output_cp1252():
    radice = Path(__file__).resolve().parent.parent
    comando = "from assistente.__main__ import configura_output; configura_output(); print('→ «x»')"

    esito_processo = subprocess.run(
        [sys.executable, "-c", comando],
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        cwd=radice,
        capture_output=True,
    )

    assert esito_processo.returncode == 0, esito_processo.stderr
