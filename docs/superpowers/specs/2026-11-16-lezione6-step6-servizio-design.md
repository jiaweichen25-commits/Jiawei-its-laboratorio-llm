# Lezione 6, step 6 — L'agente come servizio HTTP

Data: 2026-11-16. Estende i blocchi 1 e 2. Slide di riferimento: `LLM_Lez_6.pdf`, pagine 12–13 e 19.

## Perché

Gli step 7–9 portano a un'applicazione web con quattro container: front-end, back-end, agente e PostgreSQL.
Perché il back-end possa usare l'agente, l'agente deve diventare un **servizio HTTP**: riceve la conversazione e
restituisce la risposta. Lo stesso grafo deve servire sia la CLI sia le chiamate HTTP, senza duplicare la logica
(slide 13). Evidenza minima da consegnare: **stessa risposta dalla CLI e dall'API** (slide 19).

## Obiettivi

1. Un servizio FastAPI dell'agente (`servizio_agente.py`), avviato con uvicorn sulla porta 8001 (la 8000 resta
   all'orologio della lezione 5).
2. `POST /conversazione`: riceve la cronologia, il riassunto e una domanda **oppure** un prompt MCP; esegue il grafo
   e restituisce risposta, strumenti usati, cronologia aggiornata e riassunto aggiornato.
3. `GET /prompts`: il catalogo dei prompt MCP, per `/prompts` e `/prompt` della CLI.
4. `GET /stato`: dice se agente, server MCP e modello sono raggiungibili.
5. **Agente senza stato:** nessuna memoria tra una richiesta e l'altra. Cronologia e riassunto arrivano dal chiamante
   e tornano aggiornati; sarà il back-end dello step 7 a salvarli.
6. La CLI (`python -m assistente`) diventa un **client dell'API**: manda le domande al servizio e mostra le risposte.

## Non obiettivi

- Streaming della risposta fino al client (slide 18): è una richiesta facoltativa e verrà valutata con il front-end
  allo step 8. La CLI mostrerà la risposta quando è completa, preceduta da una riga di attesa.
- Back-end, database, front-end, Compose a quattro servizi (step 7–9).
- Autenticazione: il servizio è pensato per stare dietro al back-end, non esposto (step 9).

## Approcci considerati

**Che cosa è «la CLI che diventa client»**

1. **La CLI chiama il servizio via HTTP** — scelto. È ciò che chiede la slide 13 e dimostra l'evidenza «stessa
   risposta da CLI e API», perché le due strade finiscono nello stesso endpoint.
2. La CLI continua a eseguire il grafo nel proprio processo e il servizio è un secondo punto d'ingresso. È più
   semplice e mantiene lo streaming, ma non è «la CLI client dell'API» e le due strade restano distinte.

**Che cosa contiene la cronologia scambiata via HTTP**

1. **Solo i messaggi visibili in una chat:** `{"ruolo": "utente" | "assistente", "testo": "..."}` — scelto. È lo
   stesso formato che il back-end salverà e il front-end mostrerà, leggibile nella documentazione OpenAPI. Le
   richieste di strumento, i `ToolMessage` e le indicazioni del revisore restano dentro il turno; gli strumenti usati
   tornano a parte in `strumenti_usati`. Il prezzo: ai turni successivi il modello vede la risposta che ha dato, non
   il risultato grezzo dello strumento.
2. Tutti i messaggi LangChain serializzati (`messages_to_dict`). Conserva tutto, ma espone ai client un formato
   interno di LangChain e complica back-end e front-end.

## Scelte di progetto

### Contratto `POST /conversazione`

Richiesta:

```json
{
  "cronologia": [{"ruolo": "utente", "testo": "Mi chiamo Jiawei"}, {"ruolo": "assistente", "testo": "Piacere!"}],
  "riassunto": "",
  "domanda": "Che ore sono a Tokyo?",
  "prompt": null
}
```

`domanda` e `prompt` (`{"nome": "spiega", "argomenti": {"argomento": "MCP"}}`) sono alternativi: esattamente uno dei
due, altrimenti 422.

Risposta 200:

```json
{
  "risposta": "A Tokyo sono le 08:12.",
  "strumenti_usati": [{"nome": "orologio", "argomenti": {"fuso": "Asia/Tokyo"}, "risultato": "2026-11-16T08:12:00+09:00 (Asia/Tokyo), lunedì"}],
  "cronologia": [... la cronologia ricevuta, più la domanda (o il testo del prompt) e la risposta ...],
  "riassunto": "",
  "rifiutata": false,
  "revisioni": 0
}
```

Con il riassunto acceso, la cronologia restituita può essere **più corta** di quella inviata: il chiamante deve
sostituire la propria con quella ricevuta.

### Errori (slide 13, «codice e messaggio comprensibili»)

| Situazione | Codice | `detail` |
|---|---|---|
| richiesta malformata, domanda e prompt entrambi o nessuno | 422 | dalla validazione FastAPI |
| prompt sconosciuto o argomenti non validi | 422 | il messaggio di `comandi.py` |
| LM Studio non raggiungibile | 503 | «Connessione a LM Studio fallita: ...» (da `descrivi_errore`) |
| LM Studio non risponde in tempo | 504 | «Attesa scaduta: LM Studio non ha risposto in tempo.» |
| server MCP non disponibile per un prompt | 503 | «Errore di collegamento MCP: ...» |
| troppi passaggi tra modello e strumenti | 500 | «Troppi passaggi tra modello e strumenti: turno interrotto.» |

Un errore di uno strumento (fuso sbagliato) non è un errore HTTP: il modello lo riceve e risponde, come oggi.

### Timeout e risposte lunghe

Nella prova dello step 5 una spiegazione ha richiesto 260 s. Il servizio esegue il grafo con `stream` e raccoglie
il risultato, come fa il terminale: così il timeout di 120 s del modello vale tra un frammento e l'altro e non
sull'intera risposta. La CLI aspetta il servizio fino a `AGENTE_TIMEOUT` secondi (predefinito 600).

### `GET /stato`

```json
{"agente": "ok", "server_mcp": "ok", "modello": "ok", "dettagli": {...}}
```

200 se tutto è raggiungibile, 503 con il dettaglio di ciò che manca. Il modello si controlla con lo stesso
`GET /models` della lezione 4.

### Struttura

- `agente.py` (nuovo): `Agente`, che costruisce una volta grafo, client MCP e preferenze e offre
  `rispondi(cronologia, riassunto, messaggi_nuovi) -> EsitoTurno`. Contiene la logica oggi sparsa in `__main__.py` e
  `terminale.py` (avvio del client MCP, preferenze, opzioni, esecuzione di un turno). Il grafo gira **senza
  checkpointer**: lo stato del turno nasce dalla richiesta.
- `servizio_agente.py` (nuovo): app FastAPI con i tre endpoint; `crea_app(agente)` per i test con un agente costruito
  su `ModelloFinto`. Avvio:
  `.\.venv\Scripts\python.exe -m uvicorn assistente.servizio_agente:app --port 8001`.
- `terminale.py`: la CLI parla con un `ClienteAgente` (nuovo, `httpx`) invece che con il grafo. Mantiene la
  cronologia e il riassunto della sessione, `/prompts` (da `GET /prompts`), `/prompt` (interpretazione e controllo
  locali con `comandi.py`, poi `POST /conversazione` con `prompt`), le righe `[strumento]`, `[revisore]` e
  `[riassunto]` ricavate dalla risposta.
- `config.py`: `AGENTE_URL` (predefinito `http://localhost:8001`) e `AGENTE_TIMEOUT` (600) per la CLI.
- Docker: in questo step il `compose.yaml` avvia il **servizio** dell'agente con la porta 8001 pubblicata, così la
  CLI locale può usarlo. Lo step 9 lo nasconderà dietro il back-end.

## Test

Automatici, senza modello (`TestClient` di FastAPI e agente con `ModelloFinto`):

- domanda semplice; domanda con uno strumento (`strumenti_usati` compilato); domanda fuori ambito (`rifiutata: true`);
  cronologia e riassunto ricevuti e restituiti; prompt valido; prompt non valido → 422; domanda e prompt insieme →
  422; LM Studio spento → 503; timeout → 504; troppi passaggi → 500;
- `/stato` con tutto attivo e con il modello spento;
- `/openapi.json` contiene i tre endpoint e gli schemi;
- CLI: con un servizio finto (`httpx.MockTransport`) mostra risposta e tracce, aggiorna la cronologia, gestisce
  `/prompts`, `/prompt` e il servizio spento con un messaggio chiaro.

Reali (`lmstudio`): una domanda che usa l'orologio inviata sia con la CLI sia con una chiamata HTTP diretta: stesso
strumento, stessi argomenti, risposta coerente (il testo può variare); servizio avviato con uvicorn come
sottoprocesso.

## Consegna

Un commit `feat(api): agente come servizio HTTP senza stato e CLI client`, poi push. README (avvio del servizio,
`/docs`, esempi `Invoke-RestMethod`, tabella degli errori), `.env.example`, `CLAUDE.md` (struttura e comandi).
