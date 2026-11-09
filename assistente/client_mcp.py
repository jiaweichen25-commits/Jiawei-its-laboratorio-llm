"""Variante 3, LATO AGENTE — client MCP e adattatore (slide 9, 11, 12, 20, 21, 22).

Ruoli MCP (slide 9):
  - HOST   = la nostra applicazione LangGraph (cronologia, modello, permessi);
  - CLIENT = la classe ClienteMCP qui sotto: parla col server e gestisce il collegamento;
  - SERVER = server_mcp.py, avviato come sottoprocesso con trasporto stdio.

Cosa fa questo modulo, in ordine (la «sequenza concettuale» della slide 20):
  1. catalogo = client.list_tools()              → ClienteMCP.avvia() + catalogo()
  2. strumenti = adatta_schemi_e_invocazioni()   → crea_strumenti_mcp()
  3. modello_con_tool = bind_tools(strumenti)    → lo fa già grafo.py, come per le altre varianti

IL PROBLEMA SINCRONO/ASINCRONO (slide 22: «gestire esplicitamente asincronia e durata della
connessione»): il client FastMCP è asincrono (async/await), mentre il nostro grafo è sincrono.
Soluzione:
  - un thread di servizio esegue un event loop asyncio tutto suo;
  - in quel loop una coroutine tiene APERTA una sola sessione MCP per tutta la durata del
    programma (non si riavvia il server a ogni domanda);
  - quando il nodo strumenti chiama un tool, la richiesta viene «spedita» al loop con
    asyncio.run_coroutine_threadsafe e il thread principale aspetta la risposta (con timeout).
"""

import asyncio
import logging
import sys
import threading
from functools import partial
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from langchain_core.tools import BaseTool, StructuredTool

log = logging.getLogger("assistente.mcp")

RADICE_PROGETTO = Path(__file__).resolve().parent.parent


class ErroreCollegamentoMCP(Exception):
    """Il server MCP non si avvia o non risponde: l'applicazione non può partire."""


def trasporto_stdio(modulo: str = "assistente.server_mcp") -> StdioTransport:
    """Trasporto stdio: il client avvia il server come sottoprocesso «python -m <modulo>».

    sys.executable = lo stesso interprete Python dell'agente (quello del .venv o del container),
    così il server trova le stesse dipendenze (slide 24: «interprete, dipendenze, percorsi»).
    """
    # keep_alive=False: quando la sessione si chiude, anche il sottoprocesso del server termina
    # (il valore predefinito di FastMCP lo lascerebbe vivo tra una connessione e l'altra).
    return StdioTransport(
        command=sys.executable, args=["-m", modulo], cwd=str(RADICE_PROGETTO), keep_alive=False
    )


class ClienteMCP:
    """Sessione MCP persistente utilizzabile da codice sincrono.

    `sorgente` è ciò a cui collegarsi: un trasporto (stdio nell'applicazione) oppure, nei test,
    direttamente un oggetto FastMCP (collegamento in memoria).
    Si usa così:   with ClienteMCP(trasporto_stdio()) as cliente: ...
    """

    def __init__(self, sorgente: Any, timeout: float = 15.0):
        self._sorgente = sorgente
        self._timeout = timeout                 # secondi massimi per avvio e per ogni chiamata
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._sessione_futura = None            # la coroutine che tiene aperta la sessione
        self._client: Client | None = None      # valorizzato solo mentre la sessione è aperta
        self._stop: asyncio.Event | None = None # segnale «chiudi la sessione»
        self._pronto = threading.Event()        # avvia() aspetta questo segnale
        self._catalogo: list = []

    # ------------------------------------------------------------------ ciclo di vita

    def avvia(self) -> None:
        """Avvia il thread col suo event loop, apre la sessione e scarica il catalogo (tools/list)."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="client-mcp", daemon=True)
        self._thread.start()
        self._sessione_futura = asyncio.run_coroutine_threadsafe(self._sessione(), self._loop)

        if not self._pronto.wait(self._timeout):
            self.chiudi()
            raise ErroreCollegamentoMCP(f"il server MCP non ha risposto entro {self._timeout:.0f} s")
        if self._client is None:  # la sessione è terminata subito: il server non è partito
            errore = self._sessione_futura.exception()
            self.chiudi()
            raise ErroreCollegamentoMCP(f"impossibile avviare il server MCP: {errore}") from errore
        log.info("mcp: catalogo ricevuto %s", [voce.name for voce in self._catalogo])

    async def _sessione(self) -> None:
        """Gira nel thread di servizio: apre la sessione, la tiene viva finché non arriva lo stop."""
        try:
            # «async with» apre la connessione (avvia il sottoprocesso e fa l'handshake MCP)
            # e la chiude da sola all'uscita del blocco.
            async with Client(self._sorgente, timeout=self._timeout) as client:
                self._catalogo = await client.list_tools()  # DISCOVERY: tools/list
                self._stop = asyncio.Event()
                self._client = client
                self._pronto.set()       # sblocca avvia()
                await self._stop.wait()  # resta qui, con la sessione aperta, fino a chiudi()
        finally:
            self._client = None
            self._pronto.set()  # sblocca avvia() anche se l'apertura è fallita

    def chiudi(self) -> None:
        """Chiude la sessione (termina il sottoprocesso) e ferma il thread. Si può chiamare due volte."""
        if self._loop is None:
            return
        if self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)  # fa uscire _sessione dall'attesa
        try:
            self._sessione_futura.result(self._timeout)
        except Exception:
            pass  # in chiusura un errore della sessione non interessa più
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(self._timeout)
        self._loop.close()
        self._loop = None

    def __enter__(self) -> "ClienteMCP":
        self.avvia()
        return self

    def __exit__(self, *eccezione) -> None:
        self.chiudi()

    # ------------------------------------------------------------------ catalogo e chiamate

    def catalogo(self) -> list:
        """Le voci ottenute con tools/list: ognuna ha name, description e input_schema."""
        return list(self._catalogo)

    def chiama(self, nome: str, argomenti: dict) -> str:
        """Esegue tools/call in modo sincrono e restituisce il risultato come testo per il modello."""
        client = self._client
        if client is None or self._loop is None:
            return "Errore di collegamento MCP: la sessione con il server non è attiva"

        # Si spedisce la coroutine al loop del thread di servizio e si aspetta il risultato.
        # raise_on_error=False: un errore del tool torna come risultato con is_error=True.
        futura = asyncio.run_coroutine_threadsafe(
            client.call_tool(nome, argomenti, raise_on_error=False), self._loop
        )
        try:
            risultato = futura.result(self._timeout)
        except Exception as exc:  # timeout, server caduto, connessione chiusa...
            futura.cancel()
            return f"Errore di collegamento MCP: {type(exc).__name__}: {exc}"

        # Il risultato MCP è una lista di «contenuti»; qui ci interessano quelli testuali.
        testo = "\n".join(c.text for c in risultato.content if getattr(c, "text", None) is not None)
        if risultato.is_error:
            return f"Errore: {testo}"  # errore DELLO STRUMENTO (es. fuso non valido)
        return testo


# ---------------------------------------------------------------------- adattatore

def _invoca(cliente: ClienteMCP, nome: str, **argomenti: Any) -> str:
    """Funzione eseguita quando il grafo invoca il tool: inoltra la chiamata al server MCP."""
    return cliente.chiama(nome, argomenti)


def crea_strumenti_mcp(cliente: ClienteMCP) -> list[BaseTool]:
    """ADATTATORE: converte ogni voce del catalogo MCP in un tool LangChain (slide 21).

    Nome, descrizione e schema vengono COPIATI dal catalogo del server: se domani il server
    cambia un tool, l'agente lo vede al prossimo avvio senza modificare questo codice.
    Poi il tool entra in bind_tools e nel nodo strumenti come quelli delle altre varianti.
    """
    return [
        StructuredTool(
            name=voce.name,
            description=voce.description or "",
            args_schema=voce.input_schema,          # lo schema JSON così come arriva dal server
            func=partial(_invoca, cliente, voce.name),
            metadata={"variante": "mcp"},           # solo per i log
        )
        for voce in cliente.catalogo()
    ]
