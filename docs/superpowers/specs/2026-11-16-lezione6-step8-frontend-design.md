# Lezione 6, step 8 — Front-end: interfaccia di chat, con streaming

Data: 2026-11-16. Estende lo step 7 (`2026-11-16-lezione6-step7-backend-design.md`).
Slide di riferimento: `LLM_Lez_6.pdf`, pagine 12, 15, 18 e 19.

## Perché

Serve un'interfaccia di chat utilizzabile da chi non conosce il progetto, che parla **solo con il back-end**
(slide 15). Evidenza minima (slide 19): conversazione completa dal browser, errori mostrati.

## Obiettivi

Una pagina web con:

1. elenco delle chat, creazione di una nuova chat ed eliminazione;
2. vista dei messaggi della chat scelta e invio di una nuova domanda;
3. stato di attesa durante la risposta ed errori mostrati in modo comprensibile, senza che la pagina si blocchi;
4. indirizzo del back-end preso da un file di configurazione, non scritto nel codice;
5. **streaming** lungo tutta la catena (slide 18, richiesto dallo studente): il testo compare mentre il modello lo
   scrive e l'interfaccia indica quando l'agente usa uno strumento.

Aspetto, in breve:

```
┌──────────────────┬───────────────────────────────────────────────┐
│ [+ Nuova chat]   │                         Che ore sono a Tokyo? │
│                  │ A Tokyo sono le 08:12 di lunedì.              │
│ ▸ Che ore sono … │ strumento: orologio(fuso="Asia/Tokyo")        │
│   Converti 10 k… │                                               │
│   Nuova chat  [x]│ L'agente sta rispondendo… 42 s                │
│                  ├───────────────────────────────────────────────┤
│ ● servizi attivi │ [ Scrivi una domanda…               ] [Invia] │
└──────────────────┴───────────────────────────────────────────────┘
```

- A sinistra le chat, dalla più recente, con titolo e pulsante per eliminare (con conferma).
- A destra i messaggi; sotto ogni risposta gli strumenti che l'agente ha usato.
- Durante l'attesa compare «L'agente sta rispondendo…» con i secondi trascorsi: con il modello locale una risposta
  richiede da mezzo minuto a qualche minuto, e senza contatore la pagina sembrerebbe ferma. Casella e pulsante
  restano disattivati finché arriva la risposta; le altre chat restano consultabili.
- In basso a sinistra lo stato dei servizi, letto da `GET /stato`: dice subito se l'agente o il modello sono spenti.
- Errore durante l'invio: riquadro rosso con il messaggio del back-end («Agente non raggiungibile: il messaggio non
  è stato salvato, riprova.») e la domanda resta nella casella, pronta per essere rimandata.

## Non obiettivi

- Prompt MCP nell'interfaccia; modifica del titolo; più utenti.
- Compose a quattro container (step 9): qui il front-end si serve in locale.

## Approcci considerati

1. **Pagina statica: HTML, CSS e JavaScript senza librerie** — scelto. Nessuna dipendenza e nessuna fase di
   compilazione; tutto il codice si legge in tre file; allo step 9 basta un container nginx che serve i file e fa
   da proxy verso il back-end, che è lo schema della slide 16.
2. Streamlit (Python). Si scriverebbe in poche righe, ma le chiamate al back-end partirebbero dal server Streamlit
   e non dal browser, l'aspetto è poco controllabile e il container porterebbe con sé un altro server Python.
3. React con Vite. È lo standard per interfacce grandi, ma aggiunge Node, dipendenze e compilazione per una pagina
   sola.

## Scelte di progetto

### File

```
frontend/
  index.html         struttura della pagina
  stile.css          aspetto (chiaro e scuro secondo il sistema, utilizzabile anche su schermo stretto)
  config.js          window.CONFIGURAZIONE = { backendUrl: "http://localhost:8002" }  ← unico posto con l'indirizzo
  api.js             una funzione per ogni operazione del documento OpenAPI del back-end; traduce gli errori
  app.js             logica della pagina: elenco, messaggi, invio, attesa, errori
  test/api.test.js   test di api.js con il test runner integrato di Node (nessuna dipendenza)
```

`api.js` è scritto a partire dal documento OpenAPI del back-end (slide 15: «il contratto»): un test Python
controlla che ogni percorso chiamato da `api.js` esista davvero in `/openapi.json`.

### Configurazione dell'indirizzo

`config.js` è l'unico file che contiene l'indirizzo del back-end. In locale vale `http://localhost:8002`; allo
step 9 il container lo sostituirà con `/api`, servito dal proxy.

### Modifica al back-end: CORS

Front-end (porta 8003) e back-end (porta 8002) in locale sono due «origini» diverse e il browser bloccherebbe le
chiamate. Il back-end guadagna la variabile `CORS_ORIGINI` (elenco separato da virgole, predefinito vuoto = nessuna
origine esterna ammessa); nel `.env` locale varrà `http://localhost:8003`. Con il proxy dello step 9 non servirà.

### Avvio locale

```powershell
.\.venv\Scripts\python.exe -m http.server 8003 --directory frontend
```

poi `http://localhost:8003` nel browser, con PostgreSQL, agente e back-end avviati.

### Sicurezza del testo

Le risposte del modello e i titoli si inseriscono nella pagina come testo (`textContent`), mai come HTML: una
risposta che contenesse tag non può modificare la pagina.

### Streaming (slide 18)

```
agente  POST /conversazione/stream        ──SSE──▶  back-end  POST /chat/{id}/messaggi/stream  ──SSE──▶  browser
```

Server-Sent Events: la risposta HTTP resta aperta e porta una sequenza di eventi `event: <tipo>` + `data: <JSON>`.

| Evento | Dati | Significato |
|---|---|---|
| `testo` | `{"testo": "..."}` | un frammento della bozza corrente, da aggiungere a quelli già arrivati |
| `strumento` | `{"nome", "argomenti", "risultato"}` | l'agente ha usato uno strumento; la bozza corrente è finita |
| `revisione` | `{"motivo"}` | il revisore ha bocciato la bozza: va scartata, ne arriva un'altra |
| `riassunto` | `{"messaggi_riassunti"}` | la cronologia è stata compressa |
| `fine` | agente: l'esito completo; back-end: `domanda`, `risposta`, `chat` salvati | il turno è finito |
| `errore` | `{"codice", "detail"}` | il turno è fallito dopo l'inizio del flusso; nulla è stato salvato |

- **Agente:** emette i frammenti man mano che il modello li genera, insieme agli eventi degli strumenti.
- **Back-end:** inoltra gli eventi al browser e salva domanda e risposta solo all'evento `fine`, poi manda il suo
  `fine` con i messaggi salvati. Gli errori che avvengono prima dell'inizio del flusso restano normali risposte
  HTTP (404, 422, 502, 503).
- **Front-end:** mostra il testo mentre arriva; a `strumento` mostra lo strumento usato; a `fine` sostituisce la
  bozza con il messaggio salvato.
- **Decisione con il revisore attivo (slide 18):** si mostra la bozza mentre viene scritta. Se il revisore la boccia,
  la bozza viene tolta, compare la nota «Il revisore ha chiesto una correzione: <motivo>» e parte la risposta nuova.
  Motivo: con un modello locale lento, aspettare la risposta approvata vorrebbe dire minuti di schermo fermo.
- Gli endpoint senza streaming dello step 6 e 7 restano: li usano la CLI e i test.
- Limite accettato: se il browser chiude la pagina a metà risposta, quello scambio non viene salvato.

## Test

- Agente e back-end: eventi nell'ordine giusto con il modello finto; errore a metà flusso → evento `errore` e nulla
  salvato; errori prima del flusso → codici HTTP; il back-end salva solo a `fine`.

- `node --test frontend/test/`: lettura degli eventi SSE anche spezzati a metà tra due pacchetti; `api.js` con un
  `fetch` finto: indirizzi e metodi corretti, corpo JSON dell'invio,
  errore del back-end tradotto nel suo `detail`, back-end spento tradotto in «Back-end non raggiungibile».
- Python: i percorsi usati da `api.js` esistono nell'OpenAPI del back-end; `config.js` è l'unico file del
  front-end che contiene un indirizzo `http://`; CORS: origine ammessa e origine non ammessa.
- Prova reale nel browser (Chrome), con tutti i servizi accesi: creare una chat, chiedere «Che ore sono a Tokyo?»
  e vedere risposta e strumento; ricaricare la pagina e riavviare il back-end: la chat c'è ancora; spegnere
  l'agente e inviare: compare l'errore, la pagina resta utilizzabile; eliminare una chat.

## Consegna

Un commit `feat(frontend): interfaccia di chat nel browser`, poi push. README (step 8, avvio, cosa si vede, come
cambiare l'indirizzo del back-end), `.env.example` (`CORS_ORIGINI`), `CLAUDE.md`.
