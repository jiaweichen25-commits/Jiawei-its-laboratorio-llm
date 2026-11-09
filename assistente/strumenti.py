"""Variante 1 — CHIAMATA LOCALE (slide 18): la funzione resta nel processo dell'agente.

@tool è la registrazione LangChain, NON un server MCP: aggiunge alla funzione Python il
«contratto» (nome, descrizione, schema degli argomenti) che il modello riceve con bind_tools.
Il contratto è definito qui, dalla firma e dalla descrizione della funzione (slide 21).
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from langchain_core.tools import BaseTool, tool
from pydantic import Field

from assistente.logica import ErroreStrumento, ora_nel_fuso, ora_utc

# Stessa descrizione in tutte le varianti: il confronto deve cambiare solo il percorso (slide 17).
DESCRIZIONE_OROLOGIO = (
    "Restituisce la data, l'ora e il giorno della settimana correnti nel fuso orario indicato. "
    "Usalo ogni volta che servono data, ora o giorno attuali."
)
DESCRIZIONE_FUSO = "Nome IANA del fuso orario, per esempio Europe/Rome, Asia/Tokyo o UTC."

__all__ = ["DESCRIZIONE_FUSO", "DESCRIZIONE_OROLOGIO", "crea_orologio", "ora_utc"]


def crea_orologio(adesso: Callable[[], datetime] = ora_utc) -> BaseTool:
    """Crea lo strumento orologio locale; `adesso` si sostituisce nei test con un istante fisso."""

    @tool("orologio", description=DESCRIZIONE_OROLOGIO)
    def orologio(fuso: Annotated[str, Field(description=DESCRIZIONE_FUSO)]) -> str:
        try:
            return ora_nel_fuso(fuso, adesso())  # chiamata diretta: nessun server, nessuna rete
        except ErroreStrumento as exc:
            # L'errore diventa testo per il modello: il grafo non si interrompe (slide 22).
            return f"Errore: {exc}"

    # metadata non arriva al modello: serve solo ai nostri log per sapere quale variante ha risposto.
    orologio.metadata = {"variante": "locale"}
    return orologio
