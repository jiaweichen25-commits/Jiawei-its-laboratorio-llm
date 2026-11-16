"""Lezione 6, step 6: l'agente come SERVIZIO HTTP (FastAPI).

Avvio (PowerShell, dalla cartella del progetto):

    .\\.venv\\Scripts\\python.exe -m uvicorn assistente.servizio_agente:app --port 8001

Documentazione OpenAPI interattiva su http://localhost:8001/docs (generata da FastAPI).

Endpoint:
    POST /conversazione          un turno: cronologia + riassunto + domanda (o prompt) → risposta e cronologia aggiornata
    POST /conversazione/stream   lo stesso turno in streaming (Server-Sent Events): il testo arriva mentre viene scritto
    GET  /prompts         i prompt MCP disponibili (per /prompts e /prompt della CLI)
    GET  /stato           agente, server MCP e modello raggiungibili?

Il servizio è SENZA STATO: non ricorda le conversazioni. Le conserva chi lo chiama (la CLI,
poi il back-end dello step 7).
"""

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Literal

import openai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field, model_validator

from assistente.agente import Agente, crea_agente
from assistente.client_mcp import ErroreCollegamentoMCP
from assistente.comandi import ErroreComando
from assistente.config import carica_configurazione
from assistente.modello import descrivi_errore

log = logging.getLogger("assistente.servizio")


# ---------------------------------------------------------------------- contratto (schemi OpenAPI)

class Messaggio(BaseModel):
    ruolo: Literal["utente", "assistente"]
    testo: str


class RichiestaPrompt(BaseModel):
    nome: str = Field(description="Nome del prompt MCP, es. spiega")
    argomenti: dict[str, str] = Field(default_factory=dict, description='Es. {"argomento": "MCP"}')


class RichiestaConversazione(BaseModel):
    cronologia: list[Messaggio] = Field(default_factory=list, description="Messaggi precedenti, dal più vecchio")
    riassunto: str = Field(default="", description="Riassunto restituito dalla risposta precedente")
    domanda: str | None = Field(default=None, description="Nuova domanda dell'utente")
    prompt: RichiestaPrompt | None = Field(default=None, description="In alternativa alla domanda: un prompt MCP")

    @model_validator(mode="after")
    def _domanda_oppure_prompt(self):
        ha_domanda = self.domanda is not None and self.domanda.strip() != ""
        if ha_domanda == (self.prompt is not None):
            raise ValueError("indicare esattamente uno tra `domanda` (non vuota) e `prompt`")
        return self


class StrumentoUsato(BaseModel):
    nome: str
    argomenti: dict
    risultato: str


class RispostaConversazione(BaseModel):
    risposta: str
    strumenti_usati: list[StrumentoUsato]
    cronologia: list[Messaggio] = Field(description="Da usare al posto della propria: può essere più corta")
    riassunto: str
    rifiutata: bool
    revisioni: list[str] = Field(description="Motivi con cui il revisore ha rimandato indietro la risposta")
    messaggi_riassunti: int


class ArgomentoPrompt(BaseModel):
    nome: str
    descrizione: str
    obbligatorio: bool


class DescrizionePrompt(BaseModel):
    nome: str
    descrizione: str
    argomenti: list[ArgomentoPrompt]


# ---------------------------------------------------------------------- errori

def errore_http(exc: BaseException) -> HTTPException | None:
    """Traduce un errore del turno in codice HTTP e messaggio comprensibile (slide 13)."""
    if isinstance(exc, ErroreComando):
        return HTTPException(422, str(exc))
    if isinstance(exc, ErroreCollegamentoMCP):
        return HTTPException(503, f"Errore di collegamento MCP: {exc}")
    if isinstance(exc, GraphRecursionError):
        return HTTPException(500, "Troppi passaggi tra modello e strumenti: turno interrotto.")
    messaggio = descrivi_errore(exc)  # gli stessi messaggi su LM Studio usati dal terminale
    if messaggio is None:
        return None
    if isinstance(exc, openai.APITimeoutError):  # va controllato prima: è una APIConnectionError
        return HTTPException(504, messaggio)
    if isinstance(exc, openai.APIConnectionError):
        return HTTPException(503, messaggio)
    return HTTPException(502, messaggio)  # LM Studio ha risposto con un errore HTTP


def formatta_sse(tipo: str, dati: dict) -> str:
    """Un evento Server-Sent Events: riga «event», riga «data» con il JSON, riga vuota che lo chiude."""
    return f"event: {tipo}\ndata: {json.dumps(dati, ensure_ascii=False)}\n\n"


DESCRIZIONE_EVENTI = (
    "Flusso `text/event-stream`. Eventi: `testo` {testo} (frammento della bozza corrente), `strumento` "
    "{nome, argomenti, risultato} (la bozza corrente è finita), `revisione` {motivo} (bozza bocciata, ne arriva "
    "un'altra), `riassunto` {messaggi_riassunti}, `fine` (stesso corpo di POST /conversazione), `errore` "
    "{codice, detail} (turno fallito dopo l'inizio del flusso)."
)


# ---------------------------------------------------------------------- applicazione

def crea_app(agente: Agente | None = None) -> FastAPI:
    """Con `agente` (nei test) usa quello; senza, lo costruisce all'avvio dal file .env."""

    @asynccontextmanager
    async def ciclo_di_vita(app: FastAPI):
        cliente_mcp = None
        if agente is None:
            load_dotenv(override=False)
            cfg = carica_configurazione(os.environ)
            logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                                format="%(asctime)s %(levelname)s %(name)s: %(message)s")
            logging.getLogger("assistente").setLevel(cfg.log_level)
            app.state.agente, cliente_mcp = crea_agente(cfg)
        yield
        if cliente_mcp is not None:
            cliente_mcp.chiudi()  # allo spegnimento del servizio termina anche il server MCP

    app = FastAPI(
        title="Agente del laboratorio",
        description="Agente LangGraph con strumenti MCP, servito da LM Studio. Senza stato: la cronologia la "
                    "conserva il chiamante.",
        lifespan=ciclo_di_vita,
    )
    if agente is not None:
        app.state.agente = agente  # già pronto (test): disponibile anche senza la fase di avvio

    # Endpoint sincroni (def, non async def): FastAPI li esegue in un thread separato, così un turno
    # lungo del modello non blocca le altre richieste.

    @app.post("/conversazione", response_model=RispostaConversazione)
    def conversazione(richiesta: RichiestaConversazione) -> RispostaConversazione:
        """Esegue un turno dell'agente e restituisce risposta, strumenti usati e cronologia aggiornata."""
        prompt = (richiesta.prompt.nome, richiesta.prompt.argomenti) if richiesta.prompt else None
        log.info("POST /conversazione: %d messaggi, %s", len(richiesta.cronologia),
                 f"prompt={prompt}" if prompt else f"domanda={richiesta.domanda!r}")
        try:
            esito = app.state.agente.rispondi(
                [m.model_dump() for m in richiesta.cronologia], richiesta.riassunto, richiesta.domanda, prompt
            )
        except Exception as exc:
            http = errore_http(exc)
            if http is None:
                raise
            log.error("POST /conversazione: %d %s", http.status_code, http.detail)
            raise http from None
        return RispostaConversazione(**esito.__dict__)

    @app.post(
        "/conversazione/stream",
        response_class=StreamingResponse,
        responses={200: {"description": DESCRIZIONE_EVENTI, "content": {"text/event-stream": {}}}},
    )
    def conversazione_stream(richiesta: RichiestaConversazione) -> StreamingResponse:
        """Lo stesso turno di POST /conversazione, ma il testo arriva mentre il modello lo scrive (slide 18)."""
        prompt = (richiesta.prompt.nome, richiesta.prompt.argomenti) if richiesta.prompt else None
        log.info("POST /conversazione/stream: %d messaggi, %s", len(richiesta.cronologia),
                 f"prompt={prompt}" if prompt else f"domanda={richiesta.domanda!r}")
        agente_app = app.state.agente
        # Il prompt si controlla PRIMA di aprire il flusso: così un errore è ancora un normale 422.
        try:
            nuovi = agente_app.prepara(richiesta.domanda, prompt)
        except Exception as exc:
            http = errore_http(exc)
            if http is None:
                raise
            raise http from None
        cronologia = [m.model_dump() for m in richiesta.cronologia]

        def flusso():
            try:
                for tipo, dati in agente_app.eventi(cronologia, richiesta.riassunto, nuovi):
                    yield formatta_sse(tipo, dati)
            except Exception as exc:
                # La risposta 200 è già partita: l'errore non può più essere un codice HTTP,
                # quindi viaggia come ultimo evento del flusso.
                http = errore_http(exc)
                codice, dettaglio = (http.status_code, http.detail) if http else (500, f"Errore interno: {type(exc).__name__}")
                log.error("POST /conversazione/stream: errore a flusso aperto: %d %s", codice, dettaglio)
                yield formatta_sse("errore", {"codice": codice, "detail": dettaglio})

        # no-cache e X-Accel-Buffering: chiedono ai proxy (nginx allo step 9) di non trattenere gli eventi.
        return StreamingResponse(flusso(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/prompts", response_model=list[DescrizionePrompt])
    def prompts() -> list[DescrizionePrompt]:
        """I prompt MCP del server, con i loro argomenti (da prompts/list)."""
        return [
            DescrizionePrompt(
                nome=p.name,
                descrizione=p.description or "",
                argomenti=[ArgomentoPrompt(nome=a.name, descrizione=a.description or "", obbligatorio=bool(a.required))
                           for a in (p.arguments or [])],
            )
            for p in app.state.agente.prompts()
        ]

    @app.get("/stato")
    def stato() -> JSONResponse:
        """200 se agente, server MCP e modello sono disponibili; altrimenti 503 con il dettaglio."""
        valori = app.state.agente.stato()
        tutto_ok = all(v == "ok" for v in valori.values())
        return JSONResponse(valori, status_code=200 if tutto_ok else 503)

    return app


app = crea_app()
