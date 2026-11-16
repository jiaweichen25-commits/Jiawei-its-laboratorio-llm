"""Prove reali del back-end (lezione 6, step 7).

  pytest -m docker   -k backend   PostgreSQL vero nel container, agente simulato
  pytest -m lmstudio -k backend   PostgreSQL vero + servizio dell'agente vero + LM Studio

Serve `docker compose up -d postgres` (la prova docker lo avvia da sola) e il file .env con DATABASE_URL.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from backend.agente_http import AgenteHttp
from backend.app import crea_app
from backend.archivio import Archivio

ROOT = Path(__file__).resolve().parent.parent


def compose(*argomenti, timeout=300):
    return subprocess.run(["docker", "compose", *argomenti], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def aspetta_postgres(url: str, secondi: int = 90) -> None:
    for _ in range(secondi):
        archivio = Archivio(url)
        pronto = archivio.raggiungibile()
        archivio.chiudi()
        if pronto:
            return
        time.sleep(1)
    pytest.fail("PostgreSQL non è diventato raggiungibile: " + compose("logs", "postgres").stdout[-1500:])


@pytest.fixture(scope="module")
def database_url():
    load_dotenv(ROOT / ".env", override=False)
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("Serve DATABASE_URL di PostgreSQL nel file .env.")
    return url


def app_con_agente_simulato(url, risposta="Risposta di prova."):
    def agente_finto(richiesta):
        return httpx.Response(200, json={"risposta": risposta, "strumenti_usati": [], "cronologia": [],
                                         "riassunto": "", "rifiutata": False, "revisioni": [], "messaggi_riassunti": 0})

    archivio = Archivio(url)
    archivio.prepara()
    agente = AgenteHttp("http://agente.test", transport=httpx.MockTransport(agente_finto))
    return TestClient(crea_app(archivio=archivio, agente=agente)), archivio


@pytest.mark.docker
def test_backend_postgres_chat_presenti_dopo_i_riavvii(database_url):
    # Slide 14 e 19: le conversazioni restano disponibili dopo il riavvio.
    avvio = compose("up", "-d", "postgres")
    assert avvio.returncode == 0, avvio.stdout + avvio.stderr
    aspetta_postgres(database_url)

    client, archivio = app_con_agente_simulato(database_url)
    chat_id = client.post("/chat").json()["id"]
    try:
        assert client.post(f"/chat/{chat_id}/messaggi", json={"testo": "Prova di persistenza"}).status_code == 200
        archivio.chiudi()

        # 1) riavvio del back-end: applicazione e connessioni nuove, stesso database
        client, archivio = app_con_agente_simulato(database_url)
        assert [m["testo"] for m in client.get(f"/chat/{chat_id}").json()["messaggi"]] == [
            "Prova di persistenza", "Risposta di prova.",
        ]
        archivio.chiudi()

        # 2) riavvio del container di PostgreSQL: i dati stanno nel volume
        assert compose("restart", "postgres").returncode == 0
        aspetta_postgres(database_url)
        client, archivio = app_con_agente_simulato(database_url)
        chat = client.get(f"/chat/{chat_id}").json()
        assert chat["titolo"] == "Prova di persistenza" and chat["numero_messaggi"] == 2
        assert chat_id in [c["id"] for c in client.get("/chat").json()]
    finally:
        client.delete(f"/chat/{chat_id}")  # la prova non lascia chat nel database del laboratorio
        archivio.chiudi()


def avvia_uvicorn(modulo: str, porta: int, ambiente: dict) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", modulo, "--port", str(porta)],
        cwd=ROOT, env={**os.environ, **ambiente}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def aspetta_stato(url: str, processo: subprocess.Popen, tentativi: int = 120) -> None:
    for _ in range(tentativi):
        try:
            if httpx.get(f"{url}/stato", timeout=30).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if processo.poll() is not None:
            pytest.fail(f"il servizio su {url} è terminato all'avvio")
        time.sleep(0.5)
    pytest.fail(f"il servizio su {url} non è diventato pronto")


@pytest.mark.lmstudio
def test_backend_reale_domanda_con_strumento_salvata_e_riletta(database_url):
    # Catena intera: back-end → servizio dell'agente → LM Studio, con PostgreSQL vero.
    aspetta_postgres(database_url, secondi=5)
    agente_url, backend_url = "http://127.0.0.1:8011", "http://127.0.0.1:8012"
    agente = avvia_uvicorn("assistente.servizio_agente:app", 8011, {})
    backend = avvia_uvicorn("backend.app:app", 8012, {"AGENTE_URL": agente_url})
    chat_id = None
    try:
        aspetta_stato(agente_url, agente)
        aspetta_stato(backend_url, backend)

        chat_id = httpx.post(f"{backend_url}/chat").json()["id"]
        r = httpx.post(f"{backend_url}/chat/{chat_id}/messaggi", json={"testo": "Che ore sono a Tokyo?"}, timeout=600)

        assert r.status_code == 200, r.text
        assert any(s["nome"] == "orologio" and s["argomenti"].get("fuso") == "Asia/Tokyo"
                   for s in r.json()["risposta"]["strumenti"]), r.json()

        # Riavvio del back-end: la chat, con lo strumento usato, è ancora nel database.
        backend.terminate()
        backend.wait(30)
        backend = avvia_uvicorn("backend.app:app", 8012, {"AGENTE_URL": agente_url})
        aspetta_stato(backend_url, backend)
        chat = httpx.get(f"{backend_url}/chat/{chat_id}").json()
        assert [m["ruolo"] for m in chat["messaggi"]] == ["utente", "assistente"]
        assert chat["messaggi"][1]["strumenti"][0]["nome"] == "orologio"
    finally:
        if chat_id is not None and backend.poll() is None:
            httpx.delete(f"{backend_url}/chat/{chat_id}")
        for processo in (backend, agente):
            processo.terminate()
            processo.wait(30)
