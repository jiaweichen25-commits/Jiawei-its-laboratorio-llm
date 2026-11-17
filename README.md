# Assistente del laboratorio

Agente in Python che conversa con un modello locale servito da LM Studio. Il flusso è un grafo LangGraph; il
modello può chiamare degli strumenti che il programma esegue davvero. Dalla lezione 6 è un'applicazione web
completa: interfaccia di chat nel browser, back-end che salva le conversazioni in PostgreSQL, agente come servizio
HTTP, il tutto avviabile con `docker compose up`. Resta disponibile anche la CLI da terminale.

Strumenti (lezione 5):

| Tool | Cosa fa | Da dove arriva |
|---|---|---|
| `orologio(fuso)` | data, ora e giorno della settimana in un fuso IANA | una delle tre varianti, scelta con `VARIANTE_OROLOGIO` |
| `calcola(espressione)` | calcolatrice sicura (albero `ast`, niente `eval`) | server MCP |
| `converti(valore, da, a)` | conversione tra unità di un elenco chiuso (lunghezza, massa, temperatura) | server MCP |

Le tre varianti dell'orologio (slide 17), una sola attiva per volta:

| `VARIANTE_OROLOGIO` | Percorso | File |
|---|---|---|
| `locale` | funzione Python nel processo dell'agente, registrata con `@tool` | `strumenti.py` |
| `fastapi` | servizio HTTP FastAPI + wrapper `httpx` scritto a mano e registrato con `@tool` | `servizio_api.py`, `wrapper_http.py` |
| `mcp` (predefinita) | server FastMCP (stdio) + client che legge il catalogo (`tools/list`) e lo adatta in tool LangChain | `server_mcp.py`, `client_mcp.py` |

Struttura: `assistente/` (`config.py`, `grafo.py`, `controllo.py`, `modello.py`, `terminale.py`, `logica.py`,
`strumenti.py`, `servizio_api.py`, `wrapper_http.py`, `server_mcp.py`, `client_mcp.py`, `varianti.py`,
`preferenze.py`, `comandi.py`, `agente.py`, `servizio_agente.py`, `cliente_agente.py`), `backend/` (`app.py`, `archivio.py`, `agente_http.py`, `config.py`, `requirements.txt`), `frontend/` (`index.html`, `stile.css`, `config.js`, `api.js`, `app.js`, `test/`, `Dockerfile`, `docker/`), `preferenze.json`, `tests/`, `Dockerfile`, `compose.yaml`, `docs/superpowers/` (specifiche e piani).

## Lezione 6 — evolvere il grafo

Lo stesso modello viene chiamato con prompt di sistema diversi per fare lavori diversi (slide 3). I nodi nuovi si
accendono dalla configurazione; la loro logica è in `assistente/controllo.py`, il collegamento in `assistente/grafo.py`.

### Step 1 · Router: conversazione o fuori ambito

```
START → router ─┬─ conversazione → modello ⇄ strumenti → END
                └─ fuori_ambito  → rifiuto → END
```

- L'ambito dell'agente è nella variabile `AMBITO_AGENTE` del file `.env`, non nel codice. Se manca vale il testo
  predefinito in `config.py`.
- Il nodo `router` chiede al modello un output strutturato, `{"categoria": "conversazione" | "fuori_ambito",
  "motivo": "..."}`, vincolato con `response_format` (schema JSON) e poi validato con Pydantic.
- Fuori ambito: il nodo `rifiuto` risponde con un testo fisso e il nodo `modello` non viene eseguito.
- Il router non riceve gli strumenti: se servono lo decide l'agente, come prima.
- Se la risposta del router non è leggibile la domanda passa all'agente e nei log compare un `WARNING`.

Evidenze nei log (`LOG_LEVEL=INFO`): `router: categoria=... motivo=...`; per una domanda fuori ambito la riga
`rifiuto: richiesta fuori ambito, il nodo modello non viene eseguito` e nessuna riga `modello: inizio chiamata`.

### Step 2 · Revisore: la risposta è coerente con la domanda?

```
modello ─(nessuno strumento richiesto)→ revisore ─┬─ coerente, o limite raggiunto → END
                                                  └─ non coerente + motivo → modello
```

- Il nodo `revisore` riceve la domanda dell'utente, i risultati degli strumenti del turno e la risposta proposta.
  Output strutturato: `{"coerente": true | false, "motivo": "..."}`. Giudica se la risposta copre tutte le parti
  della domanda, non se i fatti sono veri.
- Non coerente: il motivo entra in cronologia come messaggio che inizia con `[Revisione]` e l'agente riscrive.
- `LIMITE_REVISIONI` (predefinito 2) è il numero massimo di rinvii; il contatore `revisioni` sta nello stato del grafo
  e riparte da zero a ogni domanda. Al limite resta l'ultima risposta e nei log compare
  `WARNING revisore: limite di revisioni raggiunto`.
- Scelta sull'interfaccia (slide 18): nel terminale la bozza si vede mentre viene scritta. Se il revisore la boccia
  compare la riga `[revisore] non coerente: <motivo>` e subito dopo la risposta nuova. È la scelta più semplice e
  lascia vedere che cosa fa il revisore; il prezzo è che l'utente legge anche la bozza scartata.

Evidenze nei log: `revisore: coerente ...` oppure `revisore: non coerente (revisione 1 di 2) motivo=...`.

### Step 3 · Riassunto della cronologia

Il grafo completo, con tutti i nodi accesi:

```
START → riassunto → router ─┬─ conversazione → modello ⇄ strumenti
                            │                     │ (nessuno strumento richiesto)
                            │                     ▼
                            │                  revisore ─┬─ coerente, o limite raggiunto → END
                            │                            └─ non coerente + motivo → modello
                            └─ fuori_ambito → rifiuto → END
```

- Il nodo `riassunto` è il primo del turno. Se la cronologia supera `SOGLIA_RIASSUNTO` messaggi (predefinito 12),
  i messaggi vecchi vengono sostituiti da un riassunto e restano gli ultimi `MESSAGGI_DA_CONSERVARE` (predefinito 6).
  Sotto la soglia il nodo non chiama il modello.
- Il taglio cade sempre davanti a una domanda dell'utente: così una richiesta di strumento non viene mai separata dal
  suo `ToolMessage`. Se non c'è un punto di taglio valido (per esempio un solo turno con molti strumenti) non si
  riassume.
- Il riassunto è un campo dello stato (`riassunto`) che viene sostituito a ogni compressione: il modello riceve il
  riassunto precedente e lo fonde con i messaggi nuovi. Entra **in cima** al messaggio di sistema dell'agente ed è
  passato anche al router. In coda alle istruzioni, nella prova reale, gemma lo ignorava e rispondeva di non sapere il
  nome dell'utente; anche in cima un modello da 4B può ogni tanto rispondere così (vedi Limiti noti).
- Se il modello restituisce un riassunto vuoto non si toglie nulla (log `WARNING`).

Evidenze: nei log `riassunto: messaggi prima=14 dopo=6`; nel terminale `[riassunto] cronologia compressa: N messaggi
sostituiti`.

### Tre primitive MCP, tre responsabili (slide 11)

| Primitiva | Chi la attiva | Quando | Nel progetto | Nei log |
|---|---|---|---|---|
| Tool | il modello | durante il ciclo, quando serve | `orologio`, `calcola`, `converti` | `strumenti: richiesta ...` a ogni chiamata |
| Resource | l'applicazione (host) | una volta, prima della prima domanda | `utente://preferenze` (step 4) | `mcp: resources/read utente://preferenze` |
| Prompt | l'utente | quando scrive `/prompt` | `spiega`, `riassumi_conversazione` (step 5) | `mcp: prompts/get ...` |

### Step 4 · Resource: preferenze dell'utente

- Il file `preferenze.json` nella cartella del progetto contiene lingua delle risposte, fuso orario predefinito e stile
  (`sintetico` o `dettagliato`):

  ```json
  {"lingua": "italiano", "fuso_predefinito": "Europe/Rome", "stile": "sintetico"}
  ```

- Il server MCP lo espone come resource `utente://preferenze`. All'avvio l'applicazione la legge una volta e la mette
  in cima al messaggio di sistema. La resource non è un tool: il modello non la vede tra gli strumenti e non la
  «chiama».
- Per cambiare il comportamento si modifica il file e si avvia una nuova sessione, senza toccare il codice.
- Il fuso di `preferenze.json` ha la precedenza su `TZ_PREDEFINITO`, che resta il valore di riserva.
- File mancante, JSON non valido, fuso inesistente o stile sconosciuto: l'agente parte con i valori predefiniti
  (`italiano`, `TZ_PREDEFINITO`, `sintetico`) e nei log compare `WARNING preferenze: non utilizzabili (...)`.
- Per provare un altro file senza toccare quello del progetto: `$env:PREFERENZE_FILE = "C:\percorso\prova.json"`.

Evidenze nei log all'avvio: `mcp: resources/read utente://preferenze → {...}` e
`preferenze: lingua=... fuso=... stile=...`, separate dalle righe `strumenti:` dei tool.

### Step 5 · Prompt: comandi riusabili nella CLI

Il server MCP espone due prompt, cioè modelli di istruzioni con argomenti che è l'utente a richiamare:

| Prompt | Argomenti | Cosa chiede al modello |
|---|---|---|
| `spiega` | `argomento` (obbligatorio), `livello` (facoltativo: base, intermedio, avanzato; predefinito base) | spiegare l'argomento al livello indicato |
| `riassumi_conversazione` | `stile` (facoltativo: sintetico o dettagliato) | riassumere i turni della sessione corrente |

MCP non prevede un comando standard: i comandi li definisce questa CLI.

```text
Tu> /prompts
Tu> /prompt spiega argomento="Model Context Protocol" livello=base
Tu> /prompt riassumi_conversazione stile=dettagliato
```

- I valori con spazi vanno tra virgolette.
- Il programma controlla gli argomenti sull'elenco ricevuto con `prompts/list` prima di chiamare server e modello:
  prompt sconosciuto, argomento obbligatorio mancante, argomento sconosciuto o virgolette non chiuse danno un messaggio
  e nessuna chiamata. Il controllo serve davvero: FastMCP accetta in silenzio un argomento sconosciuto.
- I messaggi ottenuti dal server (`prompts/get`) entrano in cronologia e vanno al grafo come una domanda qualsiasi:
  passano da riassunto, router, strumenti e revisore.
- Un comando che inizia con `/` e non esiste risponde «Comando sconosciuto» senza chiamare il modello.

Evidenze nei log: `prompt: /prompt spiega argomenti={...}` e `mcp: prompts/get spiega argomenti=... messaggi=[...]`.

Tutti i comandi sono per PowerShell (Windows), dalla cartella `its-laboratorio-llm/`.

## Lezione 7 — RAG: ingestion e ricerca semantica

Il modello non conosce i documenti privati e, se l'informazione manca, può inventarla. Il RAG recupera pochi
passaggi pertinenti da un corpus e li mette nel contesto. In questa lezione si costruisce e si **misura** solo il
recupero; il modello generativo torna nella lezione 8, quando la ricerca diventerà uno strumento dell'agente.
Il codice è nel pacchetto `rag/`, separato da `assistente/`.

```
FASE 1 · INGESTION (python -m rag.ingestion, quando il corpus cambia)
dati/artusi.txt → pulizia → 790 ricette → chunk → embedding (LM Studio) → Qdrant, collezione «ricette»

FASE 2 · RICERCA (python -m rag.ricerca, a ogni domanda)
domanda → embedding (stesso modello) → i k chunk più vicini in Qdrant, con filtro per capitolo → testo e fonte
```

### Preparazione

1. **Corpus:** Pellegrino Artusi, *La scienza in cucina e l'arte di mangiar bene* (1891), Project Gutenberg n. 59047,
   pubblico dominio. Scaricare il file di testo da `https://www.gutenberg.org/ebooks/59047.txt.utf-8` e salvarlo in
   `dati/artusi.txt`. La cartella `dati/` è esclusa da Git.
2. **Modello di embedding** in LM Studio: caricare `text-embedding-nomic-embed-text-v1.5` (768 dimensioni) accanto
   al modello generativo e copiarne l'ID da `/v1/models` in `EMBEDDING_MODEL` nel `.env`.
3. **Qdrant** (database vettoriale, in Docker Compose):

   ```powershell
   docker compose up -d qdrant
   ```

   Dashboard web su `http://localhost:6333/dashboard`. I dati stanno nel volume `dati_qdrant`.

### Comandi

```powershell
.\.venv\Scripts\python.exe -m rag.ingestion                                          # costruisce o aggiorna l'indice
.\.venv\Scripts\python.exe -m rag.ricerca "Come si frigge il pollo?" --capitolo Fritti --k 3
.\.venv\Scripts\python.exe -m rag.valutazione --k 5                                  # tabella sulle domande con fonte attesa
```

### Le scelte della pipeline (specifica: `docs/superpowers/specs/2026-11-17-lezione7-ingestion-ricerca-design.md`)

| Scelta | Decisione | Perché |
|---|---|---|
| Documento | una ricetta (790); prefazione, introduzioni, appendice, menu e indice esclusi | ogni risultato ha sempre numero, titolo e capitolo; menu e indice contengono i titoli senza le ricette e «somigliano» troppo alle domande |
| Chunking | una ricetta per chunk; quelle oltre 1200 caratteri divise a paragrafi, overlap 200 | un chunk non mescola mai due ricette e le dosi restano col procedimento; 1200/200 sono i valori della valutazione in aula, quindi confrontabili |
| Payload | `documento_id`, `numero`, `titolo`, `capitolo`, `posizione`, `chunk_totali`, `testo`, `fonte` | citare, filtrare, ritrovare i chunk adiacenti |
| ID | UUID v5 di `ricetta-089:0` | stesso chunk → stesso ID: rieseguendo l'ingestion si sostituisce, non si duplica |
| Rieseguire | upsert + rimozione dei punti orfani; la collezione non si ricrea mai | serve per l'esercizio 2, che modifica chunk e campi sul posto |

Altre regole:

- La collezione registra **modello, dimensione e prefissi**: se la configurazione cambia, ingestion e ricerca si
  fermano e chiedono un'altra collezione (cambiare modello richiede di reindicizzare tutto).
- **Prefissi del modello:** `nomic-embed-text` riceve `search_document: ` davanti ai testi e `search_query: ` davanti
  alle domande, come chiede la sua documentazione (`EMBEDDING_PREFISSI=no` per spegnerli).
- La ricerca ha `k` da 1 a 20 (limite imposto dal codice) e il filtro per capitolo si applica **durante** la ricerca;
  un capitolo inesistente viene rifiutato con l'elenco di quelli validi.
- Consegna: conteggi delle ingestion e valutazioni in `docs/retrieval.md`; domande in `rag/domande.json`.

Variabili nel `.env`: `EMBEDDING_MODEL` (obbligatoria), `EMBEDDING_PREFISSI` (`si`), `QDRANT_URL`
(`http://localhost:6333`), `QDRANT_COLLEZIONE` (`ricette`), `CORPUS_FILE` (`dati/artusi.txt`), `CHUNK_DIMENSIONE`
(`1200`), `CHUNK_OVERLAP` (`200`); il server di LM Studio è lo stesso dell'agente (`LM_BASE_URL`).

## Preparazione

1. Ambiente virtuale e dipendenze (Python 3.14):

   ```powershell
   py -3.14 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   ```

2. Configurazione: copiare il file di esempio. Il file `.env` reale resta fuori da Git.

   ```powershell
   Copy-Item .env.example .env
   ```

   Variabili: `LM_BASE_URL` (con `/v1`), `LM_MODEL`, `TZ_PREDEFINITO` (fuso IANA, es. `Europe/Rome`),
   `LOG_LEVEL` (facoltativa), `VARIANTE_OROLOGIO` (`locale`, `fastapi` o `mcp`; facoltativa, predefinita `mcp`),
   `OROLOGIO_API_URL` (solo per `fastapi`; predefinito `http://localhost:8000`). Lezione 6, tutte facoltative:
   `AMBITO_AGENTE` (di che cosa si occupa l'agente), `LIMITE_REVISIONI` (predefinito 2; 0 spegne il revisore),
   `SOGLIA_RIASSUNTO` (predefinito 12 messaggi; 0 spegne il riassunto), `MESSAGGI_DA_CONSERVARE` (predefinito 6),
   `PREFERENZE_FILE`, `AGENTE_URL` e `AGENTE_TIMEOUT` (CLI e back-end). Per il back-end (step 7): `POSTGRES_USER`,
   `POSTGRES_PASSWORD`, `POSTGRES_DB` e `DATABASE_URL`, con una password a scelta, `CORS_ORIGINI` (step 8) e
   `PORTA_WEB` (step 9, facoltativa: porta dell'applicazione in Docker, predefinita 8085).

3. In LM Studio carica un modello e avvia il server locale. Leggi gli ID disponibili e copia quello scelto in
   `LM_MODEL` nel file `.env` (l'ID è quello restituito dal server, non va inventato):

   ```powershell
   Invoke-RestMethod http://localhost:1234/v1/models
   ```

   L'ID è nel campo `id` di ogni elemento di `data` (sulla macchina di prova: `google/gemma-4-e4b`).

## Avvio locale

Dalla lezione 6 (step 6) l'agente è un **servizio HTTP** e la CLI è un suo client. Servono due terminali.

1. Primo terminale, il servizio dell'agente (avvia anche il server MCP come sottoprocesso e legge le preferenze):

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn assistente.servizio_agente:app --port 8001
   ```

   Documentazione OpenAPI interattiva su `http://localhost:8001/docs`.

2. Secondo terminale, la CLI:

   ```powershell
   .\.venv\Scripts\python.exe -m assistente
   ```

   All'avvio la CLI chiama `GET /stato`; se il servizio non risponde, o se il server MCP o il modello non sono
   disponibili, lo dice ed esce con codice 1. Scrivi le domande (es. «Che ore sono a Tokyo?», «Quanto fa (17+25)*3?»,
   «Converti 10 km in miglia»), `/prompts` e `/prompt`; `esci` chiude la sessione. La risposta compare quando è
   completa, dopo la riga `[agente] in attesa della risposta...`, preceduta dalle tracce `[strumento]`, `[revisore]` e
   `[riassunto]`. I log del grafo (`LOG_LEVEL=INFO`) compaiono nel terminale del servizio.

### Step 6 · L'agente come servizio HTTP

```
CLI (python -m assistente) ──HTTP──▶ servizio agente (porta 8001) ──▶ grafo ──▶ LM Studio / server MCP
```

| Endpoint | Cosa fa |
|---|---|
| `POST /conversazione/stream` | lo stesso turno in streaming (vedi step 8) |
| `POST /conversazione` | un turno: riceve `cronologia`, `riassunto` e una `domanda` **oppure** un `prompt`; restituisce `risposta`, `strumenti_usati`, `cronologia` e `riassunto` aggiornati, `rifiutata`, `revisioni`, `messaggi_riassunti` |
| `GET /prompts` | i prompt MCP con i loro argomenti |
| `GET /stato` | `agente`, `server_mcp`, `modello`: 200 se tutto è `ok`, altrimenti 503 con il dettaglio |

- **Senza stato:** il servizio non ricorda nulla tra due richieste. La cronologia la conserva chi chiama (la CLI, poi
  il back-end dello step 7) e va sostituita con quella restituita, che può essere più corta per via del riassunto.
- La cronologia scambiata contiene solo i messaggi da chat, `{"ruolo": "utente" | "assistente", "testo": "..."}`. Le
  chiamate agli strumenti tornano a parte in `strumenti_usati`.
- Il servizio esegue il grafo in streaming anche se risponde tutto insieme: così il timeout di 120 s del modello vale
  tra un pezzo e l'altro della risposta e non sull'intera spiegazione (vedi la prova dello step 5).
- Lo streaming fino al client non c'è ancora (slide 18, facoltativo): verrà valutato con il front-end.

Prova diretta da PowerShell (con il servizio avviato):

```powershell
Invoke-RestMethod http://localhost:8001/stato
$corpo = @{ cronologia = @(); domanda = "Che ore sono a Tokyo?" } | ConvertTo-Json
Invoke-RestMethod http://localhost:8001/conversazione -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($corpo))
```

Errori:

| Situazione | Codice | Messaggio (`detail`) |
|---|---|---|
| richiesta malformata, domanda e prompt entrambi o nessuno, ruolo sconosciuto | 422 | validazione di FastAPI |
| prompt sconosciuto o argomenti non validi | 422 | es. «Argomento sconosciuto per «spiega»: colore...» |
| LM Studio spento | 503 | «Connessione a LM Studio fallita: controllare server, URL e porta.» |
| LM Studio troppo lento | 504 | «Attesa scaduta: LM Studio non ha risposto in tempo.» |
| server MCP non disponibile per un prompt | 503 | «Errore di collegamento MCP: ...» |
| troppi passaggi tra modello e strumenti | 500 | «Troppi passaggi tra modello e strumenti: turno interrotto.» |

Un errore di uno strumento (per esempio un fuso inesistente) non è un errore HTTP: il modello lo riceve e lo riferisce.

### Step 7 · Back-end: API e salvataggio delle chat

```
front-end (step 8) ──HTTP──▶ back-end (porta 8002) ──HTTP──▶ agente (porta 8001) ──▶ LM Studio
                                  │
                                  ▼
                             PostgreSQL (chat e messaggi, container, porta 5434)
```

Il back-end (cartella `backend/`) è l'unico punto di contatto del front-end. Non importa nulla da `assistente/`: i
due componenti si parlano solo via HTTP. Avvio, con il servizio dell'agente già attivo:

```powershell
docker compose up -d postgres
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --port 8002
```

Documentazione OpenAPI interattiva su `http://localhost:8002/docs`.

| Operazione | Endpoint | Risposta |
|---|---|---|
| Creare una chat | `POST /chat` | 201, la chat con il suo `id` |
| Elencare le chat | `GET /chat` | titolo, `aggiornata_il` (data dell'ultimo messaggio) e numero di messaggi, dalla più recente |
| Leggere una chat | `GET /chat/{id}` | la chat con i messaggi in ordine cronologico |
| Inviare un messaggio | `POST /chat/{id}/messaggi` con `{"testo": "..."}` | `domanda`, `risposta` (con gli `strumenti` usati) e la `chat` aggiornata |
| Inviare in streaming | `POST /chat/{id}/messaggi/stream` | gli stessi dati come eventi (vedi step 8) |
| Eliminare una chat | `DELETE /chat/{id}` | 204; spariscono anche i suoi messaggi |
| Stato | `GET /stato` | `backend`, `database`, `agente`: 200 se tutto è `ok`, altrimenti 503 |

- Dati: tabelle `chat` e `messaggio`, create all'avvio se mancano (SQLAlchemy; `backend/archivio.py`). I dati stanno nel
  volume Docker `dati_postgres`, quindi restano dopo `docker compose down` e dopo il riavvio.
- Il titolo è «Nuova chat» fino alla prima domanda, poi i suoi primi 60 caratteri.
- **Agente non raggiungibile:** domanda e risposta si salvano insieme, solo dopo che l'agente ha risposto. Se l'agente
  è spento o troppo lento il back-end risponde 503 «Agente non raggiungibile: il messaggio non è stato salvato,
  riprova.» e la chat resta com'era. Se l'agente risponde con un errore (per esempio LM Studio spento) il codice è
  502 e il messaggio riporta quello dell'agente.
- **Riassunto:** il database conserva tutti i messaggi, quindi la chat si vede sempre intera. All'agente vanno il
  riassunto e solo i messaggi che il riassunto non copre.
- Credenziali del database solo nel file `.env` (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL`).
- La porta di PostgreSQL sul computer è 5434 perché sulla macchina di sviluppo 5432 e 5433 sono occupate.

Altri errori: chat inesistente → 404 «Chat non trovata.»; testo vuoto → 422; database spento → 503 «Database non
raggiungibile.».

Prova da PowerShell:

```powershell
$chat = Invoke-RestMethod http://localhost:8002/chat -Method Post
$corpo = @{ testo = "Che ore sono a Tokyo?" } | ConvertTo-Json
Invoke-RestMethod "http://localhost:8002/chat/$($chat.id)/messaggi" -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($corpo))
Invoke-RestMethod http://localhost:8002/chat
```

### Step 8 · Front-end: interfaccia di chat, con streaming

Una pagina web (cartella `frontend/`) in HTML, CSS e JavaScript senza librerie, che parla **solo con il back-end**.
Con PostgreSQL, agente e back-end avviati:

```powershell
.\.venv\Scripts\python.exe -m http.server 8003 --directory frontend
```

poi `http://localhost:8003` nel browser.

- A sinistra l'elenco delle chat (dalla più recente), il pulsante «+ Nuova chat» e, per ogni chat, «×» per
  eliminarla (chiede conferma nella pagina). In basso lo stato dei servizi, letto da `GET /stato`.
- A destra i messaggi della chat scelta e la casella per scrivere (Invio manda, Maiusc+Invio va a capo). Sotto ogni
  risposta compaiono gli strumenti usati dall'agente.
- Durante la risposta la casella è disattivata e compare «L'agente sta rispondendo · N s» con i secondi trascorsi.
- Se l'invio fallisce compare un riquadro con il messaggio del back-end (per esempio «Agente non raggiungibile: il
  messaggio non è stato salvato, riprova.»), la domanda torna nella casella e la pagina resta utilizzabile.
- **Indirizzo del back-end:** sta solo in `frontend/config.js` (`backendUrl`). Per usare un altro back-end si cambia
  quella riga.
- **CORS:** in locale pagina (porta 8003) e back-end (porta 8002) sono due origini diverse. Il back-end accetta le
  chiamate solo dalle origini elencate in `CORS_ORIGINI` nel `.env` (`http://localhost:8003`).
- Il testo del modello entra nella pagina come testo semplice (`textContent`), mai come HTML.

File: `index.html` (struttura), `stile.css` (aspetto, tema chiaro e scuro), `config.js` (indirizzo del back-end),
`api.js` (una funzione per ogni operazione del documento OpenAPI del back-end, più la lettura dello streaming),
`app.js` (logica della pagina), `test/api.test.js` (test con il test runner integrato di Node).

#### Streaming (slide 18)

```
agente  POST /conversazione/stream   ──SSE──▶   back-end  POST /chat/{id}/messaggi/stream   ──SSE──▶   browser
```

La risposta HTTP resta aperta e porta una sequenza di eventi (Server-Sent Events: `event: <tipo>` + `data: <JSON>`):

| Evento | Dati | Significato |
|---|---|---|
| `testo` | `{"testo"}` | un frammento della bozza che il modello sta scrivendo |
| `strumento` | `{"nome", "argomenti", "risultato"}` | l'agente ha usato uno strumento; la bozza corrente è finita |
| `revisione` | `{"motivo"}` | il revisore ha bocciato la bozza: viene scartata e ne arriva un'altra |
| `riassunto` | `{"messaggi_riassunti"}` | la cronologia è stata compressa |
| `fine` | agente: l'esito del turno; back-end: `domanda`, `risposta`, `chat` salvati | il turno è finito |
| `errore` | `{"codice", "detail"}` | il turno è fallito a flusso aperto; nulla è stato salvato |

- **Agente:** emette i frammenti man mano che il modello li genera, insieme agli eventi degli strumenti.
- **Back-end:** inoltra gli eventi e salva domanda e risposta solo all'evento `fine`. Gli errori che avvengono prima
  dell'apertura del flusso restano normali risposte HTTP (404, 422, 502, 503).
- **Front-end:** mostra il testo mentre arriva e indica gli strumenti appena vengono usati.
- **Decisione con il revisore attivo:** la bozza si mostra mentre viene scritta. Se il revisore la boccia, la bozza
  viene tolta, compare «Il revisore ha chiesto una correzione: <motivo>» e parte la risposta nuova. Il motivo della
  scelta: con un modello locale lento, mostrare solo la risposta approvata vorrebbe dire minuti di schermo fermo.
- Gli endpoint senza streaming (`POST /conversazione`, `POST /chat/{id}/messaggi`) restano: li usano la CLI e i test.

### Variante `fastapi` dell'orologio (lezione 5)

Il servizio dell'orologio va avviato a parte, in un altro terminale:

```powershell
.\.venv\Scripts\python.exe -m uvicorn assistente.servizio_api:app --port 8000
```

Prova diretta: `Invoke-RestMethod "http://localhost:8000/orologio?fuso=Asia/Tokyo"`; documentazione su
`http://localhost:8000/docs`. Poi `VARIANTE_OROLOGIO=fastapi` nel `.env` e riavvio del servizio dell'agente.

## Avvio con Docker Compose

### Step 9 · L'applicazione completa, un container per componente

Con LM Studio acceso (modello caricato, server locale avviato) e il file `.env` della sezione Preparazione, un solo
comando avvia tutto:

```powershell
docker compose up -d --build
```

poi `http://localhost:8085` nel browser.

```
        computer                         rete interna di Docker Compose
  ┌──────────────────┐      ┌───────────┐      ┌──────────┐      ┌─────────┐
  │ browser          │─────▶│ frontend  │─────▶│ backend  │─────▶│ agente  │──▶ LM Studio sul computer
  │ localhost:8085   │      │ nginx     │ /api │ FastAPI  │      │ + MCP   │    (host.docker.internal)
  └──────────────────┘      └───────────┘      └────┬─────┘      └─────────┘
                                                    ▼
                                               ┌──────────┐
                                               │ postgres │── volume dati_postgres
                                               └──────────┘
```

| Servizio | Immagine | Porta sul computer | Note |
|---|---|---|---|
| `frontend` | `frontend/Dockerfile` (nginx) | 8085 (`PORTA_WEB`) | serve la pagina e fa da proxy: `/api/...` va al back-end |
| `backend` | `backend/Dockerfile` | nessuna | parte quando PostgreSQL è pronto (controllo di salute) |
| `agente` | `Dockerfile` | nessuna | non è esposto: lo chiama solo il back-end; il server MCP parte nel suo container |
| `postgres` | `postgres:17` (ufficiale) | 127.0.0.1:5434 | dati nel volume `dati_postgres` |

- **LM Studio non è in un container:** resta sul computer e l'agente lo raggiunge con `host.docker.internal`.
  Con LM Studio spento i container partono, ma la pagina segnala «modello: LM Studio non raggiungibile».
- **Proxy:** il browser parla solo con nginx. Pagina e API hanno lo stesso indirizzo, quindi CORS non serve e
  back-end e agente non pubblicano porte. Nel container `config.js` vale `backendUrl: "/api"`
  (`frontend/docker/config.js`).
- **Streaming attraverso il proxy:** `frontend/docker/nginx.conf` disattiva l'accumulo delle risposte
  (`proxy_buffering off`) e porta l'attesa a 900 s, altrimenti nginx chiuderebbe il collegamento mentre router o
  revisore stanno lavorando.
- **Credenziali:** `compose.yaml` contiene solo i nomi delle variabili (`${POSTGRES_PASSWORD}`); i valori stanno nel
  `.env`, escluso da Git. La password non deve contenere `@`, `:` o `/`.
- Nel container l'agente usa sempre la variante `mcp` dell'orologio, qualunque sia `VARIANTE_OROLOGIO` nel `.env`.
- PostgreSQL è raggiungibile dal solo computer locale sulla porta 5434: serve per avviare il back-end fuori da
  Docker durante lo sviluppo (sezioni precedenti).

Comandi utili:

```powershell
docker compose ps                 # i quattro servizi e il loro stato
docker compose logs -f agente     # i log del grafo: router, strumenti, revisore
docker compose logs backend       # salvataggi e errori del back-end
docker compose down               # ferma tutto; le chat restano nel volume
docker compose down -v            # ferma tutto e CANCELLA le chat (elimina il volume)
```

La CLI (`python -m assistente`) non fa parte dei container: per usarla si avvia il servizio dell'agente in locale
come indicato in «Avvio locale».

## Test

Test automatici (non richiedono un modello attivo; le prove reali sono escluse):

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Prove reali, da attivare esplicitamente:

```powershell
.\.venv\Scripts\python.exe -m pytest -m lmstudio -v   # richiede LM Studio con server e modello attivi
.\.venv\Scripts\python.exe -m pytest -m docker -v     # richiede Docker Desktop e LM Studio attivi
```

I test automatici coprono anche: logica pura (`test_logica.py`), servizio FastAPI con `TestClient`, wrapper HTTP con
risposte simulate (`httpx.MockTransport`), server MCP in memoria (discovery e chiamate dirette), client MCP in memoria e
come sottoprocesso stdio vero (`test_client_mcp.py`), scelta della variante e avvio.

Una risposta simulata non dimostra che il modello locale sappia usare lo strumento: per questo esistono le prove reali
(`test_reali.py`: orologio con varianti `mcp` e `locale`, calcolatrice, convertitore).

Lezione 6: `test_controllo.py` (output strutturato, trascrizione, messaggi del router) e `test_grafo_lezione6.py`
(percorsi del grafo con le risposte di router e revisore simulate, compreso un revisore che rifiuta sempre e si ferma
al limite, e il riassunto con il punto di taglio). Prove reali in `test_reali.py`: router con domanda in ambito, fuori
ambito e di seguito; revisore con una domanda in due parti; riassunto che ricorda il nome dato al primo turno.
Step 4–5: `test_preferenze.py` (validazione e valori predefiniti), `test_comandi.py` (interpretazione e controllo di
`/prompt`), resource e prompt in `test_server_mcp.py` e `test_client_mcp.py`, comandi in `test_terminale.py`. Prove
reali: fuso `America/New_York` e lingua inglese da un file di preferenze temporaneo; `spiega` attraverso router e
revisore; `riassumi_conversazione` dopo due turni.
Step 6: `test_agente.py`, `test_servizio_agente.py`, `test_cliente_agente.py`, `test_terminale.py`. Step 7:
`test_backend.py` (database SQLite in memoria e agente simulato con `httpx.MockTransport`: le cinque operazioni,
errori, riassunto, persistenza su file) e `test_backend_reali.py` (marker `docker`: PostgreSQL vero, chat presente
dopo il riavvio del back-end e del container; marker `lmstudio`: back-end → agente → LM Studio con l'orologio).
Step 8: streaming in `test_agente.py`, `test_servizio_agente.py` e `test_backend.py` (eventi nell'ordine giusto, errore a
flusso aperto, salvataggio solo alla fine, CORS); `test_frontend.py` (i percorsi usati da `api.js` esistono
nell'OpenAPI del back-end, l'indirizzo sta solo in `config.js`, nessun inserimento di HTML) che esegue anche i test
JavaScript: dalla cartella `frontend/`, `node --test` (lettura degli eventi spezzati tra due pacchetti, chiamate, errori).
Step 9: `test_compose.py` (struttura di `compose.yaml` senza avviare Docker: quattro servizi, agente e back-end non
esposti, back-end dopo il database, nessuna credenziale nel file, proxy adatto allo streaming) e `test_docker.py`
(marker `docker`: i quattro container veri, chat in streaming attraverso il proxy, traccia dello strumento nei log
dell'agente, chat ancora presente dopo `down` e `up`).
Le prove reali controllano che lo strumento abbia risposto, non solo che sia stato chiamato.
Lezione 7: `test_rag_corpus.py` (790 ricette senza buchi, 23 capitoli, pulizia, chunking, ID stabili) e
`test_rag_pipeline.py` (ingestion ripetibile, orfani, metadati della collezione, cambio di modello bloccato,
ricerca con filtro, valutazione) con un embedder finto e Qdrant in memoria: passano con LM Studio e Qdrant spenti.
Prova reale: `pytest -m qdrant` (ingestion completa due volte con lo stesso numero di punti, ricerca filtrata).

## Diagnosi

| Sintomo | Causa e soluzione |
|---|---|
| L'app stampa un errore di connessione ed esce con codice 1 | Server LM Studio non raggiungibile. Avvia il server di LM Studio e controlla `LM_BASE_URL`. |
| L'app elenca degli ID ed esce con codice 1 | `LM_MODEL` non esiste. Copia un ID da `/v1/models`. |
| «Risposta inattesa da http://localhost:1234/models: LM_BASE_URL deve terminare con /v1. Il server dice: Unexpected endpoint or method. (GET /models)», codice 1 | `LM_BASE_URL` senza `/v1` (LM Studio risponde 200 con un corpo di errore). Aggiungi `/v1`; una `/` finale viene tolta. |
| «LOG_LEVEL non valido: «VERBOSE»...», codice 1 | Valori ammessi: DEBUG, INFO, WARNING, ERROR, CRITICAL (anche minuscoli). |
| `docker compose build` fallisce in `pip install` con `CERTIFICATE_VERIFY_FAILED` | Causa verificata: l'antivirus AVG con scansione HTTPS (certificato «AVG Web/Mail Shield Root», accettato da Windows ma non dal container). In AVG disattiva la scansione HTTPS di Web Shield oppure aggiungi eccezioni per `pypi.org` e `files.pythonhosted.org`. Non usare `--trusted-host`. |
| I log (stderr) si mescolano al testo in streaming | Problema noto, non risolto. Per nasconderli imposta `LOG_LEVEL=WARNING` nel `.env`. |
| La CLI stampa «Servizio agente non raggiungibile su http://localhost:8001...» ed esce con codice 1 | Il servizio dell'agente non è avviato o è su un'altra porta. Avvialo con uvicorn (vedi Avvio locale) e controlla `AGENTE_URL`. |
| La CLI stampa «Il servizio agente non è pronto: modello: ...» ed esce con codice 1 | Il servizio è partito ma LM Studio o il modello non sono disponibili (`GET /stato` lo mostra nel dettaglio). |
| Il servizio non parte e nel suo terminale compare `ErroreCollegamentoMCP` | Il server MCP non è partito (slide 24, «processo non avviato»). Guarda `server_mcp.log` nella cartella del progetto: lì finisce lo stderr del server. Controlla che le dipendenze siano installate nel `.venv`. |
| «VARIANTE_OROLOGIO non valida: ...», codice 1 | Valori ammessi: `locale`, `fastapi`, `mcp`. |
| Lo strumento orologio risponde «Errore di collegamento al servizio orologio» | Variante `fastapi` con servizio spento o su un'altra porta. Avvia uvicorn (vedi sopra) e controlla `OROLOGIO_API_URL`. È diverso da «Errore: fuso orario sconosciuto», che indica un fuso sbagliato. |
| Il container non raggiunge LM Studio | Non verificato su questa macchina (ha funzionato subito). Indicazione non verificata: abilita «Serve on Local Network» in LM Studio e controlla il firewall. |

## Limiti noti

- I log su stderr si mescolano al testo in streaming (vedi Diagnosi).
- Lezione 6: router e revisore aggiungono una chiamata al modello ciascuno, quindi ogni domanda richiede più tempo
  (con gemma-4-e4b sulla macchina di prova da 10 a 35 secondi per chiamata).
- Lezione 6: le risposte lunghe, come quella di `/prompt spiega`, possono richiedere minuti (260 s nella prova
  reale). L'agente esegue sempre il grafo in streaming, così il timeout di 120 s del modello vale tra un frammento
  e l'altro e non sull'intera risposta.
- Streaming: la CLI non lo usa ancora (mostra la risposta completa). Se il browser chiude la pagina a metà di una
  risposta, quello scambio non viene salvato. Prima che compaia il primo testo passano comunque decine di secondi,
  perché il router fa una chiamata intera al modello.
- Lezione 6: con un modello da 4B le risposte che dipendono dal riassunto non sono sempre affidabili; a volte il
  modello risponde di non conoscere un'informazione che ha nel messaggio di sistema. Il codice passa il riassunto
  correttamente (verificato catturando la richiesta inviata a LM Studio).
- Il test `test_client_mcp.py::test_server_che_non_risponde_viene_terminato` (lezione 5) fallisce a intermittenza:
  il processo di prova a volte resta vivo oltre i 5 secondi di attesa del test.
