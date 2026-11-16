"""Lezione 6, step 7: API del back-end (FastAPI).

Avvio (PowerShell, dalla cartella del progetto), con PostgreSQL e il servizio dell'agente attivi:

    docker compose up -d postgres
    .\\.venv\\Scripts\\python.exe -m uvicorn backend.app:app --port 8002

Documentazione OpenAPI interattiva: http://localhost:8002/docs

Il back-end è l'unico punto di contatto del front-end (slide 14): il front-end non conosce
l'agente. Per ogni messaggio: legge la cronologia dal database, chiama l'agente, salva
domanda e risposta.

Dallo step 8 l'invio esiste anche in streaming (POST /chat/{id}/messaggi/stream): il back-end
inoltra al browser gli eventi dell'agente e salva il messaggio completo alla fine (slide 18).
"""

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import dotenv_values, load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import OperationalError

from backend.agente_http import AgenteHttp, AgenteNonRaggiungibile, ErroreAgente
from backend.archivio import Archivio
from backend.config import carica_configurazione

log = logging.getLogger("backend")


# ---------------------------------------------------------------------- contratto (schemi OpenAPI)

class ChatBreve(BaseModel):
    id: str
    titolo: str
    creata_il: str
    aggiornata_il: str = Field(description="Data dell'ultimo messaggio (della creazione, se la chat è vuota)")
    numero_messaggi: int


class MessaggioSalvato(BaseModel):
    id: int
    ruolo: Literal["utente", "assistente"]
    testo: str
    creato_il: str
    strumenti: list[dict] = Field(description="Strumenti usati dall'agente per questa risposta")


class ChatCompleta(ChatBreve):
    messaggi: list[MessaggioSalvato] = Field(description="In ordine cronologico")


class NuovoMessaggio(BaseModel):
    testo: str = Field(description="La domanda dell'utente")

    @field_validator("testo")
    @classmethod
    def _non_vuoto(cls, valore: str) -> str:
        if not valore.strip():
            raise ValueError("il testo non può essere vuoto")
        return valore.strip()


class Scambio(BaseModel):
    domanda: MessaggioSalvato
    risposta: MessaggioSalvato
    chat: ChatBreve = Field(description="La chat aggiornata (titolo, data, numero di messaggi)")


NON_TROVATA = HTTPException(404, "Chat non trovata.")
NON_RAGGIUNGIBILE = "Agente non raggiungibile: il messaggio non è stato salvato, riprova."

DESCRIZIONE_EVENTI = (
    "Flusso `text/event-stream`. Eventi inoltrati dall'agente: `testo` {testo} (frammento della bozza corrente), "
    "`strumento` {nome, argomenti, risultato} (la bozza corrente è finita), `revisione` {motivo} (bozza bocciata, ne "
    "arriva un'altra), `riassunto` {messaggi_riassunti}. Eventi del back-end: `fine` {domanda, risposta, chat} con i "
    "messaggi appena salvati, oppure `errore` {codice, detail} se il turno fallisce a flusso aperto (nulla viene salvato)."
)


def formatta_sse(tipo: str, dati: dict) -> str:
    """Un evento Server-Sent Events: riga «event», riga «data» con il JSON, riga vuota che lo chiude."""
    return f"event: {tipo}\ndata: {json.dumps(dati, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------- applicazione

def crea_app(archivio: Archivio | None = None, agente: AgenteHttp | None = None,
             cors_origini: tuple[str, ...] | None = None) -> FastAPI:
    """Con archivio e agente (nei test) usa quelli; senza, li costruisce all'avvio dal file .env."""
    if cors_origini is None:
        # CORS va deciso alla creazione dell'applicazione, prima dell'avvio. dotenv_values legge il
        # file .env senza modificare le variabili del processo (qui siamo ancora all'importazione).
        ambiente = {**dotenv_values(), **os.environ}
        cors_origini = carica_configurazione({"DATABASE_URL": "-", **ambiente}).cors_origini

    @asynccontextmanager
    async def ciclo_di_vita(app: FastAPI):
        if archivio is None:
            load_dotenv(override=False)
            cfg = carica_configurazione(os.environ)
            logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                                format="%(asctime)s %(levelname)s %(name)s: %(message)s")
            log.setLevel(cfg.log_level)
            app.state.archivio = Archivio(cfg.database_url)
            app.state.archivio.prepara()  # crea le tabelle; se il database non risponde il back-end non parte
            app.state.agente = AgenteHttp(cfg.agente_url, timeout=cfg.agente_timeout)
            log.info("back-end avviato: agente su %s", cfg.agente_url)
        yield
        if archivio is None:
            app.state.agente.chiudi()
            app.state.archivio.chiudi()

    app = FastAPI(
        title="Back-end delle chat",
        description="Gestisce le chat, le salva in PostgreSQL e inoltra le domande all'agente.",
        lifespan=ciclo_di_vita,
    )
    if archivio is not None:
        app.state.archivio, app.state.agente = archivio, agente
    if cors_origini:
        # Step 8: in locale la pagina (porta 8003) e l'API (porta 8002) sono «origini» diverse e il
        # browser blocca le chiamate, a meno che il back-end dichiari di accettarle da quell'origine.
        app.add_middleware(CORSMiddleware, allow_origins=list(cors_origini),
                           allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])

    @app.exception_handler(OperationalError)
    def database_non_raggiungibile(richiesta, exc):
        # OperationalError = SQLAlchemy non riesce a parlare con il database (spento, rete, credenziali).
        log.error("database non raggiungibile: %s", exc)
        return JSONResponse({"detail": "Database non raggiungibile."}, status_code=503)

    # Endpoint sincroni (def): FastAPI li esegue in un thread, così l'attesa dell'agente (anche
    # minuti) non blocca le altre richieste, per esempio l'elenco delle chat.

    @app.post("/chat", response_model=ChatBreve, status_code=201)
    def crea_chat() -> dict:
        """Crea una chat vuota e ne restituisce l'identificativo."""
        return app.state.archivio.crea_chat()

    @app.get("/chat", response_model=list[ChatBreve])
    def elenca_chat() -> list[dict]:
        """Tutte le chat, dalla più recente: titolo e data dell'ultimo messaggio."""
        return app.state.archivio.elenco()

    @app.get("/chat/{chat_id}", response_model=ChatCompleta)
    def leggi_chat(chat_id: str) -> dict:
        """Una chat con i suoi messaggi in ordine cronologico."""
        chat = app.state.archivio.leggi(chat_id)
        if chat is None:
            raise NON_TROVATA
        return chat

    @app.delete("/chat/{chat_id}", status_code=204)
    def elimina_chat(chat_id: str) -> Response:
        """Elimina la chat e tutti i suoi messaggi."""
        if not app.state.archivio.elimina(chat_id):
            raise NON_TROVATA
        return Response(status_code=204)

    def salva_esito(chat_id: str, domanda: str, esito: dict, riassunto_precedente: str) -> dict:
        """Salva domanda e risposta dopo un turno riuscito (con o senza streaming)."""
        risposta = (esito.get("risposta") or "").strip()
        if not risposta:
            raise HTTPException(502, "L'agente ha restituito una risposta vuota: il messaggio non è stato salvato.")
        scambio = app.state.archivio.salva_scambio(
            chat_id, domanda, risposta, esito.get("strumenti_usati", []),
            esito.get("riassunto", riassunto_precedente), esito.get("messaggi_riassunti", 0),
        )
        if scambio is None:  # chat eliminata mentre l'agente rispondeva
            raise NON_TROVATA
        log.info("chat %s: scambio salvato (strumenti=%s)", chat_id, [s.get("nome") for s in scambio["risposta"]["strumenti"]])
        return scambio

    def errore_agente(exc: ErroreAgente) -> str:
        return f"L'agente ha risposto con un errore ({exc.codice}): {exc.dettaglio} Il messaggio non è stato salvato."

    @app.post("/chat/{chat_id}/messaggi", response_model=Scambio)
    def invia_messaggio(chat_id: str, nuovo: NuovoMessaggio) -> dict:
        """Manda la domanda all'agente con la cronologia della chat, poi salva domanda e risposta."""
        contesto = app.state.archivio.contesto_per_agente(chat_id)
        if contesto is None:
            raise NON_TROVATA
        cronologia, riassunto = contesto
        log.info("chat %s: domanda all'agente con %d messaggi di cronologia", chat_id, len(cronologia))
        try:
            esito = app.state.agente.conversazione(cronologia, riassunto, nuovo.testo)
        except AgenteNonRaggiungibile as exc:
            log.error("chat %s: agente non raggiungibile: %s", chat_id, exc)
            raise HTTPException(503, NON_RAGGIUNGIBILE) from None
        except ErroreAgente as exc:
            log.error("chat %s: errore dell'agente %s", chat_id, exc)
            raise HTTPException(502, errore_agente(exc)) from None
        return salva_esito(chat_id, nuovo.testo, esito, riassunto)

    @app.post(
        "/chat/{chat_id}/messaggi/stream",
        response_class=StreamingResponse,
        responses={200: {"description": DESCRIZIONE_EVENTI, "content": {"text/event-stream": {}}}},
    )
    def invia_messaggio_stream(chat_id: str, nuovo: NuovoMessaggio) -> StreamingResponse:
        """Come l'invio normale, ma la risposta arriva in streaming mentre l'agente la scrive (slide 18)."""
        contesto = app.state.archivio.contesto_per_agente(chat_id)
        if contesto is None:
            raise NON_TROVATA
        cronologia, riassunto = contesto
        log.info("chat %s: domanda in streaming con %d messaggi di cronologia", chat_id, len(cronologia))
        # Il flusso verso l'agente si apre PRIMA di rispondere al browser: se l'agente è spento
        # o rifiuta la richiesta, il browser riceve ancora un normale 503 o 502.
        try:
            flusso_agente = app.state.agente.apri_stream(cronologia, riassunto, nuovo.testo)
        except AgenteNonRaggiungibile as exc:
            log.error("chat %s: agente non raggiungibile: %s", chat_id, exc)
            raise HTTPException(503, NON_RAGGIUNGIBILE) from None
        except ErroreAgente as exc:
            log.error("chat %s: errore dell'agente %s", chat_id, exc)
            raise HTTPException(502, errore_agente(exc)) from None

        def flusso():
            # Da qui la risposta 200 è già partita: ogni problema diventa un evento «errore».
            try:
                for tipo, dati in app.state.agente.eventi(flusso_agente):
                    if tipo == "fine":
                        # Slide 18, punto 02: il messaggio completo si salva alla fine del flusso.
                        yield formatta_sse("fine", salva_esito(chat_id, nuovo.testo, dati, riassunto))
                        return
                    if tipo == "errore":
                        dettaglio = errore_agente(ErroreAgente(dati.get("codice", 500), dati.get("detail", "")))
                        log.error("chat %s: %s", chat_id, dettaglio)
                        yield formatta_sse("errore", {"codice": 502, "detail": dettaglio})
                        return
                    yield formatta_sse(tipo, dati)  # testo, strumento, revisione, riassunto: inoltrati così come sono
                yield formatta_sse("errore", {"codice": 502, "detail": "L'agente ha chiuso il collegamento prima di "
                                              "finire la risposta: il messaggio non è stato salvato."})
            except AgenteNonRaggiungibile as exc:
                log.error("chat %s: collegamento con l'agente caduto: %s", chat_id, exc)
                yield formatta_sse("errore", {"codice": 503, "detail": NON_RAGGIUNGIBILE})
            except HTTPException as exc:
                yield formatta_sse("errore", {"codice": exc.status_code, "detail": exc.detail})

        return StreamingResponse(flusso(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/stato")
    def stato() -> JSONResponse:
        """200 se back-end, database e agente sono disponibili; altrimenti 503 con il dettaglio."""
        valori = {
            "backend": "ok",
            "database": "ok" if app.state.archivio.raggiungibile() else "non raggiungibile",
            "agente": app.state.agente.stato(),
        }
        return JSONResponse(valori, status_code=200 if all(v == "ok" for v in valori.values()) else 503)

    return app


app = crea_app()
