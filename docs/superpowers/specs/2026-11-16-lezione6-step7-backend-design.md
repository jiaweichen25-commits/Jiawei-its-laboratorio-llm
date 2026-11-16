# Lezione 6, step 7 — Back-end: API e salvataggio delle chat

Data: 2026-11-16. Estende lo step 6 (`2026-11-16-lezione6-step6-servizio-design.md`).
Slide di riferimento: `LLM_Lez_6.pdf`, pagine 12, 14 e 19.

## Perché

Il servizio dell'agente è senza stato: qualcuno deve conservare le conversazioni. Quel qualcuno è il back-end,
che è anche l'unico punto di contatto del front-end (slide 14): gestisce le chat, le salva in PostgreSQL e inoltra
le domande all'agente. Evidenza minima (slide 19): **chat persistenti dopo il riavvio; OpenAPI consultabile**.

```
front-end (step 8) ──HTTP──▶ back-end (porta 8002) ──HTTP──▶ agente (porta 8001) ──▶ LM Studio
                                  │
                                  ▼
                             PostgreSQL (chat e messaggi)
```

## Obiettivi

Un servizio FastAPI nuovo, in una cartella sua (`backend/`), con le cinque operazioni della slide 14:

| Operazione | Endpoint | Risposta |
|---|---|---|
| Creare una chat | `POST /chat` | 201, la chat con il suo `id` |
| Elencare le chat | `GET /chat` | titolo e data dell'ultimo messaggio, dalla più recente |
| Leggere una chat | `GET /chat/{id}` | la chat con i messaggi in ordine cronologico |
| Inviare un messaggio | `POST /chat/{id}/messaggi` | salva la domanda, chiama l'agente, salva e restituisce la risposta |
| Eliminare una chat | `DELETE /chat/{id}` | 204; spariscono anche i suoi messaggi |

Più `GET /stato` (back-end, database e agente raggiungibili) e la documentazione OpenAPI su `/docs`.

## Non obiettivi

- Front-end e Compose a quattro container (step 8 e 9). In questo step il back-end gira in locale con uvicorn;
  in Docker parte solo PostgreSQL.
- Utenti e autenticazione: una sola persona, tutte le chat sono sue.
- Prompt MCP attraverso il back-end: restano un comando della CLI.
- Streaming della risposta (slide 18, facoltativo).

## Approcci considerati

**Come parlare con PostgreSQL**

1. **SQLAlchemy (ORM) con il driver psycopg** — scelto. Le tabelle sono classi Python e lo stesso codice gira su
   PostgreSQL e, nei test automatici, su SQLite in memoria: così i test provano davvero il salvataggio senza
   bisogno di Docker. È anche l'accoppiata più comune con FastAPI.
2. psycopg con SQL scritto a mano. Meno «magia» e una dipendenza in meno, ma il codice che salva si potrebbe
   provare solo con PostgreSQL acceso, quindi quasi tutti i test diventerebbero prove reali.
3. SQLite al posto di PostgreSQL. Più semplice, ma la slide chiede PostgreSQL in un container.

**Che cosa succede alla domanda se l'agente non risponde**

1. **Non resta salvata** — scelto. Domanda e risposta si salvano insieme, in una sola transazione: se l'agente è
   spento il back-end risponde 503 e la chat resta com'era. Il front-end tiene il testo nella casella per riprovare.
2. La domanda resta salvata senza risposta. Segue alla lettera «salva la domanda, chiama l'agente», ma lascia chat
   con domande orfane e complica la cronologia da mandare all'agente al turno dopo.

## Scelte di progetto

### Dati

| Tabella | Campi |
|---|---|
| `chat` | `id` (UUID), `titolo`, `creata_il`, `aggiornata_il`, `riassunto`, `messaggi_riassunti` |
| `messaggio` | `id` (progressivo), `chat_id` → `chat`, `ruolo` (`utente` o `assistente`), `testo`, `creato_il`, `strumenti` (JSON: gli strumenti usati per una risposta) |

- Il titolo è «Nuova chat» finché non arriva la prima domanda, poi i suoi primi 60 caratteri.
- Eliminare una chat elimina i suoi messaggi.
- Le tabelle vengono create all'avvio se non esistono. Nessuno strumento di migrazione: per il laboratorio basta.

### Riassunto e cronologia

Con il riassunto acceso l'agente restituisce una cronologia più corta di quella ricevuta. L'utente però deve
continuare a vedere tutta la chat. Quindi il database conserva **tutti** i messaggi; la chat ricorda il `riassunto`
e quanti messaggi vecchi copre (`messaggi_riassunti`). All'agente si mandano solo i messaggi successivi, insieme
al riassunto; dopo la risposta i due valori si aggiornano con quelli restituiti.

### Errori

| Situazione | Codice | `detail` |
|---|---|---|
| chat inesistente | 404 | «Chat non trovata.» |
| testo vuoto o richiesta malformata | 422 | validazione FastAPI |
| agente non raggiungibile o troppo lento | 503 | «Agente non raggiungibile: il messaggio non è stato salvato, riprova.» |
| l'agente risponde con un errore | 502 | il `detail` dell'agente (es. «Connessione a LM Studio fallita...») |
| database non raggiungibile | 503 | «Database non raggiungibile.» |

### Struttura

```
backend/
  app.py            FastAPI: endpoint e traduzione degli errori; crea_app(...) per i test
  archivio.py       tabelle SQLAlchemy e operazioni sulle chat
  agente_http.py    client httpx del servizio dell'agente (il back-end non importa nulla da assistente/)
  config.py         DATABASE_URL, AGENTE_URL, AGENTE_TIMEOUT dal file .env
  requirements.txt  dipendenze del solo back-end (servirà al suo Dockerfile allo step 9)
```

Il back-end non importa il pacchetto `assistente`: sono due componenti che allo step 9 vivranno in container
diversi e si parlano solo via HTTP.

### Configurazione e Docker

- `.env`: `DATABASE_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`. Credenziali solo nel `.env`, fuori da
  Git; in `.env.example` valori di esempio.
- `compose.yaml` guadagna il servizio `postgres` (immagine ufficiale, volume per i dati, controllo di salute).
  Sul computer la porta pubblicata è **5434**, perché 5432 (PostgreSQL installato su Windows) e 5433 (database di un altro progetto) sono già occupate.
- Avvio locale: `docker compose up -d postgres`, poi
  `.\.venv\Scripts\python.exe -m uvicorn backend.app:app --port 8002`.

### Dipendenze nuove (versioni fissate)

- `sqlalchemy` 2.1.8 — tabelle e interrogazioni.
- `psycopg[binary]` 3.3.9 — driver PostgreSQL.

`fastapi`, `uvicorn` e `httpx` ci sono già.

## Test

Automatici, con SQLite in memoria e agente simulato (`httpx.MockTransport`):

- le cinque operazioni; ordine cronologico dei messaggi; elenco ordinato per ultimo messaggio; titolo dalla prima
  domanda; eliminazione che toglie anche i messaggi; 404 e 422;
- la cronologia inviata all'agente contiene i turni precedenti; `strumenti` salvati con la risposta;
- riassunto: dopo una compressione all'agente arrivano solo i messaggi non coperti, mentre `GET /chat/{id}` li
  mostra tutti;
- agente spento → 503 e chat invariata; agente con errore → 502 con il suo messaggio;
- `/stato`; `/openapi.json` con i sei percorsi;
- persistenza: database SQLite su file, applicazione ricreata, le chat ci sono ancora.

Reali:

- marker `docker`: PostgreSQL vero nel container, chat creata, back-end riavviato, container riavviato
  (`docker compose restart postgres`): la chat c'è ancora;
- marker `lmstudio`: agente vero, domanda che usa l'orologio inviata al back-end, risposta salvata con lo strumento.

## Consegna

Un commit `feat(backend): API delle chat con salvataggio in PostgreSQL`, poi push. README (step 7, avvio, tabella
degli endpoint e degli errori, comportamento con l'agente spento), `.env.example`, `CLAUDE.md`.
