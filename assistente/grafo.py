"""Grafo LangGraph dell'assistente: stato, nodi e instradamento.

    START → modello ─instrada()─┬─ "strumenti" → strumenti → modello
                                └─ END
"""

import logging
import time
from collections.abc import Sequence
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import ValidationError

LIMITE_PASSAGGI = 10

log = logging.getLogger("assistente.grafo")


def config_sessione() -> dict:
    """Configurazione di esecuzione: un solo thread per la sessione e limite ai passaggi."""
    return {"configurable": {"thread_id": "sessione"}, "recursion_limit": LIMITE_PASSAGGI}


def messaggio_sistema(fuso: str) -> SystemMessage:
    return SystemMessage(
        "Rispondi in italiano. Per conoscere data o ora usa sempre lo strumento `orologio`, "
        f"senza inventarle. Se l'utente non indica un fuso orario, usa `{fuso}`. "
        # Lezione 5: i due tool MCP aggiunti (slide 25). Senza questa frase un modello piccolo
        # tende a fare i conti «a mente» invece di chiamare lo strumento.
        "Per i calcoli usa sempre lo strumento `calcola` e per le conversioni di unità lo "
        "strumento `converti`, senza fare i conti a mente. Se uno strumento restituisce un "
        "errore, riferiscilo all'utente senza inventare un risultato."
    )


def instrada(state: MessagesState) -> Literal["strumenti", "__end__"]:
    """Va al nodo strumenti se il modello ha richiesto uno strumento, altrimenti termina."""
    # La cronologia può essere vuota dopo l'annullamento di un turno fallito.
    messaggi = state["messages"]
    return "strumenti" if messaggi and getattr(messaggi[-1], "tool_calls", None) else END


def costruisci_grafo(
    modello: BaseChatModel,
    fuso_predefinito: str,
    strumenti: Sequence[BaseTool] = (),
    checkpointer=None,
):
    llm = modello.bind_tools(list(strumenti)) if strumenti else modello
    per_nome = {s.name: s for s in strumenti}

    def nodo_modello(state: MessagesState) -> dict:
        # Il messaggio di sistema si ricostruisce a ogni chiamata e non entra nello stato.
        log.info("modello: inizio chiamata")
        inizio = time.perf_counter()
        risposta = llm.invoke([messaggio_sistema(fuso_predefinito), *state["messages"]])
        log.info(
            "modello: fine chiamata (%.1f s, tool_calls=%d)",
            time.perf_counter() - inizio,
            len(getattr(risposta, "tool_calls", [])),
        )
        return {"messages": [risposta]}

    def nodo_strumenti(state: MessagesState) -> dict:
        # Gli errori diventano risultati per il modello: il grafo non si interrompe.
        risultati = []
        for chiamata in state["messages"][-1].tool_calls:
            nome, args, call_id = chiamata["name"], chiamata["args"], chiamata["id"]
            strumento = per_nome.get(nome)
            # Lezione 5: la variante (locale / fastapi / mcp) viene dai metadata del tool e il
            # call_id permette di seguire la richiesta fino al ToolMessage (traccia della slide 23).
            variante = (strumento.metadata or {}).get("variante", "?") if strumento else "?"
            log.info("strumenti: richiesta %s variante=%s call_id=%s argomenti=%s", nome, variante, call_id, args)
            if strumento is None:
                contenuto = f"Errore: strumento sconosciuto: «{nome}»"
            else:
                try:
                    contenuto = str(strumento.invoke(args))
                except ValidationError as exc:
                    contenuto = f"Errore: argomenti non validi per {nome}: {exc}"
                except Exception as exc:
                    contenuto = f"Errore: esecuzione di {nome} fallita: {exc}"
            # «Errore...» copre sia l'errore dello strumento sia quello di collegamento: mai un falso «ok».
            esito = "errore" if contenuto.startswith("Errore") else "ok"
            log.info("strumenti: risultato %s variante=%s call_id=%s esito=%s → %s",
                     nome, variante, call_id, esito, contenuto)
            # tool_call_id collega il risultato alla richiesta del modello (slide 12).
            risultati.append(ToolMessage(contenuto, tool_call_id=call_id, name=nome))
        return {"messages": risultati}

    grafo = StateGraph(MessagesState)
    grafo.add_node("modello", nodo_modello)
    grafo.add_node("strumenti", nodo_strumenti)
    grafo.add_edge(START, "modello")
    grafo.add_conditional_edges("modello", instrada, ["strumenti", END])
    grafo.add_edge("strumenti", "modello")
    return grafo.compile(checkpointer=checkpointer)
