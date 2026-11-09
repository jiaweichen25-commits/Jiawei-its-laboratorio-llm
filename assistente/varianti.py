"""Scelta della variante dell'orologio (slide 17: «una sola variante viene esposta al modello per volta»).

Il server MCP fornisce sempre calcola e converti (le proposte della slide 25). Per l'orologio,
invece, l'HOST decide quale percorso usare (slide 11: «l'host seleziona le capacità consentite»):

    VARIANTE_OROLOGIO=mcp      → orologio dal catalogo MCP (insieme agli altri due tool)
    VARIANTE_OROLOGIO=locale   → orologio MCP scartato, al suo posto la funzione locale
    VARIANTE_OROLOGIO=fastapi  → orologio MCP scartato, al suo posto il wrapper HTTP

Il nome del tool resta sempre «orologio», così domanda, modello e contratto sono identici e
cambia solo il percorso (è il confronto chiesto dalla slide 17).
"""

from collections.abc import Sequence

from langchain_core.tools import BaseTool

from assistente.strumenti import crea_orologio
from assistente.wrapper_http import crea_orologio_http


def strumenti_per_variante(
    variante: str, strumenti_mcp: Sequence[BaseTool], orologio_api_url: str
) -> list[BaseTool]:
    """Restituisce l'elenco finale degli strumenti da passare al grafo (e quindi a bind_tools)."""
    if variante == "mcp":
        return list(strumenti_mcp)

    if variante == "locale":
        orologio = crea_orologio()
    elif variante == "fastapi":
        orologio = crea_orologio_http(orologio_api_url)
    else:
        raise ValueError(f"variante sconosciuta: «{variante}»")

    # Si tolgono dal catalogo MCP i tool con lo stesso nome, per non avere due «orologio».
    altri = [s for s in strumenti_mcp if s.name != orologio.name]
    return [orologio, *altri]
