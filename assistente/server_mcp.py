"""Variante 3, LATO SERVER — server MCP con FastMCP (slide 9, 10, 11, 20).

Ruolo MCP: questo è il SERVER. Espone tre tool (le «capacità»):
  - orologio  (slide 17: la stessa capacità delle altre due varianti)
  - calcola   (slide 25: calcolatrice sicura)
  - converti  (slide 25: convertitore di unità)

Il CONTRATTO di ogni tool (nome, descrizione, schema JSON degli argomenti) viene generato da
FastMCP leggendo la firma e la docstring delle funzioni, e il client lo ottiene con tools/list
(discovery). Nell'agente quindi non si riscrive a mano nessuno schema (slide 20).

Trasporto stdio (slide 13): il client avvia questo file come sottoprocesso e i messaggi
JSON-RPC viaggiano su standard input/output. Per questo NON si deve mai usare print():
stdout è riservato al protocollo, i log vanno su stderr.

Avvio manuale (di solito lo avvia il client):  python -m assistente.server_mcp
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from assistente import logica
from assistente.logica import ErroreStrumento, Unita, ora_utc


def crea_server(adesso: Callable[[], datetime] = ora_utc) -> FastMCP:
    """Costruisce il server con i tre tool. `adesso` si sostituisce nei test con un istante fisso."""
    mcp = FastMCP("Strumenti ITS")

    # @mcp.tool registra la funzione nel catalogo MCP. La docstring diventa la «description» che il
    # modello legge per decidere se usare il tool; i tipi diventano lo «inputSchema».

    @mcp.tool
    def orologio(
        fuso: Annotated[str, Field(description="Nome IANA del fuso orario, per esempio Europe/Rome, Asia/Tokyo o UTC.")],
    ) -> str:
        """Restituisce la data, l'ora e il giorno della settimana correnti nel fuso orario indicato. Usalo ogni volta che servono data, ora o giorno attuali."""
        try:
            return logica.ora_nel_fuso(fuso, adesso())
        except ErroreStrumento as exc:
            # ToolError → il risultato MCP ha is_error=True e contiene il nostro messaggio:
            # il client sa che è un errore dello strumento, non un successo (slide 12 e 23).
            raise ToolError(str(exc)) from None

    @mcp.tool
    def calcola(
        espressione: Annotated[str, Field(description="Espressione aritmetica, es. (2+3)*4 oppure 2**10 / 4.")],
    ) -> str:
        """Calcola un'espressione aritmetica con numeri, + - * / // % ** e parentesi. Usalo per ogni calcolo numerico invece di farlo a mente. Non esegue codice: nomi, funzioni e testo vengono rifiutati."""
        try:
            return logica.calcola(espressione)
        except ErroreStrumento as exc:
            raise ToolError(str(exc)) from None

    @mcp.tool
    def converti(
        valore: Annotated[float, Field(description="Numero da convertire, es. 10.")],
        # Unita è un Literal: nello schema diventa un «enum», cioè un elenco chiuso di valori ammessi.
        da: Annotated[Unita, Field(description="Unità di partenza.")],
        a: Annotated[Unita, Field(description="Unità di arrivo, della stessa grandezza di quella di partenza.")],
    ) -> str:
        """Converte un valore tra unità di lunghezza (mm, cm, m, km, in, ft, mi), massa (g, kg, lb, oz) o temperatura (C, F, K). Le due unità devono misurare la stessa grandezza."""
        try:
            return logica.converti(valore, da, a)
        except ErroreStrumento as exc:
            raise ToolError(str(exc)) from None

    return mcp


if __name__ == "__main__":
    # Senza argomenti FastMCP usa il trasporto stdio. show_banner=False: niente logo all'avvio.
    crea_server().run(show_banner=False)
