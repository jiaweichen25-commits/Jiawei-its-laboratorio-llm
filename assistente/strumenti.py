"""Strumenti che il modello può richiedere e che il programma esegue."""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import BaseTool, tool
from pydantic import Field

DESCRIZIONE_OROLOGIO = (
    "Restituisce la data, l'ora e il giorno della settimana correnti nel fuso orario indicato. "
    "Usalo ogni volta che servono data, ora o giorno attuali."
)

GIORNI = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")


def ora_utc() -> datetime:
    return datetime.now(timezone.utc)


def crea_orologio(adesso: Callable[[], datetime] = ora_utc) -> BaseTool:
    """Crea lo strumento orologio; `adesso` si sostituisce nei test con un istante fisso."""

    @tool("orologio", description=DESCRIZIONE_OROLOGIO)
    def orologio(
        fuso: Annotated[str, Field(description="Nome IANA del fuso orario, per esempio Europe/Rome, Asia/Tokyo o UTC.")],
    ) -> str:
        try:
            zona = ZoneInfo(fuso)
        except (ZoneInfoNotFoundError, ValueError):
            return f"Errore: fuso orario sconosciuto: «{fuso}»"
        ora_locale = adesso().astimezone(zona)
        return f"{ora_locale.isoformat(timespec='seconds')} ({fuso}), {GIORNI[ora_locale.weekday()]}"

    return orologio
