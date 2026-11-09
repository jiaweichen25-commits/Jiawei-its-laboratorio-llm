"""Avvio dell'assistente: python -m assistente

Sequenza (lezione 5):
  1. configurazione da .env e controllo del modello in LM Studio (come nella lezione 4);
  2. avvio del server MCP come sottoprocesso stdio e DISCOVERY del catalogo (tools/list);
  3. ADATTAMENTO del catalogo in tool LangChain e scelta della variante dell'orologio;
  4. costruzione del grafo (bind_tools) e conversazione da terminale;
  5. alla fine, chiusura della sessione MCP (il sottoprocesso termina).
"""

import logging
import os
import sys

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver

from assistente.client_mcp import ClienteMCP, ErroreCollegamentoMCP, crea_strumenti_mcp, trasporto_stdio
from assistente.config import ErroreConfigurazione, carica_configurazione, verifica_modello
from assistente.grafo import config_sessione, costruisci_grafo
from assistente.modello import crea_modello, descrivi_errore
from assistente.terminale import conversa
from assistente.varianti import strumenti_per_variante

log = logging.getLogger("assistente.avvio")


def configura_output() -> None:
    # Con l'output rediretto Windows usa cp1252, che non ha caratteri come «→».
    for flusso in (sys.stdout, sys.stderr):
        flusso.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    configura_output()
    load_dotenv(override=False)
    try:
        cfg = carica_configurazione(os.environ)
        # Le librerie restano su WARNING; LOG_LEVEL vale solo per i log dell'applicazione.
        logging.basicConfig(
            level=logging.WARNING,
            stream=sys.stderr,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        logging.getLogger("assistente").setLevel(cfg.log_level)
        verifica_modello(cfg)
    except ErroreConfigurazione as exc:
        print(exc, file=sys.stderr)
        return 1

    # Il client MCP resta aperto per tutta la sessione: un solo sottoprocesso server.
    cliente = ClienteMCP(trasporto_stdio())
    try:
        cliente.avvia()
    except ErroreCollegamentoMCP as exc:
        # Slide 24, «processo non avviato»: si segnala subito, prima di parlare col modello.
        print(f"Errore di collegamento al server MCP: {exc}", file=sys.stderr)
        return 1

    try:
        strumenti = strumenti_per_variante(cfg.variante, crea_strumenti_mcp(cliente), cfg.orologio_api_url)
        log.info("variante orologio=%s, strumenti=%s", cfg.variante, [s.name for s in strumenti])
        grafo = costruisci_grafo(
            crea_modello(cfg),
            cfg.fuso_predefinito,
            strumenti=strumenti,
            checkpointer=InMemorySaver(),
        )
        conversa(grafo, config_sessione(), descrivi_errore=descrivi_errore)
    finally:
        cliente.chiudi()  # anche in caso di errore o Ctrl+C: il server MCP non resta acceso
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
