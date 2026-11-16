"""Prova reale dell'applicazione completa in Docker Compose (lezione 6, step 9): pytest -m docker

Servono Docker Desktop acceso, LM Studio con il modello caricato e il file .env.
Segue le evidenze della slide 16: quattro servizi attivi, chat dal browser con uno strumento
visibile nei log dell'agente, chat ancora presenti dopo down e up, agente non esposto.
"""

import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parent.parent
PORTA = os.environ.get("PORTA_WEB") or dotenv_values(ROOT / ".env").get("PORTA_WEB") or "8085"
URL = f"http://localhost:{PORTA}"


def compose(*argomenti, timeout=900):
    return subprocess.run(["docker", "compose", *argomenti], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def aspetta_applicazione(secondi: int = 240) -> None:
    """Aspetta che il proxy risponda e che back-end, database e agente siano tutti «ok»."""
    ultimo = "nessuna risposta"
    for _ in range(secondi // 2):
        try:
            risposta = httpx.get(f"{URL}/api/stato", timeout=30)
            ultimo = f"{risposta.status_code} {risposta.text[:200]}"
            if risposta.status_code == 200:
                return
        except httpx.HTTPError as exc:
            ultimo = repr(exc)
        time.sleep(2)
    pytest.fail(f"applicazione non pronta ({ultimo})\n" + compose("logs", "--tail", "40").stdout[-3000:])


def eventi_stream(chat_id: str, testo: str) -> list[tuple[str, dict]]:
    eventi, tipo = [], None
    with httpx.stream("POST", f"{URL}/api/chat/{chat_id}/messaggi/stream", json={"testo": testo}, timeout=900) as flusso:
        assert flusso.status_code == 200, flusso.read()
        for riga in flusso.iter_lines():
            if riga.startswith("event:"):
                tipo = riga[6:].strip()
            elif riga.startswith("data:"):
                eventi.append((tipo, json.loads(riga[5:])))
    return eventi


def test_applicazione_completa_in_quattro_container():
    if not (ROOT / ".env").is_file():
        pytest.skip("Serve un file .env valido per la prova Docker.")

    avvio = compose("up", "-d", "--build")
    assert avvio.returncode == 0, avvio.stdout[-2000:] + avvio.stderr[-3000:]
    chat_id = None
    try:
        aspetta_applicazione()

        # 1) docker compose ps: i quattro servizi sono attivi
        righe = [json.loads(riga) for riga in compose("ps", "--format", "json").stdout.splitlines() if riga.strip()]
        assert {r["Service"]: r["State"] for r in righe} == {
            "frontend": "running", "backend": "running", "agente": "running", "postgres": "running",
        }

        # 2) agente e back-end non hanno porte pubblicate sul computer
        assert compose("port", "agente", "8001").stdout.strip() == ""
        assert compose("port", "backend", "8002").stdout.strip() == ""

        # 3) il browser riceve la pagina, configurata per usare il proxy
        assert "Assistente del laboratorio" in httpx.get(URL, timeout=30).text
        assert '"/api"' in httpx.get(f"{URL}/config.js", timeout=30).text

        # 4) chat con uno strumento, in streaming attraverso proxy → back-end → agente → LM Studio
        chat_id = httpx.post(f"{URL}/api/chat", timeout=30).json()["id"]
        eventi = eventi_stream(chat_id, "Che ore sono a Tokyo?")
        tipi = [tipo for tipo, _ in eventi]
        assert tipi[-1] == "fine" and "errore" not in tipi, eventi
        orologio = [dati for tipo, dati in eventi if tipo == "strumento" and dati["nome"] == "orologio"]
        assert orologio and not orologio[0]["risultato"].startswith("Errore"), eventi
        assert tipi.count("testo") >= 2, tipi  # il proxy non ha accumulato il testo in un blocco solo
        assert "strumenti: richiesta orologio" in compose("logs", "agente").stdout

        # 5) down e up: le chat sono ancora presenti (i dati stanno nel volume)
        assert compose("down").returncode == 0
        assert compose("up", "-d").returncode == 0
        aspetta_applicazione()
        chat = httpx.get(f"{URL}/api/chat/{chat_id}", timeout=30).json()
        assert [m["ruolo"] for m in chat["messaggi"]] == ["utente", "assistente"]
        assert chat["messaggi"][1]["strumenti"][0]["nome"] == "orologio"
    finally:
        if chat_id is not None:
            try:
                httpx.delete(f"{URL}/api/chat/{chat_id}", timeout=30)  # la prova non lascia chat nel database
            except httpx.HTTPError:
                pass
        compose("down")
