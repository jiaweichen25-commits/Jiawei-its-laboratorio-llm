"""Lezione 6, step 8: controlli sul front-end fatti da Python.

  - il contratto: ogni percorso chiamato da api.js esiste nel documento OpenAPI del back-end (slide 15);
  - la configurazione: l'indirizzo del back-end sta solo in config.js (slide 15, punto 4);
  - i test JavaScript di api.js, eseguiti con Node se è installato.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.agente_http import AgenteHttp
from backend.app import crea_app
from backend.archivio import Archivio

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def percorsi_di_api_js() -> set[str]:
    testo = (FRONTEND / "api.js").read_text(encoding="utf-8")
    blocco = re.search(r"export const PERCORSI = \{(.*?)\};", testo, re.DOTALL).group(1)
    return set(re.findall(r'"(/[^"]*)"', blocco))


def test_i_percorsi_del_front_end_esistono_nell_openapi_del_back_end():
    archivio = Archivio("sqlite://")
    archivio.prepara()
    openapi = TestClient(crea_app(archivio=archivio, agente=AgenteHttp("http://agente.test"), cors_origini=())).get("/openapi.json").json()

    usati = percorsi_di_api_js()

    assert usati, "nessun percorso trovato in PERCORSI"
    assert usati <= set(openapi["paths"]), usati - set(openapi["paths"])


def test_api_js_non_costruisce_indirizzi_fuori_da_PERCORSI():
    testo = (FRONTEND / "api.js").read_text(encoding="utf-8")
    fuori = testo.replace(re.search(r"export const PERCORSI = \{.*?\};", testo, re.DOTALL).group(0), "")

    assert not re.findall(r"""["'`]/(chat|stato)""", fuori)


def test_l_indirizzo_del_back_end_sta_solo_in_config_js():
    con_indirizzo = [
        f.name for f in FRONTEND.iterdir()
        if f.suffix in (".js", ".html", ".css") and re.search(r"https?://", f.read_text(encoding="utf-8"))
    ]

    assert con_indirizzo == ["config.js"]
    assert "backendUrl" in (FRONTEND / "config.js").read_text(encoding="utf-8")


def test_la_pagina_carica_la_configurazione_prima_dell_applicazione():
    pagina = (FRONTEND / "index.html").read_text(encoding="utf-8")

    assert pagina.index('src="config.js"') < pagina.index('src="app.js"')
    assert 'lang="it"' in pagina


def test_il_testo_del_modello_non_viene_mai_inserito_come_html():
    # Una risposta del modello che contenesse tag non deve poter modificare la pagina.
    app_js = (FRONTEND / "app.js").read_text(encoding="utf-8")

    assert "innerHTML" not in app_js and "insertAdjacentHTML" not in app_js and "document.write" not in app_js


def test_javascript_di_api_js():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node non è installato: i test JavaScript non possono girare.")

    esito = subprocess.run([node, "--test"], cwd=FRONTEND, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)

    assert esito.returncode == 0, esito.stdout[-3000:] + esito.stderr[-1000:]
