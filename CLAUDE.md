# Assistente del laboratorio

Progetto del corso «Deep Learning e LLM: costruire chatbot e agenti». La cartella del progetto è `its-laboratorio-llm/`.

Struttura: `assistente/` con `config.py` (variabili d'ambiente, verifica del modello, variante dell'orologio, opzioni dei nodi della lezione 6), `grafo.py` (stato, nodi, instradamento: riassunto → router → modello ⇄ strumenti → revisore, più rifiuto; i nodi della lezione 6 si accendono con `OpzioniGrafo`), `controllo.py` (prompt e output strutturato di router, revisore e riassunto), `preferenze.py` (validazione della resource `utente://preferenze`, letta dall'host all'avvio da `preferenze.json`), `comandi.py` (comandi `/prompts` e `/prompt` del terminale e controllo degli argomenti dei prompt MCP), `agente.py` (un turno senza stato: cronologia e riassunto dal chiamante, `EsitoTurno` in uscita; costruzione dell'agente), `servizio_agente.py` (servizio FastAPI dell'agente: `/conversazione`, `/prompts`, `/stato`), `cliente_agente.py` (client HTTP usato dalla CLI), `modello.py` (collegamento a LM Studio), `terminale.py` (CLI, client del servizio), `logica.py` (logica pura di orologio, calcolatrice e convertitore), `strumenti.py` (variante locale), `servizio_api.py` + `wrapper_http.py` (variante FastAPI), `server_mcp.py` + `client_mcp.py` (variante FastMCP, server stdio e adattatore), `varianti.py` (scelta della variante); `backend/` (lezione 6, step 7: back-end delle chat, componente separato che non importa `assistente` — `app.py` API FastAPI, `archivio.py` tabelle SQLAlchemy su PostgreSQL, `agente_http.py` client del servizio dell'agente, `config.py`, `requirements.txt`); `frontend/` (lezione 6, step 8: pagina statica senza librerie che parla solo con il back-end — `config.js` unico posto con l'indirizzo del back-end, `api.js` chiamate e lettura dello streaming SSE, `app.js` logica, `test/` test con `node --test`); `tests/`; `Dockerfile` e `compose.yaml` (servizi `agente` e `postgres`); dipendenze in `requirements.txt` e `requirements-dev.txt`; specifiche e piani in `docs/superpowers/`.

Comandi (PowerShell, dalla cartella del progetto):

- test automatici: `.\.venv\Scripts\python.exe -m pytest`
- prove reali, solo su richiesta: `.\.venv\Scripts\python.exe -m pytest -m lmstudio -v` (LM Studio attivo) e `.\.venv\Scripts\python.exe -m pytest -m docker -v` (Docker e LM Studio attivi)
- servizio della variante fastapi: `.\.venv\Scripts\python.exe -m uvicorn assistente.servizio_api:app --port 8000`
- servizio dell'agente (lezione 6, step 6): `.\.venv\Scripts\python.exe -m uvicorn assistente.servizio_agente:app --port 8001` oppure `docker compose up -d --build`
- CLI, client del servizio: `.\.venv\Scripts\python.exe -m assistente`
- back-end (lezione 6, step 7): `docker compose up -d postgres`, poi `.\.venv\Scripts\python.exe -m uvicorn backend.app:app --port 8002`
- front-end (lezione 6, step 8): `.\.venv\Scripts\python.exe -m http.server 8003 --directory frontend`, poi `http://localhost:8003`; test JavaScript: `node --test` dalla cartella `frontend/`

## Obiettivo

Un'applicazione da terminale in Python che conversa con un modello locale e:

- organizza il flusso in un grafo LangGraph esplicito (stato, nodi, instradamento riconoscibili);
- usa un modello servito da LM Studio, che resta sul computer host;
- conserva la cronologia della conversazione per la durata della sessione (nessuna persistenza);
- offre uno strumento orologio con fuso orario esplicito, richiesto dal modello tramite tool calling ed eseguito davvero dal programma, raggiungibile in tre varianti (locale, FastAPI, FastMCP);
- espone tramite un server MCP anche la calcolatrice sicura e il convertitore di unità (lezione 5);
- rifiuta le domande fuori ambito, fa rivedere le risposte incomplete e riassume la cronologia lunga (lezione 6, step 1–3);
- legge le preferenze dell'utente da una resource MCP e offre prompt MCP richiamabili dall'utente (lezione 6, step 4–5);
- espone l'agente come servizio HTTP senza stato e salva le chat in PostgreSQL tramite un back-end (lezione 6, step 6–7);
- offre un'interfaccia di chat nel browser con la risposta in streaming lungo tutta la catena agente → back-end → front-end (lezione 6, step 8);
- si avvia anche con Docker Compose.

## Confini

- Implementare solo i requisiti concordati. Workflow, RAG e altri strumenti arriveranno nelle lezioni successive: non anticiparli.
- Niente servizi cloud o framework non concordati. L'interfaccia web è quella dello step 8 (pagina statica, senza librerie).
- Lavorare solo dentro `its-laboratorio-llm/`. La repository contiene altre lezioni: non leggerle per copiarne il codice e non modificarle.
- Lavorare nel branch corrente; nessun branch o worktree nuovo se non richiesto.

## Scelte tecniche

- Python, codice sincrono e moduli piccoli, con una separazione semplice tra grafo, collegamento al modello, strumenti e interfaccia da terminale.
- LM Studio sull'host, raggiunto tramite la sua API compatibile con OpenAI.
- Indirizzo del server e identificativo del modello solo da variabili d'ambiente. L'identificativo è quello restituito dal server (`GET /v1/models`), mai inventato.
- Un file di configurazione di esempio senza credenziali; il file reale resta fuori da Git.
- Docker Compose per l'applicazione; LM Studio non va containerizzato.
- Dipendenze motivate, concordate e con versioni fissate.
- Comandi documentati anche per PowerShell (Windows).

## Metodo: Superpowers

- Usare le skill di Superpowers per brainstorming, specifica, piano, implementazione e verifica.
- Non scrivere codice prima che io abbia approvato la specifica e poi il piano.
- Salvare specifica e piano in `its-laboratorio-llm/docs/superpowers/`.
- Procedere per incrementi piccoli, ciascuno verificato prima del commit.

## Test e verifiche

- Test automatici ripetibili che non richiedono un modello attivo (grafo, cronologia, instradamento, strumento con istante controllato).
- Prove reali con LM Studio e con Docker tenute separate e attivate esplicitamente.
- Una risposta simulata non dimostra che il modello locale sappia usare lo strumento.
- Nel resoconto indicare che cosa è stato eseguito, con quale esito, e che cosa resta da provare.

## Git

- Conventional Commits in italiano, per esempio `feat(grafo): ...`, `test(strumenti): ...`, `docs: ...`.
- Prima di ogni commit: `git status`, controllo del diff, staging selettivo dei soli file pertinenti.
- Mai versionare credenziali, `.env`, ambienti virtuali, cache o pesi dei modelli.
- Push soltanto su mia richiesta.

## Documentazione

- Tenere aggiornato il README con configurazione, avvio, test e diagnosi, riportando solo comandi verificati.
- Aggiornare questo file quando cambiano convenzioni stabili (struttura, comandi di test, regole di lavoro), non per annotare l'avanzamento.
