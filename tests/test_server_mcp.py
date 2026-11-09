"""Test del server FastMCP indipendenti dal modello (slide 29, punto 05).

fastmcp.Client(server) collega client e server IN MEMORIA: stesso protocollo MCP
(tools/list, tools/call), ma senza avviare un sottoprocesso.
"""

import asyncio
from datetime import datetime, timezone

from fastmcp import Client

from assistente.server_mcp import crea_server

ISTANTE = datetime(2026, 10, 26, 15, 42, 10, tzinfo=timezone.utc)


def esegui(coroutine_factory):
    """Apre una sessione MCP in memoria ed esegue la funzione asincrona passata."""
    async def principale():
        async with Client(crea_server(lambda: ISTANTE)) as client:
            return await coroutine_factory(client)
    return asyncio.run(principale())


def test_discovery_elenca_tre_tool():
    strumenti = esegui(lambda c: c.list_tools())

    assert {s.name for s in strumenti} == {"orologio", "calcola", "converti"}
    assert all(s.description for s in strumenti)


def test_schema_converti_con_elenco_chiuso_di_unita():
    strumenti = esegui(lambda c: c.list_tools())
    schema = next(s for s in strumenti if s.name == "converti").input_schema

    assert schema["required"] == ["valore", "da", "a"]
    assert "km" in schema["properties"]["da"]["enum"]
    assert "parsec" not in schema["properties"]["a"]["enum"]
    assert schema["properties"]["valore"]["type"] == "number"


def test_schema_orologio_descrive_il_fuso():
    strumenti = esegui(lambda c: c.list_tools())
    schema = next(s for s in strumenti if s.name == "orologio").input_schema

    assert "IANA" in schema["properties"]["fuso"]["description"]


def test_invocazione_diretta_orologio():
    risultato = esegui(lambda c: c.call_tool("orologio", {"fuso": "Asia/Tokyo"}))

    assert not risultato.is_error
    assert risultato.content[0].text == "2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì"


def test_orologio_fuso_non_valido_e_errore_mcp():
    risultato = esegui(lambda c: c.call_tool("orologio", {"fuso": "Mars/Olympus"}, raise_on_error=False))

    assert risultato.is_error
    assert "«Mars/Olympus»" in risultato.content[0].text


def test_calcola_e_converti():
    calcolo = esegui(lambda c: c.call_tool("calcola", {"espressione": "(2+3)*4"}))
    conversione = esegui(lambda c: c.call_tool("converti", {"valore": 10, "da": "km", "a": "mi"}))

    assert calcolo.content[0].text == "(2+3)*4 = 20"
    assert conversione.content[0].text == "10 km = 6.21371 mi"


def test_calcola_rifiuta_codice():
    risultato = esegui(lambda c: c.call_tool("calcola", {"espressione": "__import__('os')"}, raise_on_error=False))

    assert risultato.is_error
    assert "non consentita" in risultato.content[0].text


def test_converti_valore_non_numerico_rifiutato_dallo_schema():
    risultato = esegui(lambda c: c.call_tool(
        "converti", {"valore": "dieci", "da": "km", "a": "mi"}, raise_on_error=False
    ))

    assert risultato.is_error


def test_converti_unita_fuori_elenco_rifiutata_dallo_schema():
    risultato = esegui(lambda c: c.call_tool(
        "converti", {"valore": 1, "da": "parsec", "a": "m"}, raise_on_error=False
    ))

    assert risultato.is_error
