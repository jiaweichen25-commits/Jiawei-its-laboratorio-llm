"""Interfaccia da terminale: legge le domande e mostra le risposte."""

import sys

from langchain_core.messages import HumanMessage


def conversa(grafo, config, leggi=input, out=sys.stdout) -> None:
    while True:
        try:
            domanda = leggi("Tu> ").strip()
        except (EOFError, KeyboardInterrupt):
            out.write("\n")
            return
        if domanda.lower() == "esci":
            return
        if not domanda:
            continue

        stato = grafo.invoke({"messages": [HumanMessage(domanda)]}, config)
        out.write(stato["messages"][-1].content + "\n")
