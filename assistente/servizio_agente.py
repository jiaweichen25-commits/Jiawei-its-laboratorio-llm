"""Lezione 6, step 6: l'agente come SERVIZIO HTTP (FastAPI).

Avvio (PowerShell, dalla cartella del progetto):

    .\\.venv\\Scripts\\python.exe -m uvicorn assistente.servizio_agente:app --port 8001

Documentazione OpenAPI interattiva su http://localhost:8001/docs (generata da FastAPI).

Endpoint:
    POST /conversazione   un turno: cronologia + riassunto + domanda (o prompt) → risposta e cronologia aggiornata
    GET  /prompts         i prompt MCP disponibili (per /prompts e /prompt della CLI)
    GET  /stato           agente, server MCP e modello raggiungibili?

Il servizio è SENZA STATO: non ricorda le conversazioni. Le conserva chi lo chiama (la CLI,
poi il back-end dello step 7).
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Literal

import openai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
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
