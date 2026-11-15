"""Lezione 6: logica dei nodi di controllo del grafo (router, revisore, riassunto).

Qui non c'è LangGraph: solo funzioni che preparano i messaggi per il modello e ne leggono
la risposta. Il collegamento tra i nodi (chi viene dopo chi) resta in `grafo.py`.

Lo stesso modello dell'agente viene chiamato con prompt di sistema diversi (slide 3):
qui il modello non conversa con l'utente, ma prende una decisione su un testo.
"""

import logging
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ValidationError

log = logging.getLogger("assistente.controllo")

# Con questo prefisso il revisore rimanda una risposta all'agente (step 2). È un messaggio
# di tipo «utente» ma non l'ha scritto l'utente: va riconosciuto per non scambiarlo per una domanda.
PREFISSO_REVISIONE = "[Revisione]"


# ---------------------------------------------------------------- output strutturato

class DecisioneRouter(BaseModel):
    """Output strutturato del router (slide 4): categoria e motivo."""

    categoria: Literal["conversazione", "fuori_ambito"]
    motivo: str


def chiedi_strutturato(modello: BaseChatModel, schema: type[BaseModel], messaggi: list) -> BaseModel | None:
    """Chiama il modello chiedendo una risposta nella forma di `schema`. None se non è valida.

    `response_format` dice a LM Studio di vincolare la generazione allo schema JSON: anche un
    modello piccolo produce così un JSON ben formato. La validazione con Pydantic resta, perché
    il vincolo dipende dal server e non va dato per scontato.
    Gli errori di collegamento non sono catturati: il turno fallisce come per l'agente.
    """
    vincolato = modello.bind(response_format={
        "type": "json_schema",
        "json_schema": {"name": schema.__name__, "strict": True, "schema": schema.model_json_schema()},
    })
    testo = vincolato.invoke(messaggi).content
    try:
        return schema.model_validate_json(testo)
    except ValidationError:
        log.warning("%s: output non valido, ignorato: %r", schema.__name__, testo)
        return None


# ---------------------------------------------------------------- trascrizione

def e_revisione(messaggio) -> bool:
    """Vero per l'indicazione che il revisore ha messo in cronologia (non è una domanda dell'utente)."""
    return (
        isinstance(messaggio, HumanMessage)
        and isinstance(messaggio.content, str)
        and messaggio.content.startswith(PREFISSO_REVISIONE)
    )


def trascrivi(messaggi) -> str:
    """Cronologia come testo semplice, una riga per messaggio.

    Ai nodi di controllo la conversazione arriva come testo dentro un solo messaggio: se
    ricevessero i messaggi veri, un ToolMessage senza la sua richiesta farebbe fallire il modello.
    """
    righe = []
    for m in messaggi:
        if isinstance(m, ToolMessage):
            righe.append(f"Strumento {m.name}: {m.content}")
        elif isinstance(m, HumanMessage):
            righe.append(f"Utente: {m.content}")
        elif isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip():
            righe.append(f"Assistente: {m.content}")
        # Un AIMessage senza testo è solo una richiesta di strumento: non aggiunge nulla da leggere.
    return "\n".join(righe)


# ---------------------------------------------------------------- router (step 1)

ISTRUZIONI_ROUTER = (
    "Sei il router di un assistente. Devi solo decidere se l'ULTIMA richiesta dell'utente rientra "
    "nell'ambito dell'assistente. Non rispondere alla richiesta.\n"
    "Ambito dell'assistente: {ambito}\n"
    "Rispondi `conversazione` se la richiesta rientra nell'ambito, anche in parte, oppure se è un "
    "seguito degli scambi precedenti. Rispondi `fuori_ambito` solo se non c'entra nulla con l'ambito. "
    "Nel dubbio scegli `conversazione`. Scrivi il motivo in una frase, in italiano."
)


def messaggi_router(ambito: str, riassunto: str, messaggi: list) -> list:
    """Messaggi per il router: l'ambito nel sistema, gli ultimi scambi come testo.

    Gli ultimi quattro messaggi servono per i seguiti («e a Tokyo?»), che da soli non si capiscono.
    Restano fuori i risultati degli strumenti e le indicazioni del revisore: il router non valuta
    gli strumenti (slide 4, punto 4).
    """
    scambi = [
        m for m in messaggi
        if (isinstance(m, HumanMessage) and not e_revisione(m))
        or (isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip())
    ][-4:]
    parti = []
    if riassunto:
        parti.append(f"Riassunto della conversazione precedente: {riassunto}")
    parti.append("Ultimi scambi (la richiesta da valutare è l'ultima riga):\n" + trascrivi(scambi))
    return [SystemMessage(ISTRUZIONI_ROUTER.format(ambito=ambito)), HumanMessage("\n\n".join(parti))]


# ---------------------------------------------------------------- revisore (step 2)

class EsitoRevisione(BaseModel):
    """Output strutturato del revisore (slide 5): coerente sì o no, e motivo."""

    coerente: bool
    motivo: str


ISTRUZIONI_REVISORE = (
    "Sei il revisore di un assistente. Ricevi la domanda dell'utente, gli eventuali risultati degli "
    "strumenti e la risposta proposta. Controlla solo la COERENZA: la risposta deve affrontare tutte "
    "le parti della domanda e non deviare dal tema.\n"
    "Non verificare se i fatti sono veri: i risultati degli strumenti sono già corretti. Una parte "
    "è affrontata anche quando la risposta riferisce che uno strumento ha dato errore.\n"
    "Se la risposta è coerente rispondi `coerente: true`. Altrimenti `coerente: false` e nel motivo "
    "scrivi in una frase, in italiano, che cosa manca o che cosa è fuori tema."
)


def messaggi_revisore(messaggi: list) -> list:
    """Messaggi per il revisore: la domanda, i risultati degli strumenti del turno, la risposta proposta.

    La domanda è l'ultimo messaggio scritto davvero dall'utente: le indicazioni del revisore
    sono anch'esse HumanMessage, ma non sono domande. La risposta da valutare è sempre l'ultimo
    messaggio, quindi dopo una bocciatura si valuta la risposta nuova e non la bozza scartata.
    """
    posizioni = [i for i, m in enumerate(messaggi) if isinstance(m, HumanMessage) and not e_revisione(m)]
    inizio = posizioni[-1] if posizioni else 0
    domanda = messaggi[inizio].content if posizioni else ""
    risultati = [m for m in messaggi[inizio:] if isinstance(m, ToolMessage)]
    parti = [f"Domanda dell'utente:\n{domanda}"]
    if risultati:
        parti.append("Risultati degli strumenti:\n" + trascrivi(risultati))
    parti.append(f"Risposta proposta:\n{messaggi[-1].content}")
    return [SystemMessage(ISTRUZIONI_REVISORE), HumanMessage("\n\n".join(parti))]


def indicazione_revisione(motivo: str) -> HumanMessage:
    """Messaggio con cui il motivo della bocciatura entra in cronologia (slide 5, punto 3).

    È un messaggio «utente» e non «di sistema»: molti modelli locali accettano il messaggio di
    sistema solo all'inizio della conversazione. Il motivo è anche in `additional_kwargs`, così
    il terminale lo mostra senza doverlo ritagliare dal testo.
    """
    return HumanMessage(
        f"{PREFISSO_REVISIONE} La risposta precedente non è coerente con la domanda: {motivo} "
        "Riscrivi la risposta completa.",
        additional_kwargs={"motivo": motivo},
    )
