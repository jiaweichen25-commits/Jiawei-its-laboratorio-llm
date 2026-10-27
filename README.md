# Assistente del laboratorio

Applicazione da terminale in Python che conversa con un modello locale servito da LM Studio. Il flusso è un grafo
LangGraph; il modello può chiamare lo strumento `orologio` (ora corrente in un fuso orario esplicito), che il programma
esegue davvero. La cronologia dura quanto la sessione (nessuna persistenza).

Struttura: `assistente/` (`config.py`, `grafo.py`, `modello.py`, `strumenti.py`, `terminale.py`), `tests/`,
`Dockerfile`, `compose.yaml`, `docs/superpowers/` (specifica e piano).

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
   `LOG_LEVEL` (facoltativa).

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

Scrivi le domande (es. «Che ore sono?», poi «E a New York?»); `esci` chiude la sessione. Quando il modello usa lo
strumento, il programma lo esegue e l'ora compare nella risposta.

## Avvio con Docker Compose

LM Studio resta sul computer host; nel container l'indirizzo è `http://host.docker.internal:1234/v1` (impostato in
`compose.yaml`). Serve il file `.env` della sezione Preparazione.

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

Una risposta simulata non dimostra che il modello locale sappia usare lo strumento: per questo esistono le prove reali.

## Diagnosi

| Sintomo | Causa e soluzione |
|---|---|
| L'app stampa un errore di connessione ed esce con codice 1 | Server LM Studio non raggiungibile. Avvia il server di LM Studio e controlla `LM_BASE_URL`. |
| L'app elenca degli ID ed esce con codice 1 | `LM_MODEL` non esiste. Copia un ID da `/v1/models`. |
| Errore 404 su `/models` | `LM_BASE_URL` senza `/v1`. Il messaggio lo suggerisce; una `/` finale viene tolta. |
| `docker compose build` fallisce in `pip install` con `CERTIFICATE_VERIFY_FAILED` | Causa verificata: l'antivirus AVG con scansione HTTPS (certificato «AVG Web/Mail Shield Root», accettato da Windows ma non dal container). In AVG disattiva la scansione HTTPS di Web Shield oppure aggiungi eccezioni per `pypi.org` e `files.pythonhosted.org`. Non usare `--trusted-host`. |
| I log (stderr) si mescolano al testo in streaming | Problema noto, non risolto. Per nasconderli imposta `LOG_LEVEL=WARNING` nel `.env`. |
| Il container non raggiunge LM Studio | Non verificato su questa macchina (ha funzionato subito). Indicazione non verificata: abilita «Serve on Local Network» in LM Studio e controlla il firewall. |

## Limiti noti

- I log su stderr si mescolano al testo in streaming (vedi Diagnosi).
