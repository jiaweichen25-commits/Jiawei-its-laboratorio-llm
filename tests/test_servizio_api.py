"""Test del servizio FastAPI (variante 2, lato servizio) senza avviare un server vero.

TestClient esegue le richieste HTTP direttamente sull'app, in memoria.
"""

import re

from fastapi.testclient import TestClient

from assistente.servizio_api import app

client = TestClient(app)


def test_orologio_fuso_valido():
    risposta = client.get("/orologio", params={"fuso": "Asia/Tokyo"})

    assert risposta.status_code == 200
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+09:00 \(Asia/Tokyo\), \w+ì?", risposta.json()["risultato"])


def test_orologio_fuso_non_valido_400():
    risposta = client.get("/orologio", params={"fuso": "Mars/Olympus"})

    assert risposta.status_code == 400
    assert risposta.json()["detail"] == "fuso orario sconosciuto: «Mars/Olympus»"


def test_parametro_mancante_422():
    # FastAPI valida da solo i parametri obbligatori dichiarati nella firma.
    assert client.get("/orologio").status_code == 422


def test_openapi_descrive_l_endpoint():
    # Slide 5: FastAPI genera dal codice la descrizione OpenAPI (/openapi.json e /docs).
    schema = client.get("/openapi.json").json()

    parametri = schema["paths"]["/orologio"]["get"]["parameters"]
    assert parametri[0]["name"] == "fuso"
