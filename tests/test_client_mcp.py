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


def test_log_del_server_in_un_file():
    # I log del server (stderr del sottoprocesso) vanno in server_mcp.log, non nel terminale della chat.
    from assistente.client_mcp import FILE_LOG_SERVER

    assert trasporto_stdio().log_file == FILE_LOG_SERVER
    assert FILE_LOG_SERVER.name == "server_mcp.log"


def processo_vivo(pid: int) -> bool:
    """True se il processo con quel PID è ancora in esecuzione (Windows: tasklist)."""
    import os
    import subprocess

    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    elenco = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in elenco


def test_server_che_non_risponde_viene_terminato(tmp_path):
    # Un processo che parte ma non parla MCP: avvia() si arrende dopo il timeout e annulla
    # l'apertura, così il sottoprocesso viene terminato invece di restare acceso.
    import sys
    import time

    from fastmcp.client.transports import StdioTransport

    file_pid = tmp_path / "pid.txt"
    codice = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(60)"
    muto = StdioTransport(command=sys.executable, args=["-c", codice, str(file_pid)], keep_alive=False)

    with pytest.raises(ErroreCollegamentoMCP, match="non ha risposto"):
        ClienteMCP(muto, timeout=2).avvia()

    pid = int(file_pid.read_text())
    for _ in range(20):  # il sistema operativo può impiegare un attimo a togliere il processo
        if not processo_vivo(pid):
            break
        time.sleep(0.25)
    assert not processo_vivo(pid)
