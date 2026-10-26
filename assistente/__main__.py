"""Avvio dell'assistente: python -m assistente"""

from langgraph.checkpoint.memory import InMemorySaver

from assistente.grafo import config_sessione, costruisci_grafo
from assistente.terminale import conversa


def main() -> int:
    conversa(costruisci_grafo(InMemorySaver()), config_sessione())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
