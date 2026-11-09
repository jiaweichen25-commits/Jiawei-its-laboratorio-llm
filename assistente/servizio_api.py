"""Variante 2, LATO SERVIZIO — l'orologio esposto come API HTTP con FastAPI (slide 4, 5, 19).

Questo è un programma separato dall'agente: gira in un altro processo e risponde su HTTP.
Avvio (PowerShell, dalla cartella del progetto):

    .\\.venv\\Scripts\\python.exe -m uvicorn assistente.servizio_api:app --port 8000

Poi: http://localhost:8000/orologio?fuso=Asia/Tokyo  e la documentazione interattiva su /docs.
FastAPI genera da solo la descrizione OpenAPI (/openapi.json) leggendo la firma della funzione.
"""

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from assistente.logica import ErroreStrumento, ora_nel_fuso, ora_utc

app = FastAPI(
    title="Orologio ITS",
    description="Data, ora e giorno della settimana in un fuso orario IANA.",
)


@app.get("/orologio")
def orologio(
    # Query(...): `fuso` è un parametro della URL (?fuso=...), obbligatorio, con descrizione per OpenAPI.
    fuso: Annotated[str, Query(description="Nome IANA del fuso orario, es. Asia/Tokyo")],
) -> dict[str, str]:
    """Endpoint GET /orologio: la stessa logica della variante locale, raggiunta via HTTP."""
    try:
        return {"risultato": ora_nel_fuso(fuso, ora_utc())}
    except ErroreStrumento as exc:
        # 400 = «richiesta sbagliata»: l'errore è nel dato inviato, non nel servizio.
        # Così il client distingue un fuso non valido (400) da un servizio guasto (5xx o nessuna risposta).
        raise HTTPException(status_code=400, detail=str(exc)) from None
