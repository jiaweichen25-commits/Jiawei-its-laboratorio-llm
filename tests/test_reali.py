"""Prove con il modello vero in LM Studio: pytest -m lmstudio"""

import os
import re
from pathlib import Path

import pytest
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from assistente.config import carica_configurazione, verifica_modello
from assistente.grafo import LIMITE_PASSAGGI, costruisci_grafo
from assistente.modello import crea_modello
from assistente.strumenti import crea_orologio

pytestmark = pytest.mark.lmstudio


@pytest.fixture(scope="module")
def grafo():
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    cfg = carica_configurazione(os.environ)
    verifica_modello(cfg)
    return costruisci_grafo(crea_modello(cfg), cfg.fuso_predefinito, strumenti=[crea_orologio()])


def chiedi(grafo, domanda):
    stato = grafo.invoke({"messages": [HumanMessage(domanda)]}, {"recursion_limit": LIMITE_PASSAGGI})
    return stato["messages"]


def test_orologio_reale(grafo):
    messaggi = chiedi(grafo, "Che ore sono a Tokyo?")

    chiamate = [c for m in messaggi if isinstance(m, AIMessage) for c in m.tool_calls]
    assert any(c["name"] == "orologio" and c["args"].get("fuso") == "Asia/Tokyo" for c in chiamate), chiamate
    risultati = [m.content for m in messaggi if isinstance(m, ToolMessage)]
    assert any(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+09:00 \(Asia/Tokyo\)", r) for r in risultati), risultati
    finale = messaggi[-1]
    assert isinstance(finale, AIMessage) and not finale.tool_calls and finale.content.strip()


def test_conversazione_ordinaria(grafo):
    messaggi = chiedi(grafo, "Ciao, come stai?")

    assert not any(isinstance(m, ToolMessage) for m in messaggi)
