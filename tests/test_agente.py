"""Lezione 6, step 6: un turno dell'agente SENZA STATO, con il modello finto.

L'agente riceve cronologia e riassunto dal chiamante e li restituisce aggiornati: tra una
richiesta e l'altra non ricorda nulla (slide 13, punto 4).
"""

import json
from datetime import datetime, timezone

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from mcp.types import Prompt, PromptArgument

from assistente.agente import Agente, a_cronologia, da_cronologia
from assistente.client_mcp import ErroreCollegamentoMCP
from assistente.comandi import ErroreComando
from assistente.config import ErroreConfigurazione
from assistente.grafo import OpzioniGrafo, costruisci_grafo, risposta_rifiuto
from assistente.strumenti import crea_orologio
from tests.modello_finto import ModelloFinto

ISTANTE = datetime(2026, 10, 26, 15, 42, 10, tzinfo=timezone.utc)
ORA_TOKYO = "2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì"


def chiamata(fuso, id="c1"):
    return AIMessage("", tool_calls=[{"name": "orologio", "args": {"fuso": fuso}, "id": id}])


def json_ai(**dati):
    return AIMessage(json.dumps(dati))


class PromptFinti:
    def __init__(self, guasto=False):
        self.guasto = guasto
        self.richieste = []

    def elenco_prompt(self):
        return [Prompt(name="spiega", description="Spiega.", arguments=[
            PromptArgument(name="argomento", description="concetto", required=True),
        ])]

    def ottieni_prompt(self, nome, argomenti):
        self.richieste.append((nome, argomenti))
        if self.guasto:
            raise ErroreCollegamentoMCP("la sessione con il server non è attiva")
        return [HumanMessage(f"Spiegami «{argomenti['argomento']}».")]

    def attivo(self):
        return not self.guasto


def agente_con(*risposte, opzioni=OpzioniGrafo(), prompt_mcp=None, controlla_modello=None):
    modello = ModelloFinto(risposte=list(risposte))
    grafo = costruisci_grafo(modello, "Europe/Rome", strumenti=[crea_orologio(lambda: ISTANTE)], opzioni=opzioni)
    return modello, Agente(grafo, prompt_mcp=prompt_mcp, controlla_modello=controlla_modello)


# ---------------------------------------------------------------- conversione della cronologia

def test_da_cronologia():
    messaggi = da_cronologia([{"ruolo": "utente", "testo": "ciao"}, {"ruolo": "assistente", "testo": "salve"}])

    assert [(type(m), m.content) for m in messaggi] == [(HumanMessage, "ciao"), (AIMessage, "salve")]


def test_a_cronologia_tiene_solo_i_messaggi_da_chat():
    from langchain_core.messages import ToolMessage

    from assistente.controllo import indicazione_revisione

    messaggi = [
        HumanMessage("Che ore sono a Tokyo?"),
        chiamata("Asia/Tokyo"),
        ToolMessage(ORA_TOKYO, tool_call_id="c1", name="orologio"),
        AIMessage("bozza scartata"),
        indicazione_revisione("manca il giorno"),
        AIMessage("Sono le 00:42 di martedì."),
    ]

    assert a_cronologia(messaggi) == [
        {"ruolo": "utente", "testo": "Che ore sono a Tokyo?"},
        {"ruolo": "assistente", "testo": "Sono le 00:42 di martedì."},
    ]


# ---------------------------------------------------------------- un turno

def test_domanda_semplice():
    _, agente = agente_con(AIMessage("Ciao!"))

    esito = agente.rispondi([], domanda="ciao")

    assert esito.risposta == "Ciao!"
    assert esito.cronologia == [{"ruolo": "utente", "testo": "ciao"}, {"ruolo": "assistente", "testo": "Ciao!"}]
    assert esito.strumenti_usati == [] and not esito.rifiutata


def test_domanda_con_strumento():
    _, agente = agente_con(chiamata("Asia/Tokyo"), AIMessage("Sono le 00:42."))

    esito = agente.rispondi([], domanda="Che ore sono a Tokyo?")

    assert esito.strumenti_usati == [{"nome": "orologio", "argomenti": {"fuso": "Asia/Tokyo"}, "risultato": ORA_TOKYO}]
    assert esito.risposta == "Sono le 00:42."


def test_la_cronologia_ricevuta_arriva_al_modello_e_torna_aggiornata():
    modello, agente = agente_con(AIMessage("Ti chiami Jiawei."))
    cronologia = [{"ruolo": "utente", "testo": "Mi chiamo Jiawei"}, {"ruolo": "assistente", "testo": "Piacere."}]

    esito = agente.rispondi(cronologia, domanda="Come mi chiamo?")

    assert [m.content for m in modello.ricevuti[0][1:]] == ["Mi chiamo Jiawei", "Piacere.", "Come mi chiamo?"]
    assert esito.cronologia == cronologia + [
        {"ruolo": "utente", "testo": "Come mi chiamo?"}, {"ruolo": "assistente", "testo": "Ti chiami Jiawei."},
    ]


def test_senza_stato_tra_due_richieste():
    modello, agente = agente_con(AIMessage("uno"), AIMessage("due"))

    agente.rispondi([], domanda="prima")
    agente.rispondi([], domanda="seconda")

    assert [m.content for m in modello.ricevuti[1][1:]] == ["seconda"]  # «prima» non è stata ricordata


def test_domanda_fuori_ambito():
    _, agente = agente_con(json_ai(categoria="fuori_ambito", motivo="ricetta"), opzioni=OpzioniGrafo(ambito="ora"))

    esito = agente.rispondi([], domanda="Una ricetta?")

    assert esito.rifiutata and esito.risposta == risposta_rifiuto("ora")


def test_revisioni_riportate():
    _, agente = agente_con(
        AIMessage("bozza"), json_ai(coerente=False, motivo="manca il calcolo"),
        AIMessage("completa"), json_ai(coerente=True, motivo="ok"),
        opzioni=OpzioniGrafo(limite_revisioni=2),
    )

    esito = agente.rispondi([], domanda="Ora e 12*8?")

    assert esito.revisioni == ["manca il calcolo"]
    assert esito.risposta == "completa"
    assert esito.cronologia[-1] == {"ruolo": "assistente", "testo": "completa"}


def test_riassunto_ricevuto_e_restituito():
    modello, agente = agente_con(
        AIMessage("riassunto nuovo"), AIMessage("ok"),
        opzioni=OpzioniGrafo(soglia_riassunto=4, messaggi_da_conservare=2),
    )
    cronologia = [{"ruolo": r, "testo": t} for r, t in
                  [("utente", "d1"), ("assistente", "r1"), ("utente", "d2"), ("assistente", "r2")]]

    esito = agente.rispondi(cronologia, riassunto="riassunto vecchio", domanda="d3")

    assert "riassunto vecchio" in modello.ricevuti[0][1].content
    assert esito.riassunto == "riassunto nuovo"
    assert esito.messaggi_riassunti == 2
    assert [m["testo"] for m in esito.cronologia] == ["d2", "r2", "d3", "ok"]  # più corta di quella inviata


# ---------------------------------------------------------------- prompt MCP

def test_prompt_valido():
    finti = PromptFinti()
    _, agente = agente_con(AIMessage("MCP è un protocollo."), prompt_mcp=finti)

    esito = agente.rispondi([], prompt=("spiega", {"argomento": "MCP"}))

    assert finti.richieste == [("spiega", {"argomento": "MCP"})]
    assert esito.cronologia[0] == {"ruolo": "utente", "testo": "Spiegami «MCP»."}


@pytest.mark.parametrize("prompt", [("spiega", {}), ("spiega", {"argomento": "x", "colore": "blu"}), ("boh", {})])
def test_prompt_non_valido_non_chiama_ne_server_ne_modello(prompt):
    finti = PromptFinti()
    modello, agente = agente_con(prompt_mcp=finti)

    with pytest.raises(ErroreComando):
        agente.rispondi([], prompt=prompt)
    assert finti.richieste == [] and modello.ricevuti == []


def test_prompt_senza_server_mcp():
    _, agente = agente_con()

    with pytest.raises(ErroreComando, match="non disponibili"):
        agente.rispondi([], prompt=("spiega", {"argomento": "x"}))


# ---------------------------------------------------------------- errori

def test_errori_del_modello_risalgono():
    richiesta = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    _, agente = agente_con(openai.APIConnectionError(request=richiesta))

    with pytest.raises(openai.APIConnectionError):
        agente.rispondi([], domanda="ciao")


def test_troppi_passaggi():
    _, agente = agente_con(*[chiamata("UTC", id=f"c{i}") for i in range(20)])

    with pytest.raises(GraphRecursionError):
        agente.rispondi([], domanda="ciclo")


# ---------------------------------------------------------------- streaming (slide 18)

def eventi_di(agente, domanda, cronologia=()):
    return list(agente.eventi(list(cronologia), "", agente.prepara(domanda, None)))


def test_eventi_testo_a_frammenti_poi_fine():
    _, agente = agente_con(AIMessage("Sono le dieci"))

    eventi = eventi_di(agente, "che ore sono?")

    assert [dati["testo"] for tipo, dati in eventi if tipo == "testo"] == ["Sono ", "le ", "dieci"]
    tipo, esito = eventi[-1]
    assert tipo == "fine" and esito["risposta"] == "Sono le dieci"
    assert esito["cronologia"][-1] == {"ruolo": "assistente", "testo": "Sono le dieci"}


def test_eventi_con_strumento_tra_due_bozze():
    prima = AIMessage("Controllo.", tool_calls=[{"name": "orologio", "args": {"fuso": "Asia/Tokyo"}, "id": "c1"}])
    _, agente = agente_con(prima, AIMessage("Sono le 00:42."))

    eventi = eventi_di(agente, "Che ore sono a Tokyo?")

    assert [tipo for tipo, _ in eventi] == ["testo", "strumento", "testo", "testo", "testo", "fine"]
    assert eventi[1][1] == {"nome": "orologio", "argomenti": {"fuso": "Asia/Tokyo"}, "risultato": ORA_TOKYO}
    assert eventi[-1][1]["risposta"] == "Sono le 00:42."


def test_eventi_revisione_tra_bozza_e_risposta_nuova():
    _, agente = agente_con(
        AIMessage("bozza"), json_ai(coerente=False, motivo="manca il calcolo"),
        AIMessage("completa"), json_ai(coerente=True, motivo="ok"),
        opzioni=OpzioniGrafo(limite_revisioni=2),
    )

    eventi = eventi_di(agente, "Ora e 12*8?")

    assert [(t, d.get("testo") or d.get("motivo")) for t, d in eventi[:-1]] == [
        ("testo", "bozza"), ("revisione", "manca il calcolo"), ("testo", "completa"),
    ]  # il JSON del revisore non compare tra i frammenti di testo


def test_eventi_rifiuto_arriva_come_testo():
    _, agente = agente_con(json_ai(categoria="fuori_ambito", motivo="ricetta"), opzioni=OpzioniGrafo(ambito="ora"))

    eventi = eventi_di(agente, "Una ricetta?")

    assert eventi[0] == ("testo", {"testo": risposta_rifiuto("ora")})
    assert eventi[-1][1]["rifiutata"] is True


def test_eventi_riassunto():
    _, agente = agente_con(
        AIMessage("riassunto nuovo"), AIMessage("ok"),
        opzioni=OpzioniGrafo(soglia_riassunto=4, messaggi_da_conservare=2),
    )
    cronologia = [{"ruolo": r, "testo": t} for r, t in
                  [("utente", "d1"), ("assistente", "r1"), ("utente", "d2"), ("assistente", "r2")]]

    eventi = eventi_di(agente, "d3", cronologia)

    assert eventi[0] == ("riassunto", {"messaggi_riassunti": 2})
    assert [d["testo"] for t, d in eventi if t == "testo"] == ["ok"]  # il testo del riassunto non è una risposta


# ---------------------------------------------------------------- stato

def test_stato_tutto_ok():
    _, agente = agente_con(prompt_mcp=PromptFinti(), controlla_modello=lambda: None)

    assert agente.stato() == {"agente": "ok", "server_mcp": "ok", "modello": "ok"}


def test_stato_con_modello_e_server_spenti():
    def spento():
        raise ErroreConfigurazione("LM Studio non raggiungibile su http://localhost:1234/v1")

    _, agente = agente_con(prompt_mcp=PromptFinti(guasto=True), controlla_modello=spento)

    stato = agente.stato()
    assert stato["agente"] == "ok"
    assert stato["server_mcp"] != "ok" and "LM Studio non raggiungibile" in stato["modello"]
