"""Interfaccia da terminale: legge le domande e mostra le risposte in streaming."""

import logging
import sys

from langchain_core.messages import HumanMessage, RemoveMessage
from langgraph.errors import GraphRecursionError

log = logging.getLogger("assistente.terminale")


class _Uscita:
    """Scrive sull'output ricordando se la riga corrente è rimasta a metà."""

    def __init__(self, out):
        self.out = out
        self.a_meta_riga = False

    def testo(self, frammento: str) -> None:
        self.out.write(frammento)
        self.out.flush()
        self.a_meta_riga = not frammento.endswith("\n")

    def riga(self, testo: str) -> None:
        self.chiudi_riga()
        self.out.write(testo + "\n")
        self.out.flush()

    def chiudi_riga(self) -> None:
        if self.a_meta_riga:
            self.out.write("\n")
            self.a_meta_riga = False


def _id_messaggi(grafo, config) -> set[str]:
    return {m.id for m in grafo.get_state(config).values.get("messages", [])}


def _annulla_turno(grafo, config, id_prima: set[str]) -> None:
    """Toglie dalla cronologia i messaggi aggiunti da un turno fallito."""
    nuovi = [m.id for m in grafo.get_state(config).values.get("messages", []) if m.id not in id_prima]
    if nuovi:
        grafo.update_state(config, {"messages": [RemoveMessage(id=i) for i in nuovi]}, as_node="modello")


def _turno(grafo, config, domanda: str, uscita: _Uscita) -> None:
    for modo, dati in grafo.stream(
        {"messages": [HumanMessage(domanda)]}, config, stream_mode=["messages", "updates"]
    ):
        if modo == "messages":
            frammento, meta = dati
            if meta.get("langgraph_node") == "modello" and isinstance(frammento.content, str) and frammento.content:
                uscita.testo(frammento.content)
    uscita.chiudi_riga()


def conversa(grafo, config, leggi=input, out=sys.stdout, descrivi_errore=lambda exc: None) -> None:
    uscita = _Uscita(out)
    try:
        while True:
            try:
                domanda = leggi("Tu> ").strip()
            except EOFError:
                uscita.riga("")
                return
            if domanda.lower() == "esci":
                return
            if not domanda:
                continue

            id_prima = _id_messaggi(grafo, config)
            try:
                _turno(grafo, config, domanda, uscita)
            except GraphRecursionError:
                messaggio = "Troppi passaggi tra modello e strumenti: turno interrotto."
            except Exception as exc:
                messaggio = descrivi_errore(exc)
                if messaggio is None:
                    raise
            else:
                continue

            log.error("turno fallito: %s", messaggio)
            uscita.riga(messaggio)
            _annulla_turno(grafo, config, id_prima)
    except KeyboardInterrupt:
        uscita.riga("")
