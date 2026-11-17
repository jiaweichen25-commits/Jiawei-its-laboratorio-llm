# Valutazione del retrieval — ricettario di Artusi

Lezione 7. Corpus: Pellegrino Artusi, *La scienza in cucina e l'arte di mangiar bene* (1891), Project Gutenberg
n. 59047. Modello di embedding: `text-embedding-nomic-embed-text-v1.5` (768 dimensioni) in LM Studio. Qdrant 1.20.2,
distanza coseno. Domande e fonti attese in `rag/domande.json`; ogni fonte attesa è stata controllata sul testo.

Comandi per riprodurre:

```powershell
docker compose up -d qdrant
.\.venv\Scripts\python.exe -m rag.ingestion
.\.venv\Scripts\python.exe -m rag.valutazione --k 5
```

## 1 · Le due ingestion (esercizio 1)

Configurazione: un documento per ricetta, chunk per ricetta divisi a paragrafi oltre 1200 caratteri, overlap 200,
prefissi `search_document:` / `search_query:` attivi.

| Esecuzione | Ricette | Chunk | Punti prima | Punti dopo | Rimossi | Durata |
|---|---|---|---|---|---|---|
| 1ª (2026-11-17) | 790 | 1145 | 0 | 1145 | 0 | 146 s |
| 2ª (2026-11-17) | 790 | 1145 | 1145 | 1145 | 0 | 141 s |

La seconda esecuzione non aggiunge nulla: gli ID dei punti derivano da ricetta e posizione (UUID v5 di
`ricetta-089:0`), quindi ogni chunk sostituisce sé stesso. Metadati registrati nella collezione:
`{"modello_embedding": "text-embedding-nomic-embed-text-v1.5", "dimensione": 768, "prefissi": true}`; indici sul
payload: `capitolo`, `numero`.

## 2 · Valutazione di partenza (esercizio 1)

Top-k = 5. ✎ = domanda scritta per questo progetto, senza copiare le parole del testo.

| Domanda | Fonte attesa | Posizione | Score fonte | Score 1° | 1° risultato |
|---|---|---|---|---|---|
| Quanta farina serve per 400 grammi di patate negli gnocchi? | 89 | 1 | 0,772 | 0,772 | 89 · Gnocchi di patate |
| Quanti cappelletti bastano a un mangiatore moderato? | 7 | 1 | 0,762 | 0,762 | 7 · Cappelletti all'uso di Romagna |
| Che vino si usa per il pollo alla cacciatora? | 208 | assente | — | 0,723 | 209 · Pollo fritto coi pomodori |
| Perché gli gnocchi possono sciogliersi nell'acqua? | 89 | 4 | 0,718 | 0,740 | 427 · Piselli colla carnesecca |
| Come si chiama il cacciucco sulle coste dell'Adriatico? | 455, 456 | 1 | 0,798 | 0,798 | 455 · Cacciucco I |
| Con che cosa si monta la salsa fredda da servire sul pesce lesso? ✎ | 126 | assente | — | 0,729 | 360 · Lingua alla scarlatta |
| Che dolce si può preparare con la farina ricavata dalle castagne? ✎ | 240 | assente | — | 0,751 | 584 · Bocca di dama I |
| Da quale paese arriva in origine la pianta del caffè? ✎ | 776 | 1 | 0,800 | 0,800 | 776 · Caffè |
| Come si prepara un salume di maiale avvolto in una fetta di carne di vitello? ✎ | 322 | assente | — | 0,785 | 160 · Ripieno pei polli |
| Qual è la ricetta del tiramisù? | — (nessuna) | — | — | 0,736 | 425 · Piselli alla francese II |
| Come si fanno gli spaghetti alla carbonara? ✎ | — (nessuna) | — | — | 0,776 | 100 · Spaghetti colle acciughe |

**Fonte attesa trovata tra i primi 5: 5 su 9. In prima posizione: 4.**

Rispetto alla valutazione mostrata in aula (slide 22, stesso modello e stessi 1200/200 caratteri): cappelletti in
posizione 1 invece di 4, «gnocchi che si sciolgono» in posizione 4 invece di assente; pollo alla cacciatora assente
in entrambe. La differenza con la configurazione d'aula non sono i prefissi (sezione 3: senza, il risultato non
cambia) ma con buona probabilità il chunk per ricetta: le dosi e il procedimento restano nello stesso chunk.

**Nessuna soglia sullo score.** Le due domande senza risposta nel libro ottengono score (0,736 e 0,776) più alti di
domande che la risposta ce l'hanno (0,718 per gli gnocchi che si sciolgono). Lo score misura la vicinanza, non dice
se il corpus contiene la risposta: decidere se rispondere spetterà alla lezione 8.

## 3 · Confronto: con e senza i prefissi del modello

Stessa pipeline, stessa collezione costruita da capo con `EMBEDDING_PREFISSI=no` (collezione
`ricette_senza_prefissi`, 1145 punti, poi eliminata). La specifica aveva scelto i prefissi perché la documentazione
del modello lo chiede; la misura dice che **su queste domande non cambiano il risultato**.

| Domanda | Con prefissi | Senza prefissi |
|---|---|---|
| Gnocchi: farina per 400 g di patate (89) | 1 · 0,772 | 1 · 0,771 |
| Cappelletti per un mangiatore moderato (7) | 1 · 0,762 | 1 · 0,757 |
| Vino del pollo alla cacciatora (208) | assente | assente |
| Gnocchi che si sciolgono (89) | 4 · 0,718 | **2** · 0,755 |
| Cacciucco sull'Adriatico (455, 456) | 1 · 0,798 | 1 · 0,794 |
| Salsa fredda per il pesce lesso (126) ✎ | assente | assente |
| Dolce con la farina di castagne (240) ✎ | assente | assente |
| Origine della pianta del caffè (776) ✎ | 1 · 0,800 | 1 · 0,802 |
| Salume avvolto nel vitello (322) ✎ | assente | assente |
| Tiramisù (nessuna) — score del 1° | 0,736 | 0,714 |
| Carbonara (nessuna) — score del 1° | 0,776 | 0,790 |
| **Fonte trovata tra i primi 5** | **5 su 9** (4 in 1ª posizione) | **5 su 9** (4 in 1ª posizione) |

Nove domande sono poche per concludere che i prefissi siano inutili: le differenze sono tutte entro pochi
centesimi di score. I prefissi restano attivi perché sono il modo d'uso indicato per il modello e la scelta è
registrata nella collezione; la misura è qui per non attribuire loro un merito che non hanno dimostrato.

Per ripeterla:

```powershell
$env:QDRANT_COLLEZIONE="ricette_senza_prefissi"; $env:EMBEDDING_PREFISSI="no"
.\.venv\Scripts\python.exe -m rag.ingestion
.\.venv\Scripts\python.exe -m rag.valutazione --k 5
Remove-Item Env:QDRANT_COLLEZIONE, Env:EMBEDDING_PREFISSI
```

## 4 · Due query commentate

### «Che vino si usa per il pollo alla cacciatora?» — fonte 208, assente

```
python -m rag.ricerca "Che vino si usa per il pollo alla cacciatora?" --k 10
 1. 0,723  209 · Pollo fritto coi pomodori        (Fritti)
 2. 0,716  455 · Cacciucco I                      (Piatti di pesce)
 3. 0,713  264 · Pollo colla marsala              (Umidi)
 ...
10. 0,699  266 · Pollo in salsa d'uovo            (Umidi)
```

La ricetta 208 non compare neppure tra i primi 10, e nemmeno filtrando sul suo capitolo (`--capitolo Fritti`: primo
è di nuovo il 209). Il suo testo è corto (513 caratteri, un chunk solo) e contiene la risposta («mezzo bicchiere di
San Giovese od altro vino rosso»), ma **la parola «cacciatora» non compare mai**: sta solo nel titolo, che oggi non
fa parte del testo indicizzato. Per il modello il chunk parla di «pollastro, cipolla, vino rosso»: somiglia a molte
altre ricette di pollo. È il caso che la modifica B (titolo nel testo indicizzato) deve risolvere. Il filtro per
capitolo non aiuta: esclude ciò che non serve, ma non rende recuperabile un chunk che non «parla» della domanda
(slide 17).

### «Che dolce si può preparare con la farina ricavata dalle castagne?» — fonte 240, assente

```
python -m rag.ricerca "Che dolce si può preparare con la farina ricavata dalle castagne?" --k 10
 1. 0,751  584 · Bocca di dama I                  (Pasticceria)
 2. 0,747  679 · Zuppa di limone                  (Torte e dolci al cucchiaio)
 ...
```

La ricetta 240, «Migliaccio di farina dolce volgarmente Castagnaccio», è divisa in 3 chunk e due contengono la
parola «castagne». Il primo però è quasi tutto una digressione di Artusi sulla poca industria degli italiani, e il
nome del dolce sta solo nel titolo. I primi risultati sono ricette di dolci in cui la domanda «somiglia» per il tema
(dolce, farina) più che per il contenuto. Anche qui il titolo nel testo indicizzato dovrebbe aiutare.

## 5 · Dopo la modifica A (`contiene_dosi`)

Da completare con l'esercizio 2.

## 6 · Dopo la modifica B (titolo nel testo indicizzato)

Da completare con l'esercizio 2.
