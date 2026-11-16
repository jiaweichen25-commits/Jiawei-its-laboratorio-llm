"""Avvio della CLI: python -m assistente

Dalla lezione 6, step 6, la CLI è un CLIENT del servizio dell'agente. Il servizio va avviato
prima, in un altro terminale:

    .\\.venv\\Scripts\\python.exe -m uvicorn assistente.servizio_agente:app --port 8001

Sequenza:
  1. configurazione della CLI dal .env (AGENTE_URL, AGENTE_TIMEOUT, LOG_LEVEL);
  2. GET /stato: se il servizio, il server MCP o il modello non sono disponibili, messaggio ed uscita con codice 1;
  3. conversazione da terminale, una richiesta POST /conversazione per ogni domanda.

Avvio del server MCP, preferenze e grafo ora stanno nel servizio (assistente/agente.py).
"""

import logging
import os
import sys

from dotenv import load_dotenv

from assistente.cliente_agente import ClienteAgente, ErroreServizio
from assistente.config import ErroreConfigurazione, carica_configurazione_cli
from assistente.terminale import conversa


def configura_output() -> None:
    # Con l'output rediretto Windows usa cp1252, che non ha caratteri come «→».
    for flusso in (sys.stdout, sys.stderr):
        flusso.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    configura_output()
    load_dotenv(override=False)
    try:
        cfg = carica_configurazione_cli(os.environ)
    except ErroreConfigurazione as exc:
        print(exc, file=sys.stderr)
        return 1
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("assistente").setLevel(cfg.log_level)

    servizio = ClienteAgente(cfg.agente_url, timeout=cfg.agente_timeout)
    try:
        stato = servizio.stato()
    except ErroreServizio as exc:
        print(exc, file=sys.stderr)
        return 1
    problemi = {k: v for k, v in stato.items() if v != "ok"}
    if problemi:
        # Come nella lezione 4: se il modello non c'è, lo si dice subito invece che alla prima domanda.
        print("Il servizio agente non è pronto: " + "; ".join(f"{k}: {v}" for k, v in problemi.items()), file=sys.stderr)
        return 1

    conversa(servizio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
