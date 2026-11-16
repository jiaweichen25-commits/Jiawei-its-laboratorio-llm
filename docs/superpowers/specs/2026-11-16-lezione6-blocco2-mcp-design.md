# Lezione 6, blocco 2 — Resource e prompt MCP (step 4–5)

Data: 2026-11-16. Estende il blocco 1 (`2026-11-15-lezione6-blocco1-grafo-design.md`).
Le slide di riferimento sono `LLM_Lez_6.pdf`, pagine 7–11 e 19.

## Perché

Nella lezione 5 il server MCP esponeva solo **tool**, che decide il modello. La slide 11 distingue
tre primitive secondo **chi** le attiva:

| Primitiva | Chi la attiva | Quando | Nei log |
|---|---|---|---|
| Tool | il modello | durante il ciclo | `tools/call` a ogni richiesta |
| Resource | l'applicazione (host) | prima di chiamare il modello | `resources/read` una volta, a inizio sessione |
| Prompt | l'utente | quando sceglie un compito | `prompts/get` solo con `/prompt` |

Questo blocco aggiunge al server una resource (step 4) e due prompt (step 5), e all'host il codice per usarli.
L'errore da evitare, che la slide 11 indica esplicitamente, è esporre tutto come tool.

## Obiettivi

### Step 4 · Resource `utente://preferenze`

- Un file `preferenze.json` nella cartella del progetto, versionato perché non contiene segreti:

  ```json
  {"lingua": "italiano", "fuso_predefinito": "Europe/Rome", "stile": "sintetico"}
  ```

  `stile` vale `sintetico` (risposte brevi) oppure `dettagliato` (risposte complete con spiegazioni).
- Il server MCP espone il contenuto come resource `utente://preferenze` (`application/json`). Rilegge il file a
  ogni lettura, quindi basta modificarlo e riavviare la sessione.
- All'avvio l'host legge la resource una sola volta (`resources/read`) e la valida. Le preferenze entrano **in
  cima** al messaggio di sistema dell'agente, prima del riassunto e delle istruzioni sugli strumenti.
- La resource non è un tool: non compare tra gli strumenti passati a `bind_tools` e il modello non può «chiamarla».
- Resource non disponibile o non valida (file mancante, JSON rotto, fuso inesistente, stile sconosciuto): valori
  predefiniti, cioè `italiano`, il fuso di `TZ_PREDEFINITO` e `sintetico`, con un log `WARNING` che dice perché.

### Step 5 · Prompt riusabili nella CLI

- Il server espone due prompt:
  - `spiega(argomento, livello="base")`, dove livello vale base, intermedio o avanzato;
  - `riassumi_conversazione(stile="sintetico")`, che chiede di riassumere i turni della sessione corrente.
- Comandi nuovi del terminale (MCP non ne definisce di standard, slide 10):
  - `/prompts` elenca nome, descrizione e argomenti di ogni prompt, indicando quali sono obbligatori;
  - `/prompt nome chiave=valore ...` richiede il prompt al server (`prompts/get`) e manda i messaggi ottenuti al
    grafo come una domanda qualsiasi, quindi passano da riassunto, router, strumenti e revisore. I valori con spazi
    vanno tra virgolette: `/prompt spiega argomento="Model Context Protocol" livello=base`.
- Il controllo degli argomenti lo fa l'host, sull'elenco ricevuto da `prompts/list`. Prompt sconosciuto, argomento
  obbligatorio mancante o argomento sconosciuto bloccano la richiesta con un messaggio chiaro, senza chiamare né il
  server né il modello. Il secondo controllo serve davvero: provato oggi, FastMCP accetta in silenzio un argomento
  sconosciuto.
- Un comando che inizia con `/` ma non esiste dà «comando sconosciuto» senza chiamare il modello.

## Non obiettivi

- Nessuno degli step 6–9 (API, back-end, front-end, Compose).
- Le risposte fisse dell'applicazione (rifiuto, messaggi di errore, righe `[strumento]`) restano in italiano anche
  se `lingua` è un'altra: la preferenza vale per le risposte del modello.
- Il server non controlla i valori di `livello` e `stile` dei prompt: sono testo che il modello interpreta.
- Nessuna rilettura delle preferenze a sessione aperta.

## Approcci considerati

**Come arrivano le preferenze al modello**

1. **Resource letta dall'host all'avvio e messa nel prompt di sistema** — scelto. È esattamente lo schema delle
   slide 7–8.
2. Tool `leggi_preferenze` che il modello chiama quando vuole. Funziona, ma è l'«errore comune» della slide 11: il
   modello potrebbe non chiamarlo e la risposta cambierebbe da una volta all'altra.
3. Preferenze lette dal file direttamente dall'agente, senza MCP. Più semplice, ma salta il punto dell'esercizio.

**Come i messaggi del prompt MCP diventano messaggi LangChain**

1. **Conversione fatta da noi nel `ClienteMCP`** (ruolo `user` → `HumanMessage`, ruolo `assistant` → `AIMessage`)
   — scelto. Sono poche righe, nessuna dipendenza nuova, e usa la stessa sessione sincrona già aperta per i tool.
2. `load_mcp_prompt` di `langchain-mcp-adapters`, come nel frammento della slide 9. Aggiunge una dipendenza e
   richiede una sessione asincrona, mentre il nostro client è già un adattatore sincrono scritto per la lezione 5.

## Scelte di progetto

### Server (`server_mcp.py`)

- `crea_server(adesso=..., percorso_preferenze=...)`: il percorso si sostituisce nei test. Il processo reale lo
  legge dalla variabile `PREFERENZE_FILE` se presente, altrimenti usa `preferenze.json` nella radice del progetto.
- La resource restituisce il testo del file così com'è. Se il file manca, il server segnala un errore MCP e l'host
  ripiega sui predefiniti.

### Client (`client_mcp.py`)

- Al momento della discovery, oltre a `tools/list`, scarica anche `prompts/list`.
- `ClienteMCP.leggi_risorsa(uri) -> str`, sincrono come `chiama`, con log `mcp: resources/read <uri>`.
- `ClienteMCP.elenco_prompt()` restituisce il catalogo salvato all'avvio.
- `ClienteMCP.ottieni_prompt(nome, argomenti) -> list[BaseMessage]`, con log
  `mcp: prompts/get <nome> argomenti=... messaggi=...`.

### Preferenze (modulo nuovo `preferenze.py`)

- Modello Pydantic `Preferenze`: `lingua: str` non vuota, `fuso_predefinito` valido IANA, `stile` tra `sintetico` e
  `dettagliato`.
- `carica_preferenze(leggi: Callable[[], str], fuso_di_riserva: str) -> Preferenze` non solleva mai: in caso di
  errore restituisce i predefiniti e scrive il `WARNING`.
- Il fuso delle preferenze **vince** su `TZ_PREDEFINITO`, che resta il valore di riserva. Va scritto nel README
  perché cambia il comportamento della lezione 4.

### Grafo

- `costruisci_grafo(..., preferenze: Preferenze | None = None)`. Senza preferenze il messaggio di sistema resta
  identico a quello attuale («Rispondi in italiano. ...»), così i test esistenti non cambiano.
- Con le preferenze, in cima: «Preferenze dell'utente: rispondi in <lingua>; se non indica un fuso orario usa
  <fuso>; stile <frase per lo stile>». Poi l'eventuale riassunto, poi le istruzioni sugli strumenti, dove la
  lingua e il fuso fissi lasciano posto a quelli delle preferenze.

### Terminale (`terminale.py` + modulo nuovo `comandi.py`)

- `comandi.py` contiene logica pura, testabile senza server: interpretare la riga (`shlex`, che gestisce le
  virgolette), validare gli argomenti contro il catalogo e formattare l'elenco per `/prompts`.
- `conversa(..., prompt_mcp=None)`: riceve un oggetto con `elenco_prompt()` e `ottieni_prompt()`, cioè il
  `ClienteMCP` nell'applicazione e un finto nei test. Senza `prompt_mcp`, `/prompts` risponde che i prompt non sono
  disponibili.
- Il turno accetta una lista di messaggi invece di una sola domanda: una domanda normale è
  `[HumanMessage(domanda)]`, un prompt è la lista restituita dal server.

### Docker

`preferenze.json` va copiato nell'immagine (riga nel `Dockerfile`). Lo `stdio` del server parte nello stesso
container, come nella lezione 5.

## Test

Automatici, senza modello e con server MCP in memoria:

- server: la resource compare in `resources/list` e non tra i tool; contenuto letto dal file indicato; file mancante
  dà errore MCP; i due prompt con i loro argomenti (obbligatori e facoltativi) e i messaggi resi.
- preferenze: file valido; JSON rotto, fuso inesistente, stile sconosciuto, resource assente → predefiniti e
  `WARNING`.
- client: `leggi_risorsa`, `elenco_prompt`, `ottieni_prompt` con conversione dei ruoli; i tool generati
  dall'adattatore restano tre.
- grafo: preferenze in cima al messaggio di sistema; fuso `America/New_York` nel testo; senza preferenze testo
  invariato.
- comandi: interpretazione con virgolette; prompt sconosciuto, obbligatorio mancante, argomento sconosciuto,
  sintassi `chiave=valore` sbagliata; formattazione di `/prompts`.
- terminale: `/prompt` con argomenti validi aggiunge i messaggi e il modello risponde; con argomenti non validi il
  modello non viene chiamato; comando sconosciuto.

Reali, con marker `lmstudio`:

- preferenze in un file temporaneo con `fuso_predefinito: America/New_York` (passato con `PREFERENZE_FILE`):
  «Che ore sono?» → chiamata a `orologio` con `America/New_York`;
- `lingua: inglese` → la risposta a «Ciao, come stai?» è in inglese;
- `/prompt spiega argomento="Model Context Protocol" livello=base` → risposta non vuota che parla di MCP;
- `riassumi_conversazione` dopo due turni → la risposta cita entrambi.

## Lasciato a chi implementa

Testo esatto dei prompt `spiega` e `riassumi_conversazione` e della frase per lo stile; formato preciso di
`/prompts`.

## Consegna

- Due commit, uno per step: `feat(mcp): resource con le preferenze dell'utente` e
  `feat(mcp): prompt riusabili con /prompts e /prompt`. Push solo su richiesta.
- README (step 4 e 5, la tabella delle tre primitive, i comandi nuovi), `.env.example` (`PREFERENZE_FILE`
  commentata), `CLAUDE.md` (struttura) aggiornati.
