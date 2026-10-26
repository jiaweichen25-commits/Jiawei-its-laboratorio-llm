# Assistente del laboratorio — specifica

Data: 2026-10-26 · Lezione 4 · Stato: in revisione

## 1. Obiettivo

Un'applicazione Python da terminale, nella root della repository `its-laboratorio-llm/`, che conversa con un modello locale servito da LM Studio sull'host. Il flusso è un grafo LangGraph esplicito; la cronologia vale per la sessione; il modello può richiedere uno strumento orologio che il programma esegue davvero; l'applicazione si avvia anche con Docker Compose.

Il progetto continuerà nelle lezioni successive (altri strumenti, MCP, workflow, RAG) estendendo questo codice e questo grafo.

### Fuori ambito

Altri strumenti, MCP, workflow, RAG, interfacce grafiche o web, servizi cloud (compreso LangSmith), persistenza della cronologia, containerizzazione di LM Studio.

## 2. Decisioni prese nel brainstorming

| Tema | Decisione | Motivo |
|---|---|---|
| Fuso senza indicazione dell'utente | Fuso predefinito da `TZ_PREDEFINITO`, comunicato al modello; il modello passa sempre un nome IANA allo strumento | La chiamata resta esplicita senza obbligare l'utente a indicarlo |
| Visibilità dello strumento | Riga `[strumento] ...` sempre stampata prima della risposta, più eventi nei log | Dimostra che lo strumento è stato eseguito davvero |
| Risposta | In streaming | Scelta dell'utente |
| Collegamento al modello | `langchain-openai` (`ChatOpenAI` verso LM Studio) | Lo streaming nel grafo e la ricomposizione delle chiamate agli strumenti sono già gestiti |
| Grafo | `StateGraph` scritto a mano; niente `create_react_agent` né `ToolNode` | Stato, nodi e instradamento restano riconoscibili |
| Cronologia | `InMemorySaver` con `thread_id` fisso | Solo memoria del processo: persa all'uscita |
| Cartella | Root della repository `its-laboratorio-llm/`, che fa le veci di `assistente-laboratorio/` delle slide; `Lezione3/` resta esclusa | Scelta dell'utente |

## 3. Struttura

```
its-laboratorio-llm/
├─ Lezione3/           # lezione precedente: non letta né modificata
├─ assistente/
│  ├─ __init__.py
│  ├─ __main__.py      # python -m assistente
│  ├─ config.py        # variabili d'ambiente e controlli all'avvio
│  ├─ modello.py       # ChatOpenAI collegato a LM Studio
│  ├─ strumenti.py     # orologio
│  ├─ grafo.py         # stato, nodi, instradamento, compilazione
│  └─ terminale.py     # ciclo di conversazione, streaming, traccia
├─ tests/
├─ docs/superpowers/   # specifica e piano
├─ requirements.txt  requirements-dev.txt  pytest.ini
├─ .env.example  .gitignore  .dockerignore
├─ Dockerfile  compose.yaml
├─ README.md  CLAUDE.md
```

Dipendenze tra moduli: `terminale` → `grafo` → (`strumenti`, modello ricevuto come parametro); `__main__` mette insieme `config`, `modello`, `strumenti`, `grafo`, `terminale`. Solo `config.py` legge l'ambiente; solo `modello.py` conosce LM Studio.

### Dipendenze

| Pacchetto | File | Motivo |
|---|---|---|
| `langgraph` | requirements.txt | Grafo, stato, checkpointer in memoria |
| `langchain-openai` | requirements.txt | Client compatibile OpenAI con tool calling e streaming |
| `python-dotenv` | requirements.txt | Lettura di `.env` in locale |
| `tzdata` | requirements.txt | Database IANA per `zoneinfo`, assente su Windows e nell'immagine slim |
| `pytest` | requirements-dev.txt | Test |

Versioni fissate con `==` al momento dell'installazione. Python 3.14 in locale e nell'immagine (`python:3.14-slim`); se una dipendenza non lo supporta, 3.13 in entrambi.

Il controllo di `/v1/models` usa `urllib.request` della libreria standard, senza dipendenze aggiuntive.

## 4. Configurazione

Variabili, tutte obbligatorie, lette con `load_dotenv(override=False)` (l'ambiente impostato da Compose ha la precedenza):

| Variabile | Esempio | Significato |
|---|---|---|
| `LM_BASE_URL` | `http://localhost:1234/v1` | Base URL compatibile OpenAI, `/v1` compreso |
| `LM_MODEL` | `google/gemma-4-e4b` | ID restituito da `GET /v1/models` |
| `TZ_PREDEFINITO` | `Europe/Rome` | Fuso IANA usato quando l'utente non ne indica uno |

Facoltativa: `LOG_LEVEL` (predefinito `INFO`).

`.env.example` contiene queste variabili con valori di esempio, senza credenziali. `.env` è escluso da Git e dal contesto Docker. `.gitignore`: `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`. La chiave API richiesta da `ChatOpenAI` è il valore fisso `lm-studio`, ignorato da LM Studio.

### Controlli all'avvio (prima del primo prompt)

1. Variabile obbligatoria mancante → messaggio che la nomina, uscita con codice 1.
2. `TZ_PREDEFINITO` non valido → messaggio, uscita con codice 1.
3. `GET {LM_BASE_URL}/models` (timeout 5 s):
   - server non raggiungibile → messaggio su LM Studio avviato, URL e porta; uscita 1;
   - `LM_MODEL` assente → elenco degli ID disponibili; uscita 1.

## 5. Grafo

Stato: `MessagesState` (lista `messages` con riduttore che aggiunge o aggiorna per id).

```
START → modello ─instrada()─┬─ "strumenti" → strumenti → modello
                            └─ END
```

- **`modello`**: costruisce un messaggio di sistema a ogni chiamata, non salvato nello stato: «Rispondi in italiano. Per conoscere data o ora usa sempre lo strumento `orologio`, senza inventarle. Se l'utente non indica un fuso orario, usa `<TZ_PREDEFINITO>`.» Chiama il modello con lo strumento collegato (`bind_tools`) e restituisce `{"messages": [risposta]}`. Registra nei log inizio e fine con la durata.
- **`instrada`**: `"strumenti"` se l'ultimo messaggio ha `tool_calls`, altrimenti `END`.
- **`strumenti`**: per ogni chiamata cerca lo strumento per nome ed esegue; produce un `ToolMessage` con lo stesso `tool_call_id`. Nome sconosciuto, argomenti non validi o eccezione → `ToolMessage` con testo che inizia per `Errore:`; il grafo continua. Registra nei log nome, argomenti e risultato.
- `recursion_limit = 10` a ogni invocazione.
- Costruzione: `costruisci_grafo(modello, strumenti, fuso_predefinito, checkpointer)`; il modello è iniettato, così i test usano un modello finto.

## 6. Strumento orologio (contratto)

| Parte | Decisione |
|---|---|
| Nome | `orologio` |
| Descrizione per il modello | «Restituisce la data e l'ora correnti nel fuso orario indicato. Usalo ogni volta che servono data o ora attuali.» |
| Parametri | `fuso: str`, obbligatorio, nome IANA (es. `Europe/Rome`, `Asia/Tokyo`, `UTC`) |
| Risultato | ISO 8601 al secondo con offset, seguito dal nome del fuso: `2026-10-27T00:42:10+09:00 (Asia/Tokyo)` |
| Errori | Fuso inesistente → `Errore: fuso orario sconosciuto: «<valore>»`; nessun fuso indovinato |

Creato da `crea_orologio(adesso)`, dove `adesso()` restituisce un `datetime` UTC consapevole del fuso: in produzione l'ora di sistema, nei test un istante fisso.

## 7. Terminale

- Prompt `Tu> `; si esce con `esci`, Ctrl+C o EOF. Input vuoto ignorato.
- Ogni turno: `grafo.stream({"messages": [HumanMessage(domanda)]}, config, stream_mode=["messages", "updates"])`.
  - Dal flusso `messages`: i token di testo prodotti dal nodo `modello` sono stampati man mano.
  - Dal flusso `updates`: le `tool_calls` complete del nodo `modello` e i `ToolMessage` del nodo `strumenti` producono, per ogni chiamata, la riga
    `[strumento] orologio(fuso="Asia/Tokyo") → 2026-10-27T00:42:10+09:00 (Asia/Tokyo)`.
- Errori di un turno (connessione, timeout, errore HTTP, limite di passaggi): a capo se lo streaming era a metà, messaggio in italiano con la causa probabile, ritorno al prompt. I messaggi aggiunti nel turno fallito sono rimossi con `RemoveMessage`, così la cronologia torna a com'era prima del turno.
- `ChatOpenAI` con `max_retries=0` e timeout esplicito, perché gli errori emergano subito.

## 8. Log

Modulo `logging` su stderr, formato `ora livello nome: messaggio`, livello da `LOG_LEVEL`. A livello `INFO`:

- `modello: inizio chiamata` / `modello: fine chiamata (1,8 s, tool_calls=1)`;
- `strumenti: richiesta orologio {'fuso': 'Asia/Tokyo'}`;
- `strumenti: risultato orologio → 2026-10-27T00:42:10+09:00 (Asia/Tokyo)`;
- errori di un turno a livello `ERROR`.

Nel container gli stessi eventi sono leggibili con `docker logs -f assistente-demo`.

## 9. Docker

- `Dockerfile`: `python:3.14-slim`, installa solo `requirements.txt`, copia `assistente/`, `CMD ["python", "-m", "assistente"]`.
- `.dockerignore`: `.env`, `.venv/`, `.git/`, `__pycache__/`, `.pytest_cache/`, `tests/`, `docs/`, `Lezione3/`.
- `compose.yaml`: servizio `assistente`, `build: .`, `env_file: .env`, `environment: LM_BASE_URL=http://host.docker.internal:1234/v1`, `extra_hosts: ["host.docker.internal:host-gateway"]`, `stdin_open: true`, `tty: true`. Nessuna porta pubblicata.
- Avvio: `docker compose build` poi `docker compose run --rm --name assistente-demo assistente`.
- Se il container non raggiunge LM Studio, controllare indirizzo di ascolto di LM Studio («Serve on Local Network») e firewall; la soluzione verificata va nel README.

## 10. Test e verifiche

### Automatici (predefiniti, senza modello né rete)

`pytest` esegue di default solo questi (`pytest.ini`: `addopts = -m "not lmstudio and not docker"`).

| File | Cosa verifica |
|---|---|
| `test_strumenti.py` | Istante fisso: `Asia/Tokyo`, `Europe/Rome` in estate e in inverno, `UTC`; errore per fuso inesistente |
| `test_config.py` | Variabile mancante; fuso non valido; `/v1/models` simulato: modello presente, assente (elenco ID), server irraggiungibile |
| `test_grafo.py` | Modello finto con risposte prestabilite: senza `tool_calls` → `END`; con `orologio` → `strumenti` → `modello`, `ToolMessage` con l'ora attesa e `tool_call_id` corretto; strumento sconosciuto / argomenti errati → `ToolMessage` di errore; ciclo infinito → limite di passaggi |
| `test_cronologia.py` | Dopo due turni la cronologia contiene entrambe le domande e risposte senza duplicazioni; il modello riceve il primo scambio al secondo turno; messaggio di sistema non salvato nello stato; turno fallito → cronologia ripristinata |
| `test_terminale.py` | Modello finto in streaming e input da lista: token stampati in ordine, formato esatto della riga `[strumento]`, `esci` ed EOF chiudono, errore di connessione → messaggio e prompt successivo |

### Prove reali (attivate esplicitamente)

- `pytest -m lmstudio` (LM Studio avviato, `.env` valido): domanda «Che ore sono a Tokyo?». Supera solo se nello stato ci sono una chiamata `orologio` con `fuso="Asia/Tokyo"`, il `ToolMessage` corrispondente prodotto dal programma e una risposta finale successiva. Un caso di conversazione ordinaria («Ciao, come stai?») non deve chiamare lo strumento.
- `pytest -m docker` (Docker e LM Studio attivi, `.env` valido): costruisce l'immagine, esegue `docker compose run --rm -T assistente` con input preparato (domanda sull'ora, poi `esci`) e verifica nell'output la riga `[strumento] orologio(`.

Una risposta simulata non dimostra che il modello locale sappia usare lo strumento: il requisito sull'orologio è soddisfatto solo dalla prova `lmstudio` e dalla prova manuale con Compose.

## 11. Criteri di riuscita

1. Conversazione su più turni attraverso il grafo, con cronologia di sessione.
2. Una domanda sull'ora produce richiesta, esecuzione e risultato visibili nella traccia e nei log, seguiti dalla risposta del modello.
3. `docker compose run` avvia l'applicazione nel container collegata a LM Studio sull'host.
4. Test automatici verdi; prove reali eseguite e riportate separatamente.
5. README con configurazione, avvio, test e diagnosi verificati; `.env.example` sufficiente a preparare l'ambiente; `CLAUDE.md` coerente.
6. Commit leggibili in Conventional Commits; il push resta su richiesta.

## 12. Incrementi previsti (dettagliati nel piano)

1. Grafo con risposta fissa («Il grafo è in esecuzione.»), senza LLM.
2. Collegamento a LM Studio, streaming e cronologia.
3. Strumento orologio con instradamento, traccia e log.
4. Docker Compose.
5. Verifica completa e README.
