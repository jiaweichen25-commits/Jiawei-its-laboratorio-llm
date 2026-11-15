"""Prove con il modello vero in LM Studio: pytest -m lmstudio

Una risposta simulata non dimostra che il modello locale sappia scegliere lo strumento:
qui si controlla che il modello chiami DAVVERO il tool MCP e usi il risultato (slide 31).
"""

import os
import re
from pathlib import Path

import pytest
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from assistente.client_mcp import ClienteMCP, crea_strumenti_mcp, trasporto_stdio
from assistente.config import carica_configurazione, verifica_modello
from assistente.grafo import LIMITE_PASSAGGI, OpzioniGrafo, costruisci_grafo, risposta_rifiuto
from assistente.modello import crea_modello
from assistente.varianti import strumenti_per_variante

pytestmark = pytest.mark.lmstudio

ORA_TOKYO = re.compile(
    r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+09:00 \(Asia/Tokyo\), (lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica)"
)


@pytest.fixture(scope="module")
def cfg():
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    configurazione = carica_configurazione(os.environ)
    verifica_modello(configurazione)
    return configurazione


@pytest.fixture(scope="module")
def strumenti_mcp():
    # Server MCP vero, avviato come sottoprocesso stdio come nell'applicazione.
    with ClienteMCP(trasporto_stdio()) as cliente:
        yield crea_strumenti_mcp(cliente)


def grafo_per(cfg, strumenti_mcp, variante):
    strumenti = strumenti_per_variante(variante, strumenti_mcp, cfg.orologio_api_url)
    return costruisci_grafo(crea_modello(cfg), cfg.fuso_predefinito, strumenti=strumenti)


def chiedi(grafo, domanda):
    stato = grafo.invoke({"messages": [HumanMessage(domanda)]}, {"recursion_limit": LIMITE_PASSAGGI})
    return stato["messages"]


def chiamate(messaggi):
    return [c for m in messaggi if isinstance(m, AIMessage) for c in m.tool_calls]


def risultati(messaggi):
    return [m.content for m in messaggi if isinstance(m, ToolMessage)]


def risposta_finale(messaggi):
    finale = messaggi[-1]
    assert isinstance(finale, AIMessage) and not finale.tool_calls and finale.content.strip()
    return finale.content


@pytest.mark.parametrize("variante", ["mcp", "locale"])
def test_orologio_reale(cfg, strumenti_mcp, variante):
    messaggi = chiedi(grafo_per(cfg, strumenti_mcp, variante), "Che ore sono a Tokyo?")

    assert any(c["name"] == "orologio" and c["args"].get("fuso") == "Asia/Tokyo" for c in chiamate(messaggi)), chiamate(messaggi)
    assert any(ORA_TOKYO.fullmatch(r) for r in risultati(messaggi)), risultati(messaggi)
    risposta_finale(messaggi)


def test_calcola_reale(cfg, strumenti_mcp):
    messaggi = chiedi(grafo_per(cfg, strumenti_mcp, "mcp"), "Quanto fa (17 + 25) * 3? Usa la calcolatrice.")

    assert any(c["name"] == "calcola" for c in chiamate(messaggi)), chiamate(messaggi)
    assert any(r.endswith("= 126") for r in risultati(messaggi)), risultati(messaggi)
    assert "126" in risposta_finale(messaggi)


def test_converti_reale(cfg, strumenti_mcp):
    messaggi = chiedi(grafo_per(cfg, strumenti_mcp, "mcp"), "Converti 10 chilometri in miglia.")

    assert any(
        c["name"] == "converti" and c["args"].get("da") == "km" and c["args"].get("a") == "mi"
        for c in chiamate(messaggi)
    ), chiamate(messaggi)
    assert "10 km = 6.21371 mi" in risultati(messaggi), risultati(messaggi)
    assert "6.21" in risposta_finale(messaggi) or "6,21" in risposta_finale(messaggi)


def test_conversazione_ordinaria(cfg, strumenti_mcp):
    messaggi = chiedi(grafo_per(cfg, strumenti_mcp, "mcp"), "Ciao, come stai?")

    assert not any(isinstance(m, ToolMessage) for m in messaggi)


# ---------------------------------------------------------------- lezione 6

def grafo_lezione6(cfg, strumenti_mcp, checkpointer=None, **opzioni):
    """Grafo con i nodi della lezione 6 accesi come indicato (gli altri restano spenti)."""
    strumenti = strumenti_per_variante("mcp", strumenti_mcp, cfg.orologio_api_url)
    return costruisci_grafo(
        crea_modello(cfg), cfg.fuso_predefinito, strumenti=strumenti,
        checkpointer=checkpointer, opzioni=OpzioniGrafo(**opzioni),
    )


def test_router_reale_in_ambito(cfg, strumenti_mcp):
    messaggi = chiedi(grafo_lezione6(cfg, strumenti_mcp, ambito=cfg.ambito), "Che ore sono a Tokyo?")

    assert any(c["name"] == "orologio" for c in chiamate(messaggi)), messaggi
    risposta_finale(messaggi)


def test_router_reale_fuori_ambito(cfg, strumenti_mcp):
    messaggi = chiedi(grafo_lezione6(cfg, strumenti_mcp, ambito=cfg.ambito), "Dammi la ricetta della carbonara")

    assert messaggi[-1].content == risposta_rifiuto(cfg.ambito), messaggi
    assert not chiamate(messaggi)


def test_router_reale_seguito_resta_in_ambito(cfg, strumenti_mcp):
    # «e a New York?» da sola non dice nulla: il router deve leggerla insieme allo scambio precedente.
    from langgraph.checkpoint.memory import InMemorySaver

    grafo = grafo_lezione6(cfg, strumenti_mcp, checkpointer=InMemorySaver(), ambito=cfg.ambito)
    config = {"configurable": {"thread_id": "seguito"}, "recursion_limit": LIMITE_PASSAGGI}
    grafo.invoke({"messages": [HumanMessage("Che ore sono a Tokyo?")]}, config)
    messaggi = grafo.invoke({"messages": [HumanMessage("e a New York?")]}, config)["messages"]

    assert messaggi[-1].content != risposta_rifiuto(cfg.ambito), messaggi[-1].content


def test_revisore_reale_domanda_in_due_parti(cfg, strumenti_mcp):
    # Slide 5: la risposta deve coprire entrambe le parti; se la prima bozza ne salta una, il revisore la rimanda.
    messaggi = chiedi(
        grafo_lezione6(cfg, strumenti_mcp, limite_revisioni=2),
        "Che ore sono a Tokyo e quanto fa 12 * 8?",
    )

    assert any(c["name"] == "orologio" for c in chiamate(messaggi)), messaggi
    assert "96" in risposta_finale(messaggi)
