# Lezione 5 — Tre varianti dell'orologio e due strumenti MCP

Data: 2026-11-09. Estende il progetto della lezione 4 (`2026-10-26-assistente-laboratorio-design.md`).

## Obiettivo

Dalle slide della lezione 5:

- **Slide 17 (blocco 4):** lo stesso orologio raggiunto in tre modi — chiamata locale, FastAPI + wrapper HTTP,
  FastMCP + client/adattatore. Domanda, modello e contratto restano uguali; cambia solo il percorso. Una sola
  variante è esposta al modello per volta.
- **Slide 25 (blocco 5):** due proposte aggiunte come tool MCP: **Calcolatrice sicura** e **Convertitore di
  unità** (entrambe «Base»).
- **Slide 30–31 (laboratorio):** una domanda all'agente attiva un tool MCP; il risultato torna al modello come
  `ToolMessage` correlato; discovery dal server, errori controllati, log, cronologia e limite ai passaggi intatti.

Successo: ogni variante risponde a «Che ore sono a Tokyo?» con una chiamata reale tracciata nei log; un fuso
non valido dà un errore senza ora inventata; calcolatrice e convertitore funzionano tramite MCP e rifiutano
input non validi.

## Contratti (uguali in tutte le varianti)

| Tool | Argomenti | Risultato | Errori |
|---|---|---|---|
| `orologio` | `fuso`: nome IANA (es. `Asia/Tokyo`) | `2026-11-09T22:15:00+09:00 (Asia/Tokyo), lunedì` | `Errore: fuso orario sconosciuto: «Mars/Olympus»` |
| `calcola` | `espressione`: stringa aritmetica | `(2+3)*4 = 20` | sintassi non valida, operazione non consentita (nomi, chiamate, attributi…), divisione per zero, numeri o esponenti troppo grandi, espressione oltre 200 caratteri |
| `converti` | `valore`: numero; `da`, `a`: unità da elenco chiuso | `10 km = 6.21371 mi` | unità di categorie diverse (es. `kg` → `m`); unità fuori elenco rifiutata dallo schema |

Unità ammesse (elenco chiuso, nello schema come `enum`): lunghezza `mm cm m km in ft mi`; massa `g kg lb oz`;
temperatura `C F K` (conversione con offset, non solo fattore).

La calcolatrice usa `ast` (albero sintattico) senza `eval`: sono ammessi solo numeri, `+ - * / // % **` e il
segno unario. Ogni altro nodo è rifiutato in modo esplicito.

## Architettura

```
assistente/
  logica.py        logica pura: ora_nel_fuso, calcola, converti (nessuna dipendenza da LangChain o rete)
  strumenti.py     variante LOCALE: @tool orologio che chiama logica.ora_nel_fuso   (esiste, si riusa)
  servizio_api.py  servizio FastAPI: GET /orologio?fuso=...  (avvio con uvicorn, porta 8000)
  wrapper_http.py  variante FASTAPI: @tool orologio scritto a mano che chiama l'endpoint con httpx
  server_mcp.py    server FastMCP (stdio): tool orologio, calcola, converti
  client_mcp.py    variante MCP: client persistente + adattatore catalogo → tool LangChain
  config.py        + VARIANTE_OROLOGIO (locale | fastapi | mcp, predefinita mcp) e OROLOGIO_API_URL
  __main__.py      sceglie la variante e costruisce l'elenco degli strumenti
  grafo.py         invariato tranne il log, che aggiunge call_id e variante
```

**Selezione degli strumenti.** Il server MCP viene sempre avviato (porta `calcola` e `converti`).
Con `VARIANTE_OROLOGIO=mcp` si usano tutti e tre i tool del catalogo. Con `locale` o `fastapi` l'host scarta
`orologio` dal catalogo MCP e aggiunge la propria versione, così il modello vede un solo `orologio` (slide 11:
«l'host seleziona le capacità consentite»).

**Discovery reale.** L'adattatore legge nome, descrizione e `inputSchema` da `tools/list`; nell'agente non c'è
nessuno schema MCP scritto a mano (slide 20). Ogni voce diventa uno `StructuredTool` con quello schema e una
funzione che invoca `tools/call`.

**Sincrono e asincrono (slide 22).** Il grafo è sincrono, il client MCP è asincrono. `client_mcp.py` tiene un
event loop in un thread di servizio e una sola sessione stdio aperta per tutta la durata del programma; le
chiamate sincrone del nodo strumenti vengono inoltrate a quel loop e attese con timeout. Alla chiusura la
sessione e il sottoprocesso vengono terminati. Il server scrive i log solo su stderr: stdout è riservato al
protocollo (slide 13).

**FastAPI.** Il servizio va avviato a parte. Il wrapper ha timeout di 5 s e traduce gli errori in testo:
HTTP 400 → errore del fuso (dal servizio); connessione rifiutata/timeout → «Errore di collegamento al servizio
orologio» (distinto dal fuso non valido, slide 23).

## Errori e log

- Errore dello strumento (fuso, espressione, unità): testo `Errore: ...` restituito come risultato, nessun falso
  successo.
- Errore di collegamento (servizio HTTP spento, server MCP caduto): testo `Errore di collegamento ...`, distinto
  dal precedente.
- Server MCP che non parte o catalogo vuoto all'avvio: messaggio chiaro ed uscita con codice 1, come per LM Studio.
- Log del nodo strumenti nel formato della slide 23: `variante=mcp tool=orologio call_id=... argomenti=...
  esito=ok|errore risultato=...`.

## Docker

L'immagine contiene anche `server_mcp.py`, quindi la variante `mcp` (stdio, sottoprocesso nello stesso
container) funziona con `docker compose run` come prima. La variante `fastapi` è documentata solo in locale.

## Dipendenze nuove (versioni fissate)

- `fastmcp` — server MCP e client (slide 20); porta con sé `mcp`, `httpx`, `uvicorn`.
- `fastapi` — servizio della variante 2 (slide 19).
- `httpx` e `uvicorn` fissati esplicitamente perché usati direttamente dal codice.

## Test

Automatici, senza modello:

- logica: orologio con istante fisso; calcolatrice (casi validi, `__import__('os')`, `2**99999`, `1/0`, sintassi
  errata); convertitore (lunghezze, massa, temperatura, categorie incompatibili).
- FastAPI: `TestClient` su `/orologio` valido e non valido.
- wrapper HTTP: risposte simulate con `httpx.MockTransport` (ok, 400, servizio spento).
- server MCP in memoria: catalogo con i tre tool e schemi (`enum` delle unità), chiamate dirette ok ed errore.
- adattatore: discovery, conversione in tool LangChain, invocazione sincrona; filtro del tool `orologio`.
- selezione variante e configurazione (`VARIANTE_OROLOGIO` non valida → errore).

Reali, con marker `lmstudio`: «Che ore sono a Tokyo?» con variante `mcp`; «Quanto fa (2+3)*4?»; «Converti 10 km in
miglia». Docker: invariata.

## Fuori dal perimetro

Resources e prompts MCP, Streamable HTTP, più server MCP, note, catalogo e meteo. Nessuna interfaccia grafica.

## Consegna

- Codice commentato riga per riga dove serve a spiegarlo all'orale.
- File di spiegazione in `Desktop\Materiale\Spiegazione_Lezione5_MCP.md` (fuori dalla repository).
- Commit con tipo `fix(...)` su richiesta dello studente, poi push su `origin/main`.
