"""Lezione 6, step 6: il servizio HTTP dell'agente con TestClient e il modello finto."""

import httpx
import openai
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from assistente.servizio_agente import crea_app
from tests.test_agente import ORA_TOKYO, PromptFinti, agente_con, chiamata


def client_con(*risposte, **opzioni):
    _, agente = agente_con(*risposte, **opzioni)
    return TestClient(crea_app(agente))


def test_conversazione_con_strumento():
    client = client_con(chiamata("Asia/Tokyo"), AIMessage("Sono le 00:42."))

    r = client.post("/conversazione", json={"cronologia": [], "domanda": "Che ore sono a Tokyo?"})

    assert r.status_code == 200
    corpo = r.json()
    assert corpo["risposta"] == "Sono le 00:42."
    assert corpo["strumenti_usati"] == [{"nome": "orologio", "argomenti": {"fuso": "Asia/Tokyo"}, "risultato": ORA_TOKYO}]
    assert corpo["cronologia"][-1] == {"ruolo": "assistente", "testo": "Sono le 00:42."}
    assert corpo["riassunto"] == "" and corpo["rifiutata"] is False


def test_conversazione_con_prompt():
    client = client_con(AIMessage("Spiegazione."), prompt_mcp=PromptFinti())

    r = client.post("/conversazione", json={"prompt": {"nome": "spiega", "argomenti": {"argomento": "MCP"}}})

    assert r.status_code == 200 and r.json()["risposta"] == "Spiegazione."


def test_domanda_e_prompt_insieme_o_nessuno_422():
    client = client_con()

    assert client.post("/conversazione", json={"domanda": "x", "prompt": {"nome": "spiega"}}).status_code == 422
    assert client.post("/conversazione", json={"cronologia": []}).status_code == 422
    assert client.post("/conversazione", json={"domanda": "   "}).status_code == 422


def test_ruolo_sconosciuto_422():
    client = client_con()

    r = client.post("/conversazione", json={"cronologia": [{"ruolo": "sistema", "testo": "x"}], "domanda": "ciao"})

    assert r.status_code == 422


def test_prompt_non_valido_422_con_messaggio():
    client = client_con(prompt_mcp=PromptFinti())

    r = client.post("/conversazione", json={"prompt": {"nome": "spiega", "argomenti": {"colore": "blu"}}})

    assert r.status_code == 422 and "colore" in r.json()["detail"]


def test_lm_studio_spento_503():
    richiesta = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    client = client_con(openai.APIConnectionError(request=richiesta))

    r = client.post("/conversazione", json={"domanda": "ciao"})

    assert r.status_code == 503 and "LM Studio" in r.json()["detail"]


def test_lm_studio_lento_504():
    richiesta = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    client = client_con(openai.APITimeoutError(request=richiesta))

    r = client.post("/conversazione", json={"domanda": "ciao"})

    assert r.status_code == 504 and "Attesa scaduta" in r.json()["detail"]


def test_server_mcp_caduto_durante_prompt_503():
    client = client_con(prompt_mcp=PromptFinti(guasto=True))

    r = client.post("/conversazione", json={"prompt": {"nome": "spiega", "argomenti": {"argomento": "MCP"}}})

    assert r.status_code == 503 and "MCP" in r.json()["detail"]


def test_troppi_passaggi_500():
    client = client_con(*[chiamata("UTC", id=f"c{i}") for i in range(20)])

    r = client.post("/conversazione", json={"domanda": "ciclo"})

    assert r.status_code == 500 and "Troppi passaggi" in r.json()["detail"]


# ---------------------------------------------------------------- streaming (slide 18)

def eventi_sse(testo: str) -> list[tuple[str, dict]]:
    """Da «event: x / data: {...}» separati da righe vuote a una lista di (tipo, dati)."""
    import json

    eventi = []
    for blocco in testo.strip().split("\n\n"):
        righe = dict(riga.split(": ", 1) for riga in blocco.splitlines())
        eventi.append((righe["event"], json.loads(righe["data"])))
    return eventi


def test_stream_eventi_sse_con_strumento():
    client = client_con(chiamata("Asia/Tokyo"), AIMessage("Sono le 00:42."))

    r = client.post("/conversazione/stream", json={"domanda": "Che ore sono a Tokyo?"})

    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    eventi = eventi_sse(r.text)
    assert [tipo for tipo, _ in eventi] == ["strumento", "testo", "testo", "testo", "fine"]
    assert "".join(d["testo"] for t, d in eventi if t == "testo") == "Sono le 00:42."
    assert eventi[-1][1]["strumenti_usati"][0]["risultato"] == ORA_TOKYO


def test_stream_errore_a_meta_diventa_evento_errore():
    richiesta = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
    client = client_con(chiamata("Asia/Tokyo"), openai.APIConnectionError(request=richiesta))

    r = client.post("/conversazione/stream", json={"domanda": "Che ore sono a Tokyo?"})

    assert r.status_code == 200  # il flusso era già iniziato: l'errore viaggia come evento
    eventi = eventi_sse(r.text)
    assert eventi[-1][0] == "errore"
    assert eventi[-1][1]["codice"] == 503 and "LM Studio" in eventi[-1][1]["detail"]
    assert "fine" not in [tipo for tipo, _ in eventi]


def test_stream_prompt_non_valido_resta_un_422():
    client = client_con(prompt_mcp=PromptFinti())

    r = client.post("/conversazione/stream", json={"prompt": {"nome": "spiega", "argomenti": {"colore": "blu"}}})

    assert r.status_code == 422 and "colore" in r.json()["detail"]


def test_stream_con_caratteri_non_ascii():
    client = client_con(AIMessage("Perché è così — «già»."))

    eventi = eventi_sse(client.post("/conversazione/stream", json={"domanda": "x"}).text)

    assert eventi[-1][1]["risposta"] == "Perché è così — «già»."


def test_elenco_prompt():
    client = client_con(prompt_mcp=PromptFinti())

    assert client.get("/prompts").json() == [{
        "nome": "spiega", "descrizione": "Spiega.",
        "argomenti": [{"nome": "argomento", "descrizione": "concetto", "obbligatorio": True}],
    }]


def test_stato_200_e_503():
    assert client_con(prompt_mcp=PromptFinti(), controlla_modello=lambda: None).get("/stato").status_code == 200

    r = client_con(prompt_mcp=PromptFinti(guasto=True), controlla_modello=lambda: None).get("/stato")
    assert r.status_code == 503 and r.json()["server_mcp"] != "ok"


def test_documentazione_openapi():
    schema = client_con().get("/openapi.json").json()

    assert {"/conversazione", "/prompts", "/stato"} <= set(schema["paths"])
    assert "RichiestaConversazione" in schema["components"]["schemas"]
