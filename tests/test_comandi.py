"""Lezione 6, step 5: interpretazione e controllo dei comandi /prompts e /prompt (logica pura)."""

import pytest
from mcp.types import Prompt, PromptArgument

from assistente.comandi import ErroreComando, formatta_elenco, interpreta_prompt, valida_argomenti

SPIEGA = Prompt(
    name="spiega",
    description="Spiega un argomento al livello richiesto.",
    arguments=[
        PromptArgument(name="argomento", description="concetto da spiegare", required=True),
        PromptArgument(name="livello", description="base, intermedio o avanzato", required=False),
    ],
)
RIASSUMI = Prompt(name="riassumi_conversazione", description="Riassume la sessione.", arguments=[
    PromptArgument(name="stile", description="sintetico o dettagliato", required=False),
])


# ---------------------------------------------------------------- interpreta_prompt

def test_interpreta_con_virgolette():
    assert interpreta_prompt('/prompt spiega argomento="Model Context Protocol" livello=base') == (
        "spiega", {"argomento": "Model Context Protocol", "livello": "base"},
    )


def test_interpreta_senza_argomenti():
    assert interpreta_prompt("/prompt riassumi_conversazione") == ("riassumi_conversazione", {})


@pytest.mark.parametrize("riga, messaggio", [
    ("/prompt", "nome del prompt"),
    ('/prompt spiega argomento="MCP', "(?i)virgolette"),
    ("/prompt spiega argomento=Model Context", "chiave=valore"),
    ("/prompt spiega =base", "chiave=valore"),
    ("/prompt spiega livello=base livello=avanzato", "ripetuto"),
])
def test_interpreta_errori(riga, messaggio):
    with pytest.raises(ErroreComando, match=messaggio):
        interpreta_prompt(riga)


# ---------------------------------------------------------------- valida_argomenti

def test_argomenti_validi():
    valida_argomenti(SPIEGA, {"argomento": "MCP"})
    valida_argomenti(SPIEGA, {"argomento": "MCP", "livello": "base"})


def test_obbligatorio_mancante():
    with pytest.raises(ErroreComando, match="argomento"):
        valida_argomenti(SPIEGA, {"livello": "base"})


def test_argomento_sconosciuto():
    # FastMCP lo accetterebbe in silenzio: il controllo spetta all'host (slide 10, punto 4).
    with pytest.raises(ErroreComando, match="colore"):
        valida_argomenti(SPIEGA, {"argomento": "MCP", "colore": "blu"})


def test_prompt_senza_argomenti_dichiarati():
    with pytest.raises(ErroreComando, match="x"):
        valida_argomenti(Prompt(name="vuoto", arguments=None), {"x": "1"})


# ---------------------------------------------------------------- formatta_elenco

def test_formatta_elenco():
    testo = formatta_elenco([SPIEGA, RIASSUMI])

    assert "spiega" in testo and "Spiega un argomento al livello richiesto." in testo
    assert "argomento (obbligatorio): concetto da spiegare" in testo
    assert "livello (facoltativo): base, intermedio o avanzato" in testo
    assert "riassumi_conversazione" in testo
    assert '/prompt spiega argomento="..."' in testo  # esempio d'uso con gli obbligatori


def test_formatta_elenco_vuoto():
    assert "nessun prompt" in formatta_elenco([]).lower()
