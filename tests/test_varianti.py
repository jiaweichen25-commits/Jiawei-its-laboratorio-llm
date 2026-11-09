"""Test della scelta della variante: il modello deve vedere UN SOLO orologio per volta (slide 17)."""

from datetime import datetime, timezone

import pytest

from assistente.client_mcp import ClienteMCP, crea_strumenti_mcp
from assistente.server_mcp import crea_server
from assistente.varianti import strumenti_per_variante

ISTANTE = datetime(2026, 10, 26, 15, 42, 10, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def strumenti_mcp():
    with ClienteMCP(crea_server(lambda: ISTANTE)) as cliente:
        yield crea_strumenti_mcp(cliente)


@pytest.mark.parametrize("variante", ["locale", "fastapi", "mcp"])
def test_un_solo_orologio_della_variante_scelta(strumenti_mcp, variante):
    strumenti = strumenti_per_variante(variante, strumenti_mcp, "http://localhost:8000")

    orologi = [s for s in strumenti if s.name == "orologio"]
    assert len(orologi) == 1
    assert orologi[0].metadata["variante"] == variante


@pytest.mark.parametrize("variante", ["locale", "fastapi", "mcp"])
def test_calcola_e_converti_sempre_da_mcp(strumenti_mcp, variante):
    strumenti = {s.name: s for s in strumenti_per_variante(variante, strumenti_mcp, "http://localhost:8000")}

    assert set(strumenti) == {"orologio", "calcola", "converti"}
    assert strumenti["calcola"].metadata["variante"] == "mcp"
    assert strumenti["converti"].metadata["variante"] == "mcp"


def test_variante_sconosciuta(strumenti_mcp):
    with pytest.raises(ValueError, match="sole"):
        strumenti_per_variante("sole", strumenti_mcp, "http://localhost:8000")
