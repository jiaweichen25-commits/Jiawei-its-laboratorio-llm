"""Variante 2, LATO AGENTE — wrapper HTTP registrato come tool (slide 19).

Il wrapper è una funzione Python che, invece di calcolare l'ora, chiama l'endpoint del servizio
FastAPI (servizio_api.py) e ne restituisce la risposta. Viene registrato con @tool esattamente come
la funzione della variante locale: il grafo non sa che dietro c'è HTTP.

Limite di questa variante (slide 19 e 21): nome, descrizione e schema del tool sono scritti A MANO
qui nell'agente; non c'è discovery. Se l'endpoint cambia, il wrapper va aggiornato in ogni
applicazione che lo usa.
"""

from typing import Annotated

import httpx
from langchain_core.tools import BaseTool, tool
from pydantic import Field

from assistente.strumenti import DESCRIZIONE_FUSO, DESCRIZIONE_OROLOGIO

TIMEOUT_SECONDI = 5.0  # oltre questo tempo il servizio è considerato non disponibile


def crea_orologio_http(base_url: str, client: httpx.Client | None = None) -> BaseTool:
    """Crea il tool `orologio` che interroga GET {base_url}/orologio?fuso=...

    `client` si passa nei test per simulare le risposte senza rete (httpx.MockTransport).
    """
    base_url = base_url.rstrip("/")
    http = client or httpx.Client(timeout=TIMEOUT_SECONDI)

    @tool("orologio", description=DESCRIZIONE_OROLOGIO)
    def orologio(fuso: Annotated[str, Field(description=DESCRIZIONE_FUSO)]) -> str:
        # Il wrapper TRADUCE i tre esiti possibili in testo comprensibile per il modello (slide 19).
        try:
            risposta = http.get(f"{base_url}/orologio", params={"fuso": fuso})
        except httpx.HTTPError as exc:
            # 1) Errore di TRASPORTO: servizio spento, porta sbagliata, timeout...
            return f"Errore di collegamento al servizio orologio ({base_url}): {exc}"

        if risposta.status_code == 400:
            # 2) Errore dello STRUMENTO: il servizio ha risposto, ma il fuso non esiste.
            return f"Errore: {risposta.json()['detail']}"
        if risposta.status_code != 200:
            # Qualsiasi altro codice (500, 404...) è un problema del servizio, non del fuso.
            return f"Errore di collegamento al servizio orologio ({base_url}): HTTP {risposta.status_code}"

        # 3) Successo: il JSON del servizio contiene il campo "risultato".
        return risposta.json()["risultato"]

    orologio.metadata = {"variante": "fastapi"}  # usato solo nei log
    return orologio
