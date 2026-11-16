"""Lezione 6, step 4: preferenze dell'utente lette dalla resource MCP `utente://preferenze`.

La resource la decide l'HOST, non il modello (slide 7 e 11): il programma la legge una volta
all'avvio, prima della prima domanda, e la mette in cima al messaggio di sistema. Il modello
la usa come contesto senza «chiamarla».

Qui si valida il contenuto. Se qualcosa non va (file mancante, JSON rotto, valori sbagliati)
l'agente parte comunque con i valori predefiniti e lo scrive nei log (slide 8, punto 4).
"""

import json
import logging
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from assistente.config import fuso_valido

log = logging.getLogger("assistente.preferenze")

# URI della resource sul server MCP: lo usano sia il server (che la espone) sia l'host (che la legge).
URI_PREFERENZE = "utente://preferenze"


class Preferenze(BaseModel):
    """Contenuto di `preferenze.json`."""

    model_config = ConfigDict(extra="ignore")  # un campo in più nel file non è un errore

    lingua: str = "italiano"
    fuso_predefinito: str
    stile: Literal["sintetico", "dettagliato"] = "sintetico"

    @field_validator("lingua")
    @classmethod
    def _lingua_non_vuota(cls, valore: str) -> str:
        if not valore.strip():
            raise ValueError("la lingua non può essere vuota")
        return valore.strip()

    @field_validator("fuso_predefinito")
    @classmethod
    def _fuso_iana(cls, valore: str) -> str:
        if not fuso_valido(valore):
            raise ValueError(f"fuso orario sconosciuto: «{valore}»")
        return valore


def carica_preferenze(leggi: Callable[[], str], fuso_di_riserva: str) -> Preferenze:
    """Legge e valida le preferenze. Non solleva mai: in caso di problemi usa i predefiniti.

    `leggi` restituisce il testo della resource: nell'applicazione è la lettura MCP, nei test
    una funzione con un testo fisso. `fuso_di_riserva` è TZ_PREDEFINITO: vale quando il file
    non indica un fuso.
    """
    try:
        dati = json.loads(leggi())
        if not isinstance(dati, dict):
            raise ValueError("il file deve contenere un oggetto JSON")
        # Il fuso di riserva fa da base: se il file ne indica uno, quello del file lo sostituisce.
        return Preferenze.model_validate({"fuso_predefinito": fuso_di_riserva, **dati})
    except ValidationError as exc:
        motivo = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
    except Exception as exc:  # resource assente, server caduto, JSON rotto, oggetto sbagliato
        motivo = str(exc)
    log.warning("preferenze: non utilizzabili (%s), uso i valori predefiniti", motivo)
    return Preferenze(fuso_predefinito=fuso_di_riserva)
