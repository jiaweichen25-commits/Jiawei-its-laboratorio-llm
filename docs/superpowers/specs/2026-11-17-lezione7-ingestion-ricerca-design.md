# Lezione 7 — Ingestion e ricerca semantica sul ricettario di Artusi (esercizio 1)

Data: 2026-11-17. Slide di riferimento: `LLM_Lez_7.pdf`, in particolare 11–19 (ingestion), 20–23 (verifica),
24–27 (laboratorio). Le modifiche A e B dell'esercizio 2 avranno ciascuna una specifica breve dopo questa.

## Perché

Il modello non conosce i documenti privati e, se l'informazione manca, può inventarla (slide 4). Il RAG recupera
pochi passaggi pertinenti e li mette nel contesto. In questa lezione si costruisce e si **misura** solo il recupero:
il modello generativo torna nella lezione 8, quando la ricerca diventerà uno strumento MCP dell'agente (slide 30).
Separare le due cose permette di capire, quando una risposta RAG è sbagliata, se la colpa è del recupero o della
generazione (slide 6).

## Obiettivi

```
FASE 1 · INGESTION (script, quando il corpus cambia)
dati/artusi.txt → pulizia → 790 ricette → chunk → embedding (LM Studio) → Qdrant (collezione «ricette»)

FASE 2 · RICERCA (a ogni domanda)
domanda → embedding (stesso modello) → top-k in Qdrant, con filtro per capitolo → testo, ricetta, capitolo, score
```

1. **Ingestion ripetibile:** `python -m rag.ingestion` costruisce l'indice; rieseguita, non duplica nulla.
2. **Ricerca:** `python -m rag.ricerca "domanda" --k 5 --capitolo Fritti` mostra i risultati con la loro fonte.
3. **Valutazione:** `python -m rag.valutazione` esegue le domande con fonte attesa e stampa una tabella
   riproducibile (posizione e score della fonte attesa).
4. **Test** che passano con LM Studio e Qdrant spenti (slide 25).

## Non obiettivi

- Generazione di risposte e strumento `search_documents` per l'agente: lezione 8.
- Modifiche A (`contiene_dosi`) e B (titolo nel testo indicizzato): esercizio 2, specifiche separate.
- Formati diversi dal testo (PDF, HTML), OCR, più corpus.

## Le cinque scelte

### 1 · Che cos'è un documento → una ricetta, e solo le ricette

Ogni ricetta è un documento con numero, titolo e capitolo, come chiede la slide 25. Il resto del libro si scarta:
l'introduzione (prefazione, norme d'igiene, spiegazione di voci), le brevi introduzioni ad alcuni capitoli,
l'appendice «Cucina per gli stomachi deboli», i menu dei pranzi e l'indice.

- *Perché:* le domande con fonte attesa delle slide sono tutte ricette, e la verifica «790 ricette, numerazione
  senza buchi» resta semplice. Ogni risultato ha sempre numero, titolo e capitolo, quindi si cita in modo uniforme.
  Menu e indice sarebbero dannosi: contengono i titoli senza le ricette e «somigliano» moltissimo alle domande.
- *Prezzo accettato:* una domanda sulla parte narrativa del libro (per esempio sugli stomachi deboli) non trova
  risposta. Includerla è un'estensione possibile.
- *Capitolo:* il titolo in maiuscolo che precede la ricetta. Sono 23 (BRODI, GELATINA E SUGHI … COSE DIVERSE). Le
  altre righe in maiuscolo che non sono capitoli (per esempio «QUALITÀ E STAGIONE DEI PESCI», «RICETTA A»,
  «PRIMA RICETTA», «MINESTRE» che raggruppa due capitoli) non diventano capitoli. Nel payload il capitolo si scrive
  con la prima lettera maiuscola («Fritti», «Piatti di pesce»), lo stesso formato da usare nel filtro.

### 2 · Chunking → per ricetta, e le ricette lunghe divise a paragrafi

È la «combinazione frequente» della slide 15. Una ricetta fino a **1200 caratteri** è un chunk solo (il 72% delle
ricette). Una ricetta più lunga si divide a paragrafi: si riuniscono i paragrafi consecutivi finché stanno nei
1200 caratteri e il chunk successivo ripete la coda del precedente (**overlap 200 caratteri**, tagliato a inizio
parola). Un singolo paragrafo più lungo di 1200 caratteri (ce ne sono pochi, fino a 1484) si taglia a finestra.
Dimensione e overlap si cambiano dalla configurazione.

- *Perché per ricetta:* una ricetta è un'unità di significato; tagliarla a finestra fissa separerebbe le dosi dal
  procedimento (il «rischio principale» della slide 14). Un chunk non mescola mai due ricette.
- *Perché 1200/200:* sono i valori della valutazione mostrata in aula (slide 22), quindi i nostri risultati si
  confrontano con i loro. La mediana delle ricette è 880 caratteri: con 1200 la maggior parte resta intera.
- *Pulizia:* le righe del file sono spezzate a circa 70 caratteri; dentro un paragrafo si riuniscono con uno spazio,
  i paragrafi restano separati. Si tolgono intestazione e licenza del Project Gutenberg e i caratteri di controllo.

### 3 · Campi del payload

| Campo | Esempio | A che cosa serve |
|---|---|---|
| `documento_id` | `ricetta-089` | identificare la ricetta, citarla |
| `numero` | `89` | citare la ricetta come nel libro; indice per filtri futuri |
| `titolo` | `Gnocchi di patate` | mostrare la fonte in modo leggibile |
| `capitolo` | `Minestre asciutte e di magro` | filtrare (indice sul payload) |
| `posizione` | `0` | ordine del chunk nella ricetta: ritrovare i chunk adiacenti |
| `chunk_totali` | `2` | sapere se il chunk è tutta la ricetta o solo una parte |
| `testo` | il testo del chunk | ciò che la ricerca restituisce |
| `fonte` | `Artusi, La scienza in cucina (1891), ricetta 89` | citazione pronta da mostrare |

Indici sul payload: `capitolo` (parola chiave) e `numero` (intero). La collezione registra nei propri metadati il
**modello di embedding** e la **dimensione** dei vettori.

### 4 · Identificativi dei punti → stabili, derivati da ricetta e posizione

L'ID di un punto è un UUID calcolato in modo deterministico (UUID versione 5) da `documento_id` e `posizione`, per
esempio da `ricetta-089:0`. Stessa ricetta e stessa posizione danno sempre lo stesso ID.

- *Perché:* con ID casuali ogni ingestion aggiungerebbe una copia di tutto e la ricerca restituirebbe duplicati
  (slide 18). Qdrant richiede come ID un intero o un UUID: l'UUID v5 è il modo standard di ottenerne uno stabile da
  un testo.

### 5 · Rieseguire l'ingestion → upsert, più rimozione dei punti rimasti orfani

È la strategia A della slide 18. Ogni chunk viene scritto con il suo ID stabile: se esiste già viene sostituito
(upsert). Poi l'ingestion elimina i punti della collezione che non corrispondono più a nessun chunk, per esempio
perché una ricetta, con un chunking diverso, ora ha meno pezzi: è l'«attenzione» della stessa slide. La collezione
non viene mai cancellata e ricreata.

- *Perché non la ricostruzione completa (strategia B):* è più semplice, ma l'esercizio 2 chiede esplicitamente di
  ricalcolare i chunk **senza ricreare la collezione** e di aggiungere campi **senza ricalcolare gli embedding**:
  serve già adesso una collezione che si aggiorna sul posto.
- *Controllo:* l'ingestion stampa il numero di punti prima e dopo; due esecuzioni consecutive danno lo stesso numero.

## Altre scelte di progetto

### Embedding

- Modello di LM Studio letto dalla configurazione (`EMBEDDING_MODEL`, oggi `text-embedding-nomic-embed-text-v1.5`,
  768 dimensioni), chiamato su `/v1/embeddings` dello stesso server LM Studio dell'agente (`LM_BASE_URL`), a lotti
  di 32 testi.
- **Prefissi del modello nomic:** il modello è addestrato a ricevere `search_document: ` davanti ai testi da
  indicizzare e `search_query: ` davanti alle domande, e la sua documentazione dice di usarli. Si usano, e la scelta
  si registra nei metadati della collezione insieme al modello. Si possono spegnere dalla configurazione
  (`EMBEDDING_PREFISSI`) per un confronto.
- **Cambio di modello bloccato:** se il modello o la dimensione configurati non coincidono con quelli registrati
  nella collezione, ingestion e ricerca si fermano con un messaggio che dice di reindicizzare in una collezione
  nuova (slide 10 e 23).

### Ricerca

- `k` predefinito 5, massimo **20** imposto dal codice (un valore più alto viene rifiutato).
- Il filtro per capitolo si applica **durante** la ricerca, come condizione inviata a Qdrant (slide 17): si
  ottengono k risultati del capitolo, se ne contiene almeno k.
- Un capitolo inesistente viene rifiutato con l'elenco dei capitoli validi, invece di restituire zero risultati in
  silenzio (errore tipico della slide 23).
- Ogni risultato mostra: posizione nella classifica, score, numero e titolo della ricetta, capitolo, posizione del
  chunk (`1 di 2`) e l'inizio del testo.

### Valutazione

- Domande in `rag/domande.json`: quelle viste in aula (slide 21–22) più almeno tre nuove, scritte senza copiare le
  parole del testo (slide 27), e due senza risposta nel corpus (per esempio il tiramisù).
- Per ogni domanda: posizione della fonte attesa tra i primi k (oppure «assente»), score del primo risultato e della
  fonte attesa, titolo del primo risultato. In fondo: fonti trovate su domande con risposta.
- La tabella esce in Markdown, pronta da incollare in `docs/retrieval.md`.

### Struttura

```
rag/                       nuovo pacchetto, separato da assistente/ (nella lezione 8 l'agente userà solo la ricerca)
  config.py                variabili d'ambiente
  corpus.py                lettura, pulizia, ricette e capitoli (logica pura)
  chunking.py              ricetta → chunk (logica pura)
  embedding.py             client di /v1/embeddings, con i prefissi
  archivio.py              collezione Qdrant: creazione, metadati, indici, upsert, orfani, ricerca
  ingestion.py             python -m rag.ingestion
  ricerca.py               python -m rag.ricerca "domanda" [--k N] [--capitolo NOME]
  valutazione.py           python -m rag.valutazione
  domande.json             domande con fonte attesa
dati/artusi.txt            il corpus (copiato da Downloads\Ricettario.txt), escluso da Git
docs/retrieval.md          consegna: conteggi, valutazioni, query commentate
```

### Configurazione (`.env`)

| Variabile | Predefinito |
|---|---|
| `CORPUS_FILE` | `dati/artusi.txt` |
| `QDRANT_URL` | `http://localhost:6333` |
| `QDRANT_COLLEZIONE` | `ricette` |
| `EMBEDDING_MODEL` | obbligatoria (l'ID restituito da LM Studio, mai inventato) |
| `EMBEDDING_PREFISSI` | `si` |
| `CHUNK_DIMENSIONE` | `1200` |
| `CHUNK_OVERLAP` | `200` |

### Qdrant in Docker Compose

Un quinto servizio `qdrant` (immagine `qdrant/qdrant:v1.20.2`), con volume `dati_qdrant` per la persistenza.
Le porte 6333 (API e dashboard web su `http://localhost:6333/dashboard`) sono pubblicate solo su `127.0.0.1`, perché
ingestion e ricerca girano sul computer con il `.venv`. Nessun altro servizio lo usa ancora: lo farà l'agente nella
lezione 8. Si avvia anche da solo: `docker compose up -d qdrant`.

### Dipendenze nuove

`qdrant-client==1.20.0` (compatibile con il server 1.20.2). Il modello di embedding si chiama via HTTP con `httpx`,
già presente.

### CLAUDE.md

Il «Confini» oggi dice di non anticipare il RAG: va aggiornato. Le regole stabili da aggiungere, come chiede la
slide 24: ingestion come script separato, modello di embedding dalla configurazione, Qdrant con Docker Compose, dati
scaricati fuori da Git.

## Test

Automatici, con **embedder finto** (vettori deterministici ricavati dal testo) e **Qdrant in memoria**
(`QdrantClient(":memory:")`), quindi con LM Studio e Qdrant spenti:

- corpus: 790 ricette numerate senza buchi; 23 capitoli nell'ordine del libro; ricetta 89 nel capitolo giusto;
  intestazione Gutenberg e righe spezzate pulite; la riga «137. Mettete il composto…» non è un titolo;
- chunking: una ricetta breve è un chunk solo; una lunga si divide senza superare la dimensione, con l'overlap,
  senza mescolare ricette, e ricomponendo i chunk non si perde testo; parametri dalla configurazione;
- ID: stabili tra due esecuzioni, diversi tra chunk diversi;
- ingestion: due esecuzioni → stesso numero di punti; un chunking diverso rimuove i punti orfani; payload completo;
  modello e dimensione registrati; cambio di modello bloccato; prefissi applicati a documenti e domande;
- ricerca: top-k rispettato, `k` sopra 20 rifiutato, filtro per capitolo (tutti i risultati del capitolo), capitolo
  inesistente rifiutato;
- valutazione: posizione della fonte attesa calcolata correttamente, anche quando è assente.

Reali (marker `qdrant`, con Qdrant e LM Studio accesi): ingestion completa eseguita **due volte** con lo stesso
numero di punti; ricerca con filtro su un capitolo; valutazione di partenza registrata in `docs/retrieval.md`.

## Consegna (esercizio 1)

- Commit `feat(rag): ingestion ripetibile e ricerca semantica sul ricettario`, poi push.
- `docs/retrieval.md` con i conteggi delle due ingestion e la tabella della valutazione di partenza.
- README (lezione 7: avvio di Qdrant, ingestion, ricerca, valutazione), `.env.example`, `CLAUDE.md`, `.gitignore`
  (`dati/`).
