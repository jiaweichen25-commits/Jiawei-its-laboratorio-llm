"""Grafo LangGraph dell'assistente: stato, nodi e instradamento.

Senza opzioni è il grafo delle lezioni 4 e 5:

    START → modello ─instrada()─┬─ "strumenti" → strumenti → modello
                                └─ END

La lezione 6 aggiunge nodi che si accendono con `OpzioniGrafo` (un nodo spento non esiste nel grafo):

    START → router ─instrada_router()─┬─ "conversazione" → modello ⇄ strumenti
                                      │                        │ (nessuno strumento richiesto)
                                      │                        ▼
                                      │                     revisore ─instrada_revisore()─┬─ END
                                      │                                                   └─ modello
                                      └─ "fuori_ambito" → rifiuto → END
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import ValidationError

from assistente.controllo import (
    DecisioneRouter,
    EsitoRevisione,
    chiedi_strutturato,
    e_revisione,
    indicazione_revisione,
    messaggi_revisore,
    messaggi_router,
)

# Lezione 6: da 10 a 16, perché anche router, revisore e riassunto consumano passaggi del grafo.
LIMITE_PASSAGGI = 16

log = logging.getLogger("assistente.grafo")


class StatoAgente(MessagesState):
    """Stato del grafo: la cronologia (`messages`, da MessagesState) più i campi della lezione 6.

    I campi nuovi non hanno un «reducer»: ogni scrittura SOSTITUISCE il valore precedente,
    mentre `messages` accumula. Possono mancare nello stato: si leggono con `.get`.
    """

    riassunto: str   # step 3: riassunto dei messaggi tolti dalla cronologia
    revisioni: int   # step 2: quante volte il revisore ha rimandato la risposta in questo turno
    categoria: str   # step 1: decisione del router, letta dall'arco condizionale


@dataclass(frozen=True)
class OpzioniGrafo:
    """Quali nodi della lezione 6 accendere. I valori arrivano dalla configurazione (.env)."""

    ambito: str | None = None          # None → nessun router
    limite_revisioni: int = 0          # 0 → nessun revisore
    soglia_riassunto: int = 0          # 0 → nessun riassunto
    messaggi_da_conservare: int = 6


def risposta_rifiuto(ambito: str) -> str:
    """Risposta fissa del nodo rifiuto: non serve il modello per dire di no."""
    return f"Questa richiesta è fuori dal mio ambito. Posso aiutarti con: {ambito}"


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


def instrada(state: StatoAgente) -> Literal["strumenti", "__end__"]:
    """Va al nodo strumenti se il modello ha richiesto uno strumento, altrimenti termina."""
    # La cronologia può essere vuota dopo l'annullamento di un turno fallito.
    messaggi = state["messages"]
    return "strumenti" if messaggi and getattr(messaggi[-1], "tool_calls", None) else END


def instrada_router(state: StatoAgente) -> Literal["conversazione", "fuori_ambito"]:
    """Arco condizionale dopo il router (slide 4, punto 3): legge la decisione dallo stato."""
    return "fuori_ambito" if state.get("categoria") == "fuori_ambito" else "conversazione"


def instrada_revisore(state: StatoAgente) -> Literal["modello", "__end__"]:
    """Dopo il revisore: se ha lasciato un'indicazione si torna all'agente, altrimenti il turno finisce."""
    messaggi = state["messages"]
    return "modello" if messaggi and e_revisione(messaggi[-1]) else END


def costruisci_grafo(
    modello: BaseChatModel,
    fuso_predefinito: str,
    strumenti: Sequence[BaseTool] = (),
    checkpointer=None,
    opzioni: OpzioniGrafo = OpzioniGrafo(),
):
    llm = modello.bind_tools(list(strumenti)) if strumenti else modello
    per_nome = {s.name: s for s in strumenti}

    def nodo_router(state: StatoAgente) -> dict:
        # Usa `modello` e non `llm`: il router non riceve gli strumenti, perché non spetta a lui
        # decidere se servono (slide 4, punto 4). La sua risposta non entra nella cronologia.
        decisione = chiedi_strutturato(
            modello,
            DecisioneRouter,
            messaggi_router(opzioni.ambito, state.get("riassunto", ""), state["messages"]),
        )
        if decisione is None:
            # Meglio una domanda fuori ambito che passa, che un utente bloccato da un output illeggibile.
            log.warning("router: decisione non leggibile, la domanda passa all'agente")
            return {"categoria": "conversazione"}
        log.info("router: categoria=%s motivo=%s", decisione.categoria, decisione.motivo)
        return {"categoria": decisione.categoria}

    def nodo_rifiuto(state: StatoAgente) -> dict:
        log.info("rifiuto: richiesta fuori ambito, il nodo modello non viene eseguito")
        return {"messages": [AIMessage(risposta_rifiuto(opzioni.ambito))]}

    def nodo_revisore(state: StatoAgente) -> dict:
        esito = chiedi_strutturato(modello, EsitoRevisione, messaggi_revisore(state["messages"]))
        if esito is None:
            log.warning("revisore: giudizio non leggibile, la risposta viene accettata")
            return {}
        if esito.coerente:
            log.info("revisore: coerente motivo=%s", esito.motivo)
            return {}
        fatte = state.get("revisioni", 0)
        if fatte >= opzioni.limite_revisioni:
            # Il limite sta nello stato (slide 5, punto 4): senza, un revisore severo non si fermerebbe mai.
            log.warning(
                "revisore: limite di revisioni raggiunto (%d), resta l'ultima risposta. motivo=%s",
                opzioni.limite_revisioni, esito.motivo,
            )
            return {}
        log.info(
            "revisore: non coerente (revisione %d di %d) motivo=%s",
            fatte + 1, opzioni.limite_revisioni, esito.motivo,
        )
        # Il motivo entra in cronologia: alla prossima chiamata l'agente lo legge e riscrive.
        return {"messages": [indicazione_revisione(esito.motivo)], "revisioni": fatte + 1}

    def nodo_modello(state: StatoAgente) -> dict:
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

    def nodo_strumenti(state: StatoAgente) -> dict:
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

    grafo = StateGraph(StatoAgente)
    grafo.add_node("modello", nodo_modello)
    grafo.add_node("strumenti", nodo_strumenti)

    # Il primo nodo del turno dipende da che cosa è acceso: senza opzioni resta `modello`.
    ingresso = "modello"
    if opzioni.ambito:
        grafo.add_node("router", nodo_router)
        grafo.add_node("rifiuto", nodo_rifiuto)
        grafo.add_conditional_edges(
            "router", instrada_router, {"conversazione": "modello", "fuori_ambito": "rifiuto"}
        )
        grafo.add_edge("rifiuto", END)
        ingresso = "router"

    grafo.add_edge(START, ingresso)
    # Quando l'agente non chiede strumenti, `instrada` dice END: con il revisore acceso quel
    # ramo porta al revisore, che decide se il turno finisce davvero.
    dopo_modello = END
    if opzioni.limite_revisioni > 0:
        grafo.add_node("revisore", nodo_revisore)
        grafo.add_conditional_edges("revisore", instrada_revisore, ["modello", END])
        dopo_modello = "revisore"
    grafo.add_conditional_edges("modello", instrada, {"strumenti": "strumenti", END: dopo_modello})
    grafo.add_edge("strumenti", "modello")
    return grafo.compile(checkpointer=checkpointer)
