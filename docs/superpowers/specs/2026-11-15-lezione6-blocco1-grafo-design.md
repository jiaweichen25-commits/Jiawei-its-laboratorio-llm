# Lezione 6, blocco 1 — Router, revisore e riassunto (step 1–3)

Data: 2026-11-15. Estende il progetto della lezione 5 (`2026-11-09-lezione5-mcp-design.md`).
Le slide di riferimento sono `LLM_Lez_6.pdf`, pagine 3–6 e 19.

## Perché

La lezione 6 fa evolvere l'agente in nove step. Questo documento copre i primi tre, che toccano solo il
grafo: lo stesso modello viene chiamato con prompt di sistema diversi per fare tre lavori nuovi. Gli step
4–9 (resource e prompt MCP, API, back-end, front-end, Compose) avranno documenti propri.

## Obiettivi

Il grafo passa da due a sei nodi:

```
START → riassunto → router ─┬─ in ambito ──→ modello ⇄ strumenti
                            │                   │ (nessuno strumento richiesto)
                            │                   ▼
                            │                revisore ─┬─ coerente, o limite raggiunto → END
                            │                          └─ non coerente + motivo → modello
                            └─ fuori ambito → rifiuto → END
```

Il nodo dell'agente continua a chiamarsi `modello`, così il codice e i test esistenti restano validi.

1. **Router (step 1).** Decide se la domanda rientra nell'ambito dell'agente. Fuori ambito: risposta di
   rifiuto, il nodo `modello` non viene eseguito. Il router non sa nulla degli strumenti.
2. **Revisore (step 2).** Controlla che la risposta risponda a tutta la domanda. Se no, il motivo torna
   all'agente, che riscrive; dopo un numero massimo di revisioni si restituisce l'ultima risposta.
3. **Riassunto (step 3).** A inizio turno, se la cronologia supera una soglia, i messaggi vecchi sono
   sostituiti da un riassunto e restano gli ultimi N.

## Non obiettivi

- Nessuno degli step 4–9. In particolare la CLI resta com'è: diventerà client dell'API allo step 6.
- Il revisore giudica la coerenza con la domanda, non la verità dei fatti.
- Nessuna stima dei token: la soglia del riassunto è in numero di messaggi.

## Da evitare

- Un router o un revisore che, quando il modello locale risponde male, blocca l'utente. Se l'output non è
  leggibile si lascia passare e lo si scrive nei log.
- Test esistenti riscritti in massa: i 135 test della lezione 5 devono continuare a passare.

## Scelte di progetto

### Stato

`StatoAgente` estende `MessagesState` con:

| Campo | Tipo | Uso |
|---|---|---|
| `riassunto` | `str` | testo unico, **sostituito** a ogni compressione (non accumulato) |
| `revisioni` | `int` | revisioni fatte nel turno corrente; azzerato dall'ingresso del turno (`"revisioni": 0` passato da chi invoca il grafo), così non dipende da quale nodo è acceso |
| `categoria` | `str` | decisione del router, letta dall'arco condizionale |

### Configurazione (variabili d'ambiente, tutte facoltative)

| Variabile | Predefinito | Significato |
|---|---|---|
| `AMBITO_AGENTE` | vedi sotto | descrizione in italiano di ciò di cui l'agente si occupa |
| `LIMITE_REVISIONI` | `2` | quante volte il revisore può rimandare indietro una risposta; `0` lo spegne |
| `SOGLIA_RIASSUNTO` | `12` | oltre questo numero di messaggi si riassume; `0` lo spegne |
| `MESSAGGI_DA_CONSERVARE` | `6` | quanti messaggi recenti restano intatti |

Ambito predefinito: «Assistente del laboratorio del corso su LLM e agenti: saluti e conversazione sulla
sessione in corso, spiegazioni su LLM, agenti, MCP e argomenti di informatica, data e ora nei fusi orari,
calcoli aritmetici, conversioni di unità di misura.» Comprende le spiegazioni perché allo step 5 il prompt
`spiega` passerà dal router.

`costruisci_grafo` riceve queste opzioni; un nodo spento non viene aggiunto al grafo. Chiamata senza opzioni,
la funzione costruisce il grafo della lezione 5: è così che i test esistenti restano invariati. L'applicazione
passa sempre le opzioni lette dalla configurazione.

### Output strutturato (router e revisore)

Tre modi considerati:

1. **`response_format` con schema JSON + validazione Pydantic** — scelto. LM Studio vincola la generazione
   allo schema, quindi anche un modello piccolo produce JSON valido; il codice valida comunque con Pydantic.
   Nei test basta un modello finto che restituisce una stringa JSON.
2. JSON chiesto solo nel prompt e letto a mano. Funziona ovunque, ma un modello locale sbaglia spesso il formato.
3. Tool calling con uno strumento «decidi». Mescola le decisioni di controllo con gli strumenti veri, che la
   slide chiede di tenere separati.

Schemi:

- router: `{"categoria": "conversazione" | "fuori_ambito", "motivo": str}`
- revisore: `{"coerente": bool, "motivo": str}`

Output non valido o errore di validazione: il router vale «conversazione», il revisore vale «coerente»; in
entrambi i casi un log `WARNING` con l'output ricevuto.

### Router

- Riceve l'ambito, l'eventuale riassunto e gli ultimi 4 messaggi (serve per i seguiti tipo «e a Tokyo?»).
- Log: `router: categoria=... motivo=...`.
- `rifiuto` non chiama il modello: aggiunge un `AIMessage` fisso che dice che la richiesta è fuori ambito e
  riporta l'ambito.

### Revisore

- Parte quando `modello` risponde senza chiedere strumenti.
- Riceve l'ultima domanda dell'utente, i risultati degli strumenti del turno e la risposta proposta.
- Non coerente e `revisioni < limite`: aggiunge alla cronologia un `HumanMessage` che inizia con
  `[Revisione]` e contiene il motivo, incrementa `revisioni`, torna a `modello`. È un messaggio utente e non
  di sistema perché molti modelli locali rifiutano un messaggio di sistema a metà conversazione.
- Limite raggiunto: resta l'ultima risposta, log `WARNING revisore: limite di revisioni raggiunto`.
- La bozza scartata e l'indicazione restano in cronologia (slide 5, punto 3).
- Nel terminale la bozza si vede mentre viene scritta; se è scartata compare una riga
  `[revisore] non coerente: <motivo>` e poi la nuova risposta. Scelta semplice e trasparente, da documentare
  nel README (la slide 18 chiede di dichiararla).

### Riassunto

- Primo nodo del turno.
- Sotto la soglia non chiama il modello.
- Sopra: il taglio cade su un `HumanMessage`, il più vicino a «ultimi N» andando indietro. Così una richiesta
  di strumento non viene mai separata dal suo `ToolMessage`. Se non c'è un punto di taglio valido non si riassume.
- Il modello riceve il riassunto precedente e i messaggi da togliere e produce il nuovo riassunto, in testo libero.
- I messaggi vecchi escono dallo stato con `RemoveMessage`; `riassunto` è sostituito.
- Il riassunto entra nel messaggio di sistema dell'agente («Riassunto della conversazione finora: …») ed è
  passato anche al router.
- Log: `riassunto: messaggi prima=14 dopo=7`.

### Altro

- `LIMITE_PASSAGGI` sale da 10 a 16: i nodi nuovi consumano passaggi. Il test del limite resta valido.
- Il terminale mostra tre righe di traccia nuove (`[router]`, `[revisore]`, `[riassunto]`) e stampa il testo
  del rifiuto, che non arriva dal nodo `modello`.
- Nessuna dipendenza nuova.

## Test

Automatici, con modello finto:

- router: percorso in ambito (log con categoria e motivo, `modello` eseguito); percorso fuori ambito
  (rifiuto, `modello` mai chiamato); output non valido → passa.
- revisore: approvazione al primo passaggio; rifiuto motivato poi risposta nuova; revisore che rifiuta sempre
  → si ferma al limite con l'ultima risposta.
- riassunto: sotto soglia nessuna chiamata al modello; sopra soglia conteggio prima/dopo, riassunto
  sostituito, coppia richiesta-strumento/`ToolMessage` mai separata; il riassunto compare nel messaggio di sistema.
- configurazione: valori predefiniti e valori non validi.
- terminale: righe di traccia e testo del rifiuto.

Reali, marker `lmstudio`:

- domanda in ambito («Che ore sono a Tokyo?») → strumento usato;
- domanda fuori ambito («Dammi la ricetta della carbonara») → rifiuto, nessuna chiamata a strumenti;
- domanda in due parti («Che ore sono a Tokyo e quanto fa 12 × 8?») → risposta finale con entrambe le parti;
- nome dato al primo turno e richiesto dopo la compressione, con soglia bassa.

Una prova reale che fallisce va riportata con il punto esatto, senza dichiarare completato lo step.

## Lasciato a chi implementa

Testo esatto dei prompt di sistema di router, revisore e riassunto; nomi delle funzioni interne; dove vive
il codice dei nodi (in `grafo.py` o in un modulo `nodi.py` se `grafo.py` diventa troppo lungo).

## Consegna

- Tre commit, uno per step, ciascuno con test verdi: `feat(grafo): router ...`, `feat(grafo): revisore ...`,
  `feat(grafo): riassunto ...`. Push solo su richiesta.
- README e `.env.example` aggiornati con le variabili nuove; `CLAUDE.md` aggiornato nella struttura del grafo.
- Codice commentato dove serve a spiegarlo all'orale, come nella lezione 5.
