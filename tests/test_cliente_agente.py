"""Lezione 6, step 6: il client HTTP che la CLI usa per parlare con il servizio dell'agente."""

import json

import httpx
import pytest

from assistente.cliente_agente import ClienteAgente, ErroreServizio


def cliente_con(gestore):
    return ClienteAgente("http://agente.test", transport=httpx.MockTransport(gestore))


def test_conversazione_invia_e_riceve_json():
    ricevute = []

    def gestore(richiesta):
        ricevute.append((richiesta.method, richiesta.url.path, json.loads(richiesta.content)))
        return httpx.Response(200, json={"risposta": "ok"})

    risposta = cliente_con(gestore).conversazione([{"ruolo": "utente", "testo": "a"}], "r", domanda="b")

    assert risposta == {"risposta": "ok"}
    assert ricevute == [("POST", "/conversazione", {
        "cronologia": [{"ruolo": "utente", "testo": "a"}], "riassunto": "r", "domanda": "b", "prompt": None,
    })]


def test_errore_http_con_detail():
    cliente = cliente_con(lambda r: httpx.Response(503, json={"detail": "Connessione a LM Studio fallita"}))

    with pytest.raises(ErroreServizio, match="503.*Connessione a LM Studio fallita"):
        cliente.conversazione([], domanda="x")


def test_servizio_spento():
    def gestore(richiesta):
        raise httpx.ConnectError("rifiutata", request=richiesta)

    with pytest.raises(ErroreServizio, match="non raggiungibile.*uvicorn"):
        cliente_con(gestore).conversazione([], domanda="x")


def test_servizio_lento():
    def gestore(richiesta):
        raise httpx.ReadTimeout("lento", request=richiesta)

    with pytest.raises(ErroreServizio, match="non ha risposto"):
        cliente_con(gestore).conversazione([], domanda="x")


def test_prompts_convertiti_in_oggetti_mcp():
    corpo = [{"nome": "spiega", "descrizione": "Spiega.", "argomenti": [
        {"nome": "argomento", "descrizione": "concetto", "obbligatorio": True},
    ]}]

    [prompt] = cliente_con(lambda r: httpx.Response(200, json=corpo)).prompts()

    assert prompt.name == "spiega" and prompt.arguments[0].required


def test_stato_restituisce_il_corpo_anche_con_503():
    corpo = {"agente": "ok", "server_mcp": "ok", "modello": "LM Studio non raggiungibile"}

    assert cliente_con(lambda r: httpx.Response(503, json=corpo)).stato() == corpo
