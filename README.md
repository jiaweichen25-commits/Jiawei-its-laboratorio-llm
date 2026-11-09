# Assistente del laboratorio

Applicazione da terminale in Python che conversa con un modello locale servito da LM Studio. Il flusso è un grafo
LangGraph; il modello può chiamare degli strumenti che il programma esegue davvero. La cronologia dura quanto la
sessione (nessuna persistenza).

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

Struttura: `assistente/` (`config.py`, `grafo.py`, `modello.py`, `terminale.py`, `logica.py`, `strumenti.py`,
`servizio_api.py`, `wrapper_http.py`, `server_mcp.py`, `client_mcp.py`, `varianti.py`), `tests/`, `Dockerfile`,
`compose.yaml`, `docs/superpowers/` (specifiche e piani).

Tutti i comandi sono per PowerShell (Windows), dalla cartella `its-laboratorio-llm/`.

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
   `OROLOGIO_API_URL` (solo per `fastapi`; predefinito `http://localhost:8000`).

3. In LM Studio carica un modello e avvia il server locale. Leggi gli ID disponibili e copia quello scelto in
   `LM_MODEL` nel file `.env` (l'ID è quello restituito dal server, non va inventato):

   ```powershell
   Invoke-RestMethod http://localhost:1234/v1/models
   ```

   L'ID è nel campo `id` di ogni elemento di `data` (sulla macchina di prova: `google/gemma-4-e4b`).

## Avvio locale

```powershell
.\.venv\Scripts\python.exe -m assistente
```

All'avvio il programma lancia il server MCP come sottoprocesso (`python -m assistente.server_mcp`), ne legge il
catalogo e chiude il server all'uscita. Scrivi le domande (es. «Che ore sono a Tokyo?», «Quanto fa (17+25)*3?»,
«Converti 10 km in miglia»); `esci` chiude la sessione. Quando il modello usa uno strumento, il programma lo esegue e
stampa una riga `[strumento] nome(argomenti) → risultato`. Con `LOG_LEVEL=INFO` i log su stderr mostrano anche la
traccia della slide 23: `variante=... call_id=... esito=ok|errore`.

### Variante `fastapi`

Il servizio va avviato prima, in un secondo terminale:

```powershell
.\.venv\Scripts\python.exe -m uvicorn assistente.servizio_api:app --port 8000
```

Prova diretta del servizio: `Invoke-RestMethod "http://localhost:8000/orologio?fuso=Asia/Tokyo"`; documentazione
OpenAPI interattiva su `http://localhost:8000/docs`. Poi, nel primo terminale, `VARIANTE_OROLOGIO=fastapi` nel `.env`
e avvio normale.

## Avvio con Docker Compose

LM Studio resta sul computer host; nel container l'indirizzo è `http://host.docker.internal:1234/v1` (impostato in
`compose.yaml`). Serve il file `.env` della sezione Preparazione. Nel container sono previste le varianti `mcp` e
`locale` (il server MCP gira come sottoprocesso dentro lo stesso container); la variante `fastapi` è documentata solo
in locale. Non ancora verificato con Docker dopo la lezione 5 (Docker Desktop spento durante lo sviluppo).

```powershell
docker compose build
docker compose run --rm --name assistente-demo assistente
```

Per vedere i log da un secondo terminale:

```powershell
docker logs -f assistente-demo
```

Verifica del contenuto dell'immagine (devono esserci solo `assistente` e `requirements.txt`):

```powershell
docker run --rm --entrypoint ls its-laboratorio-llm-assistente -a /app
```

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

## Diagnosi

| Sintomo | Causa e soluzione |
|---|---|
| L'app stampa un errore di connessione ed esce con codice 1 | Server LM Studio non raggiungibile. Avvia il server di LM Studio e controlla `LM_BASE_URL`. |
| L'app elenca degli ID ed esce con codice 1 | `LM_MODEL` non esiste. Copia un ID da `/v1/models`. |
| «Risposta inattesa da http://localhost:1234/models: LM_BASE_URL deve terminare con /v1. Il server dice: Unexpected endpoint or method. (GET /models)», codice 1 | `LM_BASE_URL` senza `/v1` (LM Studio risponde 200 con un corpo di errore). Aggiungi `/v1`; una `/` finale viene tolta. |
| «LOG_LEVEL non valido: «VERBOSE»...», codice 1 | Valori ammessi: DEBUG, INFO, WARNING, ERROR, CRITICAL (anche minuscoli). |
| `docker compose build` fallisce in `pip install` con `CERTIFICATE_VERIFY_FAILED` | Causa verificata: l'antivirus AVG con scansione HTTPS (certificato «AVG Web/Mail Shield Root», accettato da Windows ma non dal container). In AVG disattiva la scansione HTTPS di Web Shield oppure aggiungi eccezioni per `pypi.org` e `files.pythonhosted.org`. Non usare `--trusted-host`. |
| I log (stderr) si mescolano al testo in streaming | Problema noto, non risolto. Per nasconderli imposta `LOG_LEVEL=WARNING` nel `.env`. |
| «Errore di collegamento al server MCP: ...», codice 1 | Il server MCP non è partito (slide 24, «processo non avviato»). Guarda `server_mcp.log` nella cartella del progetto: lì finisce lo stderr del server. Controlla che le dipendenze siano installate nel `.venv`. |
| «VARIANTE_OROLOGIO non valida: ...», codice 1 | Valori ammessi: `locale`, `fastapi`, `mcp`. |
| Lo strumento orologio risponde «Errore di collegamento al servizio orologio» | Variante `fastapi` con servizio spento o su un'altra porta. Avvia uvicorn (vedi sopra) e controlla `OROLOGIO_API_URL`. È diverso da «Errore: fuso orario sconosciuto», che indica un fuso sbagliato. |
| Il container non raggiunge LM Studio | Non verificato su questa macchina (ha funzionato subito). Indicazione non verificata: abilita «Serve on Local Network» in LM Studio e controlla il firewall. |

## Limiti noti

- I log su stderr si mescolano al testo in streaming (vedi Diagnosi).
