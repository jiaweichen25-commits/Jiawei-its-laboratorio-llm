from datetime import datetime, timezone

import pytest

from assistente.strumenti import crea_orologio

ISTANTE = datetime(2026, 10, 26, 15, 42, 10, tzinfo=timezone.utc)


@pytest.fixture
def orologio():
    return crea_orologio(lambda: ISTANTE)


def test_nome_e_parametro(orologio):
    assert orologio.name == "orologio"
    assert list(orologio.args) == ["fuso"]


@pytest.mark.parametrize("fuso, atteso", [
    ("Asia/Tokyo", "2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì"),
    ("Europe/Rome", "2026-10-26T16:42:10+01:00 (Europe/Rome), lunedì"),  # dopo il cambio del 25/10
    ("UTC", "2026-10-26T15:42:10+00:00 (UTC), lunedì"),
])
def test_ora_nel_fuso(orologio, fuso, atteso):
    assert orologio.invoke({"fuso": fuso}) == atteso


def test_ora_legale_estiva():
    estate = crea_orologio(lambda: datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc))

    assert estate.invoke({"fuso": "Europe/Rome"}) == "2026-07-15T12:00:00+02:00 (Europe/Rome), mercoledì"


@pytest.mark.parametrize("fuso", ["Marte/Base", "../etc"])
def test_fuso_sconosciuto(orologio, fuso):
    assert orologio.invoke({"fuso": fuso}) == f"Errore: fuso orario sconosciuto: «{fuso}»"


def test_schema_descrive_il_fuso_iana(orologio):
    proprieta = orologio.tool_call_schema.model_json_schema()["properties"]["fuso"]

    assert "IANA" in proprieta["description"]
    assert "Europe/Rome" in proprieta["description"]
