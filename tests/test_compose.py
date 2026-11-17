"""Lezione 6, step 9: controlli sulla struttura di compose.yaml e dei file Docker, senza avviare Docker.

Le richieste della slide 16 diventano controlli: quattro servizi, tre con il proprio Dockerfile,
agente non esposto, back-end che aspetta il database, credenziali fuori dal file.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
SERVIZI = COMPOSE["services"]


def test_quattro_servizi_tre_con_il_proprio_dockerfile():
    # Lezione 7: in più c'è Qdrant, il database vettoriale della pipeline RAG.
    assert set(SERVIZI) == {"frontend", "backend", "agente", "postgres", "qdrant"}

    dockerfile = {nome: s["build"].get("dockerfile", "Dockerfile") for nome, s in SERVIZI.items() if "build" in s}

    assert dockerfile == {"frontend": "frontend/Dockerfile", "backend": "backend/Dockerfile", "agente": "Dockerfile"}
    assert all((ROOT / percorso).is_file() for percorso in dockerfile.values())
    assert SERVIZI["postgres"]["image"].startswith("postgres:")  # immagine ufficiale


def test_solo_il_front_end_e_raggiungibile_dalla_rete():
    assert "ports" not in SERVIZI["agente"]   # slide 16: l'agente non è esposto
    assert "ports" not in SERVIZI["backend"]  # le chiamate API passano dal proxy del front-end
    assert len(SERVIZI["frontend"]["ports"]) == 1 and SERVIZI["frontend"]["ports"][0].endswith(":80")
    # PostgreSQL è pubblicato solo sull'interfaccia locale del computer, per lo sviluppo.
    assert all(str(porta).startswith("127.0.0.1:") for porta in SERVIZI["postgres"]["ports"])


def test_il_back_end_parte_a_database_pronto():
    dipendenze = SERVIZI["backend"]["depends_on"]

    assert dipendenze["postgres"] == {"condition": "service_healthy"}
    assert "healthcheck" in SERVIZI["postgres"]
    assert "agente" in dipendenze


def test_volume_per_i_dati_di_postgres():
    assert any(str(v).startswith("dati_postgres:") for v in SERVIZI["postgres"]["volumes"])
    assert "dati_postgres" in COMPOSE["volumes"]


def test_nessuna_credenziale_scritta_nel_file():
    testo = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    # Le credenziali compaiono solo come ${VARIABILE}, lette dal file .env escluso da Git.
    assert "${POSTGRES_PASSWORD}" in testo
    assert not re.search(r"POSTGRES_PASSWORD:\s*[^$\s]", testo)
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()


def test_indirizzi_interni_tra_i_servizi():
    ambiente_backend = SERVIZI["backend"]["environment"]
    ambiente_agente = SERVIZI["agente"]["environment"]

    assert "@postgres:5432/" in ambiente_backend["DATABASE_URL"]       # il nome del servizio, non localhost
    assert ambiente_backend["AGENTE_URL"] == "http://agente:8001"
    assert ambiente_agente["LM_BASE_URL"] == "http://host.docker.internal:1234/v1"  # LM Studio resta sul computer
    assert ambiente_agente["VARIANTE_OROLOGIO"] == "mcp"
    assert any("host.docker.internal" in voce for voce in SERVIZI["agente"]["extra_hosts"])


def test_proxy_adatto_allo_streaming():
    nginx = (ROOT / "frontend" / "docker" / "nginx.conf").read_text(encoding="utf-8")

    assert "location /api/" in nginx and "proxy_pass http://backend:8002/;" in nginx
    assert "proxy_buffering off;" in nginx  # gli eventi SSE passano subito, non a blocchi
    secondi = int(re.search(r"proxy_read_timeout (\d+)s;", nginx).group(1))
    assert secondi >= 600  # tra un evento e l'altro passano anche decine di secondi


def test_il_front_end_nel_container_usa_il_proxy():
    config = (ROOT / "frontend" / "docker" / "config.js").read_text(encoding="utf-8")
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")

    assert 'backendUrl: "/api"' in config
    assert "docker/config.js" in dockerfile and "docker/nginx.conf" in dockerfile


def test_qdrant_versione_fissa_volume_e_solo_dal_computer():
    # Lezione 7, slide 16 e 19: servizio di Docker Compose, porta 6333, volume persistente.
    qdrant = SERVIZI["qdrant"]

    assert qdrant["image"] == "qdrant/qdrant:v1.20.2"
    assert qdrant["ports"] == ["127.0.0.1:6333:6333"]
    assert "dati_qdrant:/qdrant/storage" in qdrant["volumes"] and "dati_qdrant" in COMPOSE["volumes"]


def test_il_back_end_non_porta_con_se_l_agente():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")

    assert "backend/requirements.txt" in dockerfile and "COPY backend/" in dockerfile
    assert "assistente" not in dockerfile
