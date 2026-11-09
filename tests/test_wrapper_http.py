"""Test del wrapper HTTP (variante 2, lato agente) con risposte simulate: niente rete, niente server.

httpx.MockTransport sostituisce la rete con una funzione che decide la risposta.
"""

import httpx

from assistente.wrapper_http import crea_orologio_http

URL = "http://orologio.test"


def wrapper_con(gestore):
    """Crea il tool con un client httpx che non usa la rete ma chiama `gestore(richiesta)`."""
    return crea_orologio_http(URL, client=httpx.Client(transport=httpx.MockTransport(gestore)))


def test_richiesta_corretta_e_risultato():
    ricevute = []

    def gestore(richiesta):
        ricevute.append(richiesta)
        return httpx.Response(200, json={"risultato": "2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì"})

    risultato = wrapper_con(gestore).invoke({"fuso": "Asia/Tokyo"})

    assert risultato == "2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì"
    assert ricevute[0].url.path == "/orologio"
    assert ricevute[0].url.params["fuso"] == "Asia/Tokyo"


def test_fuso_non_valido_400():
    def gestore(richiesta):
        return httpx.Response(400, json={"detail": "fuso orario sconosciuto: «Mars/Olympus»"})

    assert wrapper_con(gestore).invoke({"fuso": "Mars/Olympus"}) == "Errore: fuso orario sconosciuto: «Mars/Olympus»"


def test_errore_del_servizio_500():
    def gestore(richiesta):
        return httpx.Response(500, text="Internal Server Error")

    risultato = wrapper_con(gestore).invoke({"fuso": "UTC"})

    assert risultato.startswith("Errore di collegamento al servizio orologio")
    assert "500" in risultato


def test_servizio_spento():
    # Slide 23: «servizio non disponibile» deve essere distinto da «fuso non valido».
    def gestore(richiesta):
        raise httpx.ConnectError("connessione rifiutata", request=richiesta)

    risultato = wrapper_con(gestore).invoke({"fuso": "UTC"})

    assert risultato.startswith("Errore di collegamento al servizio orologio")
    assert URL in risultato


def test_contratto_uguale_alla_variante_locale():
    from assistente.strumenti import crea_orologio

    http = crea_orologio_http(URL)
    locale = crea_orologio()

    assert http.name == locale.name == "orologio"
    assert http.description == locale.description
    assert http.args == locale.args
    assert http.metadata == {"variante": "fastapi"}
