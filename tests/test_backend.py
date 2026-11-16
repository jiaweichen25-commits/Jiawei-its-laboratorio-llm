"""Lezione 6, step 7: back-end delle chat.

Database: SQLite in memoria (stesso codice SQLAlchemy che in produzione usa PostgreSQL).
Agente: simulato con httpx.MockTransport, cioè risposte HTTP finte senza rete.
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.agente_http import AgenteHttp
from backend.app import crea_app
from backend.archivio import Archivio
from backend.config import ErroreConfigurazione, carica_configurazione


class Orologio:
    """Tempo finto che avanza di un secondo a ogni lettura: ordini prevedibili nei test."""

    def __init__(self):
        self.istante = datetime(2026, 11, 16, 9, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        self.istante += timedelta(seconds=1)
        return self.istante


class AgenteFinto:
    """Gestore per MockTransport: registra le richieste e risponde come il servizio dell'agente."""

    def __init__(self, *risposte):
        self.risposte = list(risposte)   # dict (corpo 200), httpx.Response oppure eccezione
        self.richieste = []
        self.stato = httpx.Response(200, json={"agente": "ok", "server_mcp": "ok", "modello": "ok"})

    def __call__(self, richiesta: httpx.Request) -> httpx.Response:
        if richiesta.url.path == "/stato":
            if isinstance(self.stato, Exception):
                raise self.stato
            return self.stato
        corpo = json.loads(richiesta.content)
        self.richieste.append(corpo)
        prossima = self.risposte.pop(0) if self.risposte else {}
        if isinstance(prossima, Exception):
            raise prossima
        if isinstance(prossima, httpx.Response):
            return prossima
        # Chiavi speciali per lo streaming: eventi intermedi, errore a metà, flusso troncato.
        prossima = dict(prossima)
        eventi, errore, tronca = prossima.pop("eventi", []), prossima.pop("errore", None), prossima.pop("tronca", False)
        esito = {
            "risposta": "ok", "strumenti_usati": [], "cronologia": [], "riassunto": corpo["riassunto"],
            "rifiutata": False, "revisioni": [], "messaggi_riassunti": 0, **prossima,
        }
        if richiesta.url.path != "/conversazione/stream":
            return httpx.Response(200, json=esito)
        eventi = list(eventi)
        if errore is not None:
            eventi.append(("errore", errore))
        elif not tronca:
            eventi.append(("fine", esito))
        testo = "".join(f"event: {tipo}\ndata: {json.dumps(dati, ensure_ascii=False)}\n\n" for tipo, dati in eventi)
        return httpx.Response(200, content=testo.encode("utf-8"), headers={"content-type": "text/event-stream"})


def ambiente(*risposte, url="sqlite://", cors_origini=()):
    finto = AgenteFinto(*risposte)
    archivio = Archivio(url, adesso=Orologio())
    archivio.prepara()
    agente = AgenteHttp("http://agente.test", transport=httpx.MockTransport(finto))
    return TestClient(crea_app(archivio=archivio, agente=agente, cors_origini=cors_origini)), finto


def eventi_sse(testo: str) -> list[tuple[str, dict]]:
    eventi = []
    for blocco in testo.strip().split("\n\n"):
        righe = dict(riga.split(": ", 1) for riga in blocco.splitlines())
        eventi.append((righe["event"], json.loads(righe["data"])))
    return eventi


def invia_stream(client, chat_id, testo):
    return client.post(f"/chat/{chat_id}/messaggi/stream", json={"testo": testo})


def nuova_chat(client) -> str:
    return client.post("/chat").json()["id"]


def invia(client, chat_id, testo):
    return client.post(f"/chat/{chat_id}/messaggi", json={"testo": testo})


# ---------------------------------------------------------------- le cinque operazioni

def test_creare_una_chat():
    client, _ = ambiente()

    r = client.post("/chat")

    assert r.status_code == 201
    chat = r.json()
    assert len(chat["id"]) == 36 and chat["titolo"] == "Nuova chat" and chat["numero_messaggi"] == 0


def test_inviare_un_messaggio_salva_domanda_e_risposta():
    strumenti = [{"nome": "orologio", "argomenti": {"fuso": "Asia/Tokyo"}, "risultato": "00:42"}]
    client, finto = ambiente({"risposta": "Sono le 00:42.", "strumenti_usati": strumenti})
    chat_id = nuova_chat(client)

    r = invia(client, chat_id, "Che ore sono a Tokyo?")

    assert r.status_code == 200
    corpo = r.json()
    assert corpo["domanda"]["ruolo"] == "utente" and corpo["domanda"]["testo"] == "Che ore sono a Tokyo?"
    assert corpo["risposta"]["ruolo"] == "assistente" and corpo["risposta"]["testo"] == "Sono le 00:42."
    assert corpo["risposta"]["strumenti"] == strumenti
    assert corpo["chat"]["titolo"] == "Che ore sono a Tokyo?" and corpo["chat"]["numero_messaggi"] == 2
    assert finto.richieste == [{"cronologia": [], "riassunto": "", "domanda": "Che ore sono a Tokyo?", "prompt": None}]


def test_leggere_una_chat_messaggi_in_ordine_cronologico():
    client, _ = ambiente({"risposta": "r1"}, {"risposta": "r2"})
    chat_id = nuova_chat(client)
    invia(client, chat_id, "d1")
    invia(client, chat_id, "d2")

    chat = client.get(f"/chat/{chat_id}").json()

    assert [(m["ruolo"], m["testo"]) for m in chat["messaggi"]] == [
        ("utente", "d1"), ("assistente", "r1"), ("utente", "d2"), ("assistente", "r2"),
    ]
    assert [m["creato_il"] for m in chat["messaggi"]] == sorted(m["creato_il"] for m in chat["messaggi"])


def test_la_cronologia_precedente_arriva_all_agente():
    client, finto = ambiente({"risposta": "Piacere."}, {"risposta": "Jiawei."})
    chat_id = nuova_chat(client)
    invia(client, chat_id, "Mi chiamo Jiawei")

    invia(client, chat_id, "Come mi chiamo?")

    assert finto.richieste[1]["cronologia"] == [
        {"ruolo": "utente", "testo": "Mi chiamo Jiawei"}, {"ruolo": "assistente", "testo": "Piacere."},
    ]
    assert finto.richieste[1]["domanda"] == "Come mi chiamo?"


def test_elencare_le_chat_dalla_piu_recente_con_titolo_e_data():
    client, _ = ambiente({"risposta": "r"}, {"risposta": "r"})
    prima, seconda = nuova_chat(client), nuova_chat(client)
    invia(client, seconda, "seconda chat")
    invia(client, prima, "prima chat, ma con il messaggio più recente")

    elenco = client.get("/chat").json()

    assert [c["id"] for c in elenco] == [prima, seconda]
    assert elenco[0]["titolo"].startswith("prima chat") and elenco[0]["numero_messaggi"] == 2
    assert elenco[0]["aggiornata_il"] > elenco[1]["aggiornata_il"]
    assert "messaggi" not in elenco[0]  # l'elenco non porta con sé i messaggi


def test_eliminare_una_chat_toglie_anche_i_messaggi():
    client, _ = ambiente({"risposta": "r"})
    chat_id = nuova_chat(client)
    altra = nuova_chat(client)
    invia(client, chat_id, "d")

    assert client.delete(f"/chat/{chat_id}").status_code == 204

    assert client.get(f"/chat/{chat_id}").status_code == 404
    assert [c["id"] for c in client.get("/chat").json()] == [altra]
    assert client.app.state.archivio.numero_messaggi_totale() == 0


# ---------------------------------------------------------------- titolo

def test_titolo_dai_primi_60_caratteri_della_prima_domanda_su_una_riga():
    client, _ = ambiente({"risposta": "r"}, {"risposta": "r"})
    chat_id = nuova_chat(client)

    invia(client, chat_id, "  Prima riga\nseconda riga " + "x" * 100)
    invia(client, chat_id, "altra domanda")

    titolo = client.get(f"/chat/{chat_id}").json()["titolo"]
    assert titolo.startswith("Prima riga seconda riga x") and len(titolo) == 60


# ---------------------------------------------------------------- errori

def test_chat_inesistente_404():
    client, finto = ambiente()

    assert client.get("/chat/non-esiste").status_code == 404
    assert client.delete("/chat/non-esiste").status_code == 404
    r = invia(client, "non-esiste", "ciao")
    assert r.status_code == 404 and r.json()["detail"] == "Chat non trovata."
    assert finto.richieste == []  # l'agente non viene disturbato


@pytest.mark.parametrize("corpo", [{"testo": ""}, {"testo": "   "}, {}, {"testo": 5}])
def test_testo_non_valido_422(corpo):
    client, finto = ambiente()
    chat_id = nuova_chat(client)

    assert client.post(f"/chat/{chat_id}/messaggi", json=corpo).status_code == 422
    assert finto.richieste == []


@pytest.mark.parametrize("guasto", [
    httpx.ConnectError("rifiutata"), httpx.ReadTimeout("lento"),
], ids=["spento", "lento"])
def test_agente_non_raggiungibile_503_e_chat_invariata(guasto):
    client, _ = ambiente(guasto, {"risposta": "ora sì"})
    chat_id = nuova_chat(client)

    r = invia(client, chat_id, "ciao")

    assert r.status_code == 503
    assert "non è stato salvato" in r.json()["detail"]
    chat = client.get(f"/chat/{chat_id}").json()
    assert chat["messaggi"] == [] and chat["titolo"] == "Nuova chat"
    # Riprovando funziona, e la cronologia non contiene la domanda fallita.
    assert invia(client, chat_id, "ciao").status_code == 200
    assert len(client.get(f"/chat/{chat_id}").json()["messaggi"]) == 2


def test_errore_dell_agente_502_con_il_suo_messaggio():
    errore = httpx.Response(503, json={"detail": "Connessione a LM Studio fallita: controllare server, URL e porta."})
    client, _ = ambiente(errore)
    chat_id = nuova_chat(client)

    r = invia(client, chat_id, "ciao")

    assert r.status_code == 502
    assert "Connessione a LM Studio fallita" in r.json()["detail"]
    assert client.get(f"/chat/{chat_id}").json()["messaggi"] == []


def test_risposta_vuota_dell_agente_502():
    client, _ = ambiente({"risposta": "  "})
    chat_id = nuova_chat(client)

    r = invia(client, chat_id, "ciao")

    assert r.status_code == 502 and client.get(f"/chat/{chat_id}").json()["messaggi"] == []


# ---------------------------------------------------------------- riassunto

def test_dopo_il_riassunto_all_agente_vanno_solo_i_messaggi_non_coperti():
    client, finto = ambiente(
        {"risposta": "r1"}, {"risposta": "r2"},
        {"risposta": "r3", "riassunto": "L'utente si chiama Jiawei.", "messaggi_riassunti": 2},
        {"risposta": "r4"},
    )
    chat_id = nuova_chat(client)
    for domanda in ("d1", "d2", "d3", "d4"):
        invia(client, chat_id, domanda)

    quarta = finto.richieste[3]
    assert quarta["riassunto"] == "L'utente si chiama Jiawei."
    assert [m["testo"] for m in quarta["cronologia"]] == ["d2", "r2", "d3", "r3"]  # d1 e r1 sono nel riassunto
    # L'utente continua a vedere tutta la conversazione.
    assert len(client.get(f"/chat/{chat_id}").json()["messaggi"]) == 8


# ---------------------------------------------------------------- stato, OpenAPI, persistenza

def test_stato_tutto_ok():
    client, _ = ambiente()

    r = client.get("/stato")

    assert r.status_code == 200 and r.json() == {"backend": "ok", "database": "ok", "agente": "ok"}


def test_stato_con_agente_spento_503():
    client, finto = ambiente()
    finto.stato = httpx.ConnectError("rifiutata")

    r = client.get("/stato")

    assert r.status_code == 503 and r.json()["database"] == "ok"
    assert r.json()["agente"] == "non raggiungibile su http://agente.test"  # breve: finisce nell'interfaccia


def test_stato_con_agente_non_pronto_503():
    client, finto = ambiente()
    finto.stato = httpx.Response(503, json={"agente": "ok", "server_mcp": "ok", "modello": "LM Studio non raggiungibile"})

    r = client.get("/stato")

    assert r.status_code == 503 and "LM Studio non raggiungibile" in r.json()["agente"]


def test_documentazione_openapi():
    client, _ = ambiente()

    percorsi = client.get("/openapi.json").json()["paths"]

    assert set(percorsi) == {
        "/chat", "/chat/{chat_id}", "/chat/{chat_id}/messaggi", "/chat/{chat_id}/messaggi/stream", "/stato",
    }
    assert set(percorsi["/chat"]) == {"get", "post"} and set(percorsi["/chat/{chat_id}"]) == {"get", "delete"}


def test_le_chat_restano_dopo_il_riavvio(tmp_path):
    url = f"sqlite:///{(tmp_path / 'chat.db').as_posix()}"
    client, _ = ambiente({"risposta": "r1"}, url=url)
    chat_id = nuova_chat(client)
    invia(client, chat_id, "d1")
    client.app.state.archivio.chiudi()

    riavviato, _ = ambiente(url=url)  # archivio e applicazione nuovi sullo stesso database

    chat = riavviato.get(f"/chat/{chat_id}").json()
    assert [m["testo"] for m in chat["messaggi"]] == ["d1", "r1"] and chat["titolo"] == "d1"
    riavviato.app.state.archivio.chiudi()


# ---------------------------------------------------------------- streaming (slide 18)

STRUMENTO = {"nome": "orologio", "argomenti": {"fuso": "Asia/Tokyo"}, "risultato": "00:42"}


def test_stream_inoltra_gli_eventi_e_salva_alla_fine():
    client, finto = ambiente({
        "eventi": [("strumento", STRUMENTO), ("testo", {"testo": "Sono le "}), ("testo", {"testo": "00:42."})],
        "risposta": "Sono le 00:42.", "strumenti_usati": [STRUMENTO],
    })
    chat_id = nuova_chat(client)

    r = invia_stream(client, chat_id, "Che ore sono a Tokyo?")

    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    eventi = eventi_sse(r.text)
    assert eventi[:3] == [("strumento", STRUMENTO), ("testo", {"testo": "Sono le "}), ("testo", {"testo": "00:42."})]
    tipo, scambio = eventi[-1]
    assert tipo == "fine" and len(eventi) == 4
    assert scambio["risposta"]["testo"] == "Sono le 00:42." and scambio["risposta"]["strumenti"] == [STRUMENTO]
    assert scambio["chat"]["titolo"] == "Che ore sono a Tokyo?"
    assert [m["testo"] for m in client.get(f"/chat/{chat_id}").json()["messaggi"]] == ["Che ore sono a Tokyo?", "Sono le 00:42."]
    assert finto.richieste[0]["domanda"] == "Che ore sono a Tokyo?"


def test_stream_errore_dell_agente_a_meta_non_salva():
    client, _ = ambiente({
        "eventi": [("testo", {"testo": "Sto"})],
        "errore": {"codice": 503, "detail": "Connessione a LM Studio fallita."},
    })
    chat_id = nuova_chat(client)

    eventi = eventi_sse(invia_stream(client, chat_id, "ciao").text)

    assert eventi[-1][0] == "errore" and eventi[-1][1]["codice"] == 502
    assert "Connessione a LM Studio fallita" in eventi[-1][1]["detail"]
    assert "non è stato salvato" in eventi[-1][1]["detail"]
    assert client.get(f"/chat/{chat_id}").json()["messaggi"] == []


def test_stream_troncato_non_salva():
    client, _ = ambiente({"eventi": [("testo", {"testo": "Sto"})], "tronca": True})
    chat_id = nuova_chat(client)

    eventi = eventi_sse(invia_stream(client, chat_id, "ciao").text)

    assert eventi[-1][0] == "errore" and "non è stato salvato" in eventi[-1][1]["detail"]
    assert client.get(f"/chat/{chat_id}").json()["messaggi"] == []


def test_stream_agente_spento_resta_un_503():
    client, _ = ambiente(httpx.ConnectError("rifiutata"))
    chat_id = nuova_chat(client)

    r = invia_stream(client, chat_id, "ciao")

    assert r.status_code == 503 and "non è stato salvato" in r.json()["detail"]


def test_stream_errore_dell_agente_prima_del_flusso_resta_un_502():
    client, _ = ambiente(httpx.Response(422, json={"detail": "richiesta non valida"}))
    chat_id = nuova_chat(client)

    r = invia_stream(client, chat_id, "ciao")

    assert r.status_code == 502 and "richiesta non valida" in r.json()["detail"]


def test_stream_chat_inesistente_e_testo_vuoto():
    client, finto = ambiente()

    assert invia_stream(client, "non-esiste", "ciao").status_code == 404
    assert invia_stream(client, nuova_chat(client), "  ").status_code == 422
    assert finto.richieste == []


def test_stream_usa_e_aggiorna_il_riassunto():
    client, finto = ambiente(
        {"risposta": "r1"},
        {"risposta": "r2", "riassunto": "riassunto", "messaggi_riassunti": 2,
         "eventi": [("riassunto", {"messaggi_riassunti": 2})]},
        {"risposta": "r3"},
    )
    chat_id = nuova_chat(client)
    for domanda in ("d1", "d2", "d3"):
        invia_stream(client, chat_id, domanda)

    assert finto.richieste[2]["riassunto"] == "riassunto"
    assert [m["testo"] for m in finto.richieste[2]["cronologia"]] == ["d2", "r2"]


# ---------------------------------------------------------------- CORS (step 8: la pagina sta su un'altra porta)

def test_cors_origine_ammessa_e_non_ammessa():
    client, _ = ambiente(cors_origini=("http://localhost:8003",))

    ammessa = client.get("/chat", headers={"Origin": "http://localhost:8003"})
    estranea = client.get("/chat", headers={"Origin": "http://altro.example"})

    assert ammessa.headers.get("access-control-allow-origin") == "http://localhost:8003"
    assert "access-control-allow-origin" not in estranea.headers


def test_cors_spento_senza_configurazione():
    client, _ = ambiente()

    assert "access-control-allow-origin" not in client.get("/chat", headers={"Origin": "http://localhost:8003"}).headers


def test_cors_preflight_per_l_invio():
    client, _ = ambiente(cors_origini=("http://localhost:8003",))

    r = client.options("/chat/x/messaggi/stream", headers={
        "Origin": "http://localhost:8003", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })

    assert r.status_code == 200 and "POST" in r.headers["access-control-allow-methods"]


def test_configurazione_cors():
    c = carica_configurazione({"DATABASE_URL": "sqlite://", "CORS_ORIGINI": " http://localhost:8003/ , http://127.0.0.1:8003 "})

    assert c.cors_origini == ("http://localhost:8003", "http://127.0.0.1:8003")
    assert carica_configurazione({"DATABASE_URL": "sqlite://"}).cors_origini == ()


# ---------------------------------------------------------------- configurazione

def test_configurazione():
    c = carica_configurazione({"DATABASE_URL": " postgresql+psycopg://u:p@localhost:5433/chat ", "AGENTE_URL": "http://agente:8001/"})

    assert c.database_url == "postgresql+psycopg://u:p@localhost:5433/chat"
    assert (c.agente_url, c.agente_timeout, c.log_level) == ("http://agente:8001", 600.0, "INFO")


def test_configurazione_senza_database_url():
    with pytest.raises(ErroreConfigurazione, match="DATABASE_URL"):
        carica_configurazione({})


def test_configurazione_timeout_non_valido():
    with pytest.raises(ErroreConfigurazione, match="AGENTE_TIMEOUT"):
        carica_configurazione({"DATABASE_URL": "sqlite://", "AGENTE_TIMEOUT": "mai"})
