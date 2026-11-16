"""Prova con Docker e LM Studio attivi: pytest -m docker.

Lezione 6, step 6: il container esegue il servizio dell'agente; la prova lo avvia con
docker compose, aspetta GET /stato e manda una domanda che usa l'orologio.
"""

import subprocess
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parent.parent
URL = "http://localhost:8001"


def compose(*argomenti, timeout=300):
    return subprocess.run(
        ["docker", "compose", *argomenti], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def test_compose_servizio_agente_con_orologio():
    if not (ROOT / ".env").is_file():
        pytest.skip("Serve un file .env valido per la prova Docker.")

    avvio = compose("up", "-d", "--build")
    assert avvio.returncode == 0, avvio.stdout + avvio.stderr
    try:
        for _ in range(120):
            try:
                if httpx.get(f"{URL}/stato", timeout=30).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            pytest.fail("servizio non pronto: " + compose("logs").stdout[-2000:])

        risposta = httpx.post(f"{URL}/conversazione", json={"domanda": "Che ore sono a Tokyo?"}, timeout=600)

        assert risposta.status_code == 200, risposta.text
        usati = risposta.json()["strumenti_usati"]
        assert any(s["nome"] == "orologio" for s in usati), risposta.json()
        assert not any(s["risultato"].startswith("Errore") for s in usati), usati  # ha risposto, non solo «è stato chiamato»
    finally:
        compose("down")
