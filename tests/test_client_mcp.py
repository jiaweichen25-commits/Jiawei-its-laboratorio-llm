"""Test del client MCP e dell'adattatore catalogo → tool LangChain (variante 3, lato agente).

Due livelli:
  - server in memoria (veloce): discovery, conversione, invocazione, errori, grafo;
  - server vero come sottoprocesso stdio (come nell'applicazione), ancora senza modello.
"""

from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from assistente.client_mcp import ClienteMCP, ErroreCollegamentoMCP, crea_strumenti_mcp, trasporto_stdio
from assistente.grafo import LIMITE_PASSAGGI, costruisci_grafo
from assistente.server_mcp import crea_server
from tests.modello_finto import ModelloFinto

ISTANTE = datetime(2026, 10, 26, 15, 42, 10, tzinfo=timezone.utc)
ORA_TOKYO = "2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì"


@pytest.fixture
def cliente():
    with ClienteMCP(crea_server(lambda: ISTANTE)) as c:  # avvia() all'ingresso, chiudi() all'uscita
        yield c


def test_catalogo_dal_server(cliente):
    assert {voce.name for voce in cliente.catalogo()} == {"orologio", "calcola", "converti"}


def test_adattatore_usa_nome_descrizione_e_schema_del_server(cliente):
    strumenti = {s.name: s for s in crea_strumenti_mcp(cliente)}
    voce = next(v for v in cliente.catalogo() if v.name == "converti")

    # Lo schema NON è scritto nell'agente: è quello ricevuto con tools/list (slide 20).
    assert strumenti["converti"].description == voce.description
    assert strumenti["converti"].args_schema == voce.input_schema
    assert strumenti["converti"].metadata == {"variante": "mcp"}


def test_invocazione_sincrona(cliente):
    orologio = next(s for s in crea_strumenti_mcp(cliente) if s.name == "orologio")

    assert orologio.invoke({"fuso": "Asia/Tokyo"}) == ORA_TOKYO


def test_errore_dello_strumento_diventa_testo(cliente):
    orologio = next(s for s in crea_strumenti_mcp(cliente) if s.name == "orologio")

    assert orologio.invoke({"fuso": "Mars/Olympus"}) == "Errore: fuso orario sconosciuto: «Mars/Olympus»"


def test_dopo_la_chiusura_errore_di_collegamento():
    c = ClienteMCP(crea_server(lambda: ISTANTE))
    c.avvia()
    calcola = next(s for s in crea_strumenti_mcp(c) if s.name == "calcola")
    c.chiudi()

    # Slide 23: errore di collegamento distinto dall'errore dello strumento.
    assert calcola.invoke({"espressione": "1+1"}).startswith("Errore di collegamento MCP")


def test_chiudi_due_volte_non_fallisce():
    c = ClienteMCP(crea_server(lambda: ISTANTE))
    c.avvia()
    c.chiudi()
    c.chiudi()


def test_nel_grafo_tool_message_correlato(cliente):
    # Slide 12: il risultato MCP rientra come ToolMessage con lo stesso tool_call_id della richiesta.
    richiesta = AIMessage("", tool_calls=[{"name": "orologio", "args": {"fuso": "Asia/Tokyo"}, "id": "call_01"}])
    modello = ModelloFinto(risposte=[richiesta, AIMessage("A Tokyo è martedì, 00:42.")])
    grafo = costruisci_grafo(modello, "Europe/Rome", strumenti=crea_strumenti_mcp(cliente))

    stato = grafo.invoke({"messages": [HumanMessage("Che ore sono a Tokyo?")]}, {"recursion_limit": LIMITE_PASSAGGI})

    risultato = stato["messages"][2]
    assert isinstance(risultato, ToolMessage)
    assert risultato.tool_call_id == "call_01"
    assert risultato.content == ORA_TOKYO
    assert modello.ricevuti[1][-1].content == ORA_TOKYO  # il modello riceve il risultato


# ---------------------------------------------------------------- server vero via stdio

def test_stdio_discovery_e_chiamata():
    with ClienteMCP(trasporto_stdio()) as c:
        assert {voce.name for voce in c.catalogo()} == {"orologio", "calcola", "converti"}
        assert c.chiama("calcola", {"espressione": "(2+3)*4"}) == "(2+3)*4 = 20"


def test_stdio_server_inesistente():
    # Slide 24, «processo non avviato»: errore chiaro all'avvio, non a metà conversazione.
    c = ClienteMCP(trasporto_stdio(modulo="assistente.non_esiste"), timeout=10)

    with pytest.raises(ErroreCollegamentoMCP):
        c.avvia()


def test_trasporto_termina_il_server_con_la_sessione():
    # keep_alive=False: alla chiusura della sessione il sottoprocesso del server viene terminato,
    # invece di restare vivo finché il garbage collector non lo raccoglie.
    assert trasporto_stdio().keep_alive is False


@pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning")
def test_stdio_chiusura_pulita():
    with ClienteMCP(trasporto_stdio()) as c:
        assert c.chiama("converti", {"valore": 1, "da": "m", "a": "cm"}) == "1 m = 100 cm"
