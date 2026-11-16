"""Variante 3, LATO SERVER — server MCP con FastMCP (slide 9, 10, 11, 20).

Ruolo MCP: questo è il SERVER. Espone tre tool (le «capacità»):
  - orologio  (slide 17: la stessa capacità delle altre due varianti)
  - calcola   (slide 25: calcolatrice sicura)
  - converti  (slide 25: convertitore di unità)
e, dalla lezione 6, una RESOURCE:
  - utente://preferenze  (step 4: il contenuto di preferenze.json, letto dall'host all'avvio)

Il CONTRATTO di ogni tool (nome, descrizione, schema JSON degli argomenti) viene generato da
FastMCP leggendo la firma e la docstring delle funzioni, e il client lo ottiene con tools/list
(discovery). Nell'agente quindi non si riscrive a mano nessuno schema (slide 20).

Trasporto stdio (slide 13): il client avvia questo file come sottoprocesso e i messaggi
JSON-RPC viaggiano su standard input/output. Per questo NON si deve mai usare print():
stdout è riservato al protocollo, i log vanno su stderr.

Avvio manuale (di solito lo avvia il client):  python -m assistente.server_mcp
"""

import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from assistente import logica
from assistente.logica import ErroreStrumento, Unita, ora_utc
from assistente.preferenze import URI_PREFERENZE


def percorso_preferenze_predefinito() -> Path:
    """File delle preferenze: PREFERENZE_FILE se impostata, altrimenti preferenze.json nel progetto.

    Il server è un sottoprocesso che eredita le variabili d'ambiente dell'agente: così una
    prova può puntare a un file temporaneo senza toccare quello del progetto.
    """
    personalizzato = os.environ.get("PREFERENZE_FILE", "").strip()
    return Path(personalizzato) if personalizzato else Path(__file__).resolve().parent.parent / "preferenze.json"


def crea_server(adesso: Callable[[], datetime] = ora_utc, percorso_preferenze: Path | None = None) -> FastMCP:
    """Costruisce il server. `adesso` e `percorso_preferenze` si sostituiscono nei test."""
    mcp = FastMCP("Strumenti ITS")
    file_preferenze = percorso_preferenze or percorso_preferenze_predefinito()

    # Lezione 6, step 4 — RESOURCE (slide 7): un contenuto identificato da un URI. A differenza di un
    # tool non la sceglie il modello: è l'host a leggerla (resources/read) prima della conversazione.
    # Il file si rilegge a ogni lettura: basta modificarlo e aprire una nuova sessione.
    @mcp.resource(URI_PREFERENZE, name="preferenze", mime_type="application/json")
    def preferenze() -> str:
        """Preferenze dell'utente per le risposte: lingua, fuso orario predefinito e stile."""
        # Se il file manca, l'eccezione diventa un errore MCP e l'host usa i valori predefiniti.
        return file_preferenze.read_text(encoding="utf-8")

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
