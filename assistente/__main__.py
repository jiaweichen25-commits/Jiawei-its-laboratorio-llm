"""Avvio dell'assistente: python -m assistente"""

import logging
import os
import sys

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver

from assistente.config import ErroreConfigurazione, carica_configurazione, verifica_modello
from assistente.grafo import config_sessione, costruisci_grafo
from assistente.modello import crea_modello, descrivi_errore
from assistente.terminale import conversa


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

    grafo = costruisci_grafo(crea_modello(cfg), cfg.fuso_predefinito, checkpointer=InMemorySaver())
    conversa(grafo, config_sessione(), descrivi_errore=descrivi_errore)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
