"""Prove reali della pipeline RAG (lezione 7): pytest -m qdrant

Servono Qdrant acceso (docker compose up -d qdrant), LM Studio con il modello di embedding
caricato, dati/artusi.txt e il file .env. Usano una collezione di prova, cancellata alla fine,
così non toccano la collezione «ricette» del laboratorio.
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from qdrant_client import QdrantClient

from rag.config import carica_configurazione
from rag.ingestion import esegui
from rag.ricerca import cerca

pytestmark = pytest.mark.qdrant

ROOT = Path(__file__).resolve().parent.parent
COLLEZIONE = "ricette_prova_automatica"


@pytest.fixture(scope="module")
def cfg():
    load_dotenv(ROOT / ".env", override=False)
    configurazione = carica_configurazione({**os.environ, "QDRANT_COLLEZIONE": COLLEZIONE})
    if not configurazione.corpus_file.is_file():
        pytest.skip("Serve dati/artusi.txt.")
    client = QdrantClient(url=configurazione.qdrant_url)
    if client.collection_exists(COLLEZIONE):
        client.delete_collection(COLLEZIONE)
    yield configurazione
    client.delete_collection(COLLEZIONE)


def test_due_ingestion_reali_stesso_numero_di_punti_e_ricerca_filtrata(cfg):
    prima = esegui(cfg)
    seconda = esegui(cfg)

    assert prima["ricette"] == 790
    assert prima["punti_prima"] == 0 and prima["punti_dopo"] == prima["chunk"]
    assert seconda["punti_prima"] == seconda["punti_dopo"] == prima["punti_dopo"] and seconda["rimossi"] == 0

    risultati = cerca(cfg, "Come si frigge il pollo?", k=3, capitolo="Fritti")
    assert len(risultati) == 3 and {r.capitolo for r in risultati} == {"Fritti"}

    gnocchi = cerca(cfg, "Quanta farina serve per 400 grammi di patate negli gnocchi?", k=5)
    assert 89 in [r.numero for r in gnocchi]
