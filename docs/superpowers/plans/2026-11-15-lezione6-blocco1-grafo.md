# Lezione 6, blocco 1 — Router, revisore e riassunto: piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** aggiungere al grafo dell'agente i nodi `router`, `rifiuto`, `revisore` e `riassunto` (step 1–3 della lezione 6), ciascuno con test, prova reale e commit.

**Architecture:** la logica dei nodi di controllo (schemi, chiamata con output vincolato, trascrizione dei messaggi, punto di taglio) vive in un modulo nuovo `assistente/controllo.py`, senza dipendenze da LangGraph. `assistente/grafo.py` definisce stato e opzioni e collega i nodi; un nodo la cui opzione è spenta non viene aggiunto, così `costruisci_grafo` senza opzioni resta il grafo della lezione 5.

**Tech Stack:** Python, LangGraph 1.2.17, langchain-core 1.7.0, langchain-openai 1.7.2, Pydantic 2, pytest. Nessuna dipendenza nuova.

**Spec:** `docs/superpowers/specs/2026-11-15-lezione6-blocco1-grafo-design.md`

## Global Constraints

- I 135 test esistenti passano senza modifiche, tranne dove indicato (nessuno previsto).
- Codice sincrono, moduli piccoli, commenti che spiegano il perché (serve all'orale).
- Variabili nuove tutte facoltative: `AMBITO_AGENTE`, `LIMITE_REVISIONI` (2), `SOGLIA_RIASSUNTO` (12), `MESSAGGI_DA_CONSERVARE` (6).
- Output non valido di router o revisore: si lascia passare, log `WARNING`.
- Comandi da PowerShell nella cartella del progetto: `.\.venv\Scripts\python.exe -m pytest`.
- Conventional Commits in italiano; `git status` e diff prima di ogni commit; staging selettivo; nessun push.
- Prove reali (`-m lmstudio`) eseguite alla fine di ogni task; un fallimento si riporta con il punto esatto.

## Review Focus

1. Il router riceve testo che non è JSON valido → la domanda passa all'agente, log `WARNING` (Task 1).
2. Domanda di seguito che ha senso solo con il contesto («e a Tokyo?») → il router riceve anche gli ultimi scambi (Task 1).
3. Dopo una bocciatura l'agente, riscrivendo, chiede uno strumento → il ciclo strumenti funziona e il contatore non si perde (Task 2).
4. Il modello restituisce un riassunto vuoto → non si toglie nessun messaggio (Task 3).
5. Cronologia lunga senza un punto di taglio valido (un solo turno con molte chiamate a strumenti) → nessun riassunto, nessuna coppia richiesta/`ToolMessage` separata (Task 3).

## File

| File | Responsabilità |
|---|---|
| `assistente/controllo.py` (nuovo) | schemi Pydantic, `chiedi_strutturato`, `trascrivi`, `e_revisione`, `punto_di_taglio`, prompt di sistema dei nodi di controllo |
| `assistente/grafo.py` | `StatoAgente`, `OpzioniGrafo`, nodi e archi |
| `assistente/config.py` | quattro campi nuovi e loro validazione |
| `assistente/__main__.py` | passa le opzioni al grafo |
| `assistente/terminale.py` | righe `[revisore]`, `[riassunto]`, testo del rifiuto; azzera `revisioni` a ogni turno |
| `tests/test_controllo.py` (nuovo), `tests/test_grafo_lezione6.py` (nuovo) | test dei tre step |
| `tests/test_config.py`, `tests/test_terminale.py`, `tests/test_reali.py` | test aggiunti in coda |
| `.env.example`, `README.md`, `CLAUDE.md` | variabili, grafo, scelta sulla bozza |

Scostamento dalla specifica, deciso qui: `revisioni` non è azzerato dal nodo `riassunto` ma dall'ingresso del turno (`{"messages": [...], "revisioni": 0}` passato dal terminale), così non dipende da quale nodo è acceso. Lo stato ha anche `categoria: str`, letta dall'arco condizionale dopo il router. La specifica va allineata nel Task 1.

---

### Task 1: Router e rifiuto (step 1)

**Files:**
- Create: `assistente/controllo.py`, `tests/test_controllo.py`, `tests/test_grafo_lezione6.py`
- Modify: `assistente/grafo.py`, `assistente/config.py`, `assistente/__main__.py`, `assistente/terminale.py`, `.env.example`, `README.md`, la specifica
- Test: i due file nuovi, `tests/test_config.py`, `tests/test_terminale.py`, `tests/test_reali.py`

**Interfaces — Produces:**

```python
# assistente/controllo.py
PREFISSO_REVISIONE = "[Revisione]"

class DecisioneRouter(BaseModel):
    categoria: Literal["conversazione", "fuori_ambito"]
    motivo: str

def chiedi_strutturato(modello: BaseChatModel, schema: type[BaseModel], messaggi: list) -> BaseModel | None
    # modello.bind(response_format={"type": "json_schema", "json_schema":
    #   {"name": schema.__name__, "strict": True, "schema": schema.model_json_schema()}}).invoke(messaggi)
    # poi schema.model_validate_json(risposta.content); ValidationError → log WARNING con il testo ricevuto, None.
    # Le eccezioni di collegamento NON sono catturate: il turno fallisce come oggi.

def e_revisione(messaggio) -> bool          # HumanMessage il cui testo inizia con PREFISSO_REVISIONE
def trascrivi(messaggi) -> str
    # una riga per messaggio: "Utente: …", "Assistente: …", "Strumento <nome>: …";
    # salta gli AIMessage senza testo (sole richieste di strumento).
def messaggi_router(ambito: str, riassunto: str, messaggi: list) -> list
    # [SystemMessage(istruzioni + ambito), HumanMessage(riassunto se presente + trascrizione)]
    # trascrizione = ultimi 4 tra HumanMessage non di revisione e AIMessage con testo.

# assistente/grafo.py
LIMITE_PASSAGGI = 16

class StatoAgente(MessagesState):
    riassunto: str
    revisioni: int
    categoria: str

@dataclass(frozen=True)
class OpzioniGrafo:
    ambito: str | None = None          # None → nessun router
    limite_revisioni: int = 0          # 0 → nessun revisore
    soglia_riassunto: int = 0          # 0 → nessun riassunto
    messaggi_da_conservare: int = 6

def risposta_rifiuto(ambito: str) -> str  # "Questa richiesta è fuori dal mio ambito. Posso aiutarti con: <ambito>"
def costruisci_grafo(modello, fuso_predefinito, strumenti=(), checkpointer=None, opzioni: OpzioniGrafo = OpzioniGrafo())

# assistente/config.py — campi aggiunti a Configurazione, con questi predefiniti
AMBITO_PREDEFINITO = "<testo della specifica>"
ambito: str = AMBITO_PREDEFINITO
limite_revisioni: int = 2
soglia_riassunto: int = 12
messaggi_da_conservare: int = 6
```

Archi con il router acceso: `START → router`; `router → {"conversazione": "modello", "fuori_ambito": "rifiuto"}` tramite `instrada_router(state)`, che legge `state["categoria"]`; `rifiuto → END`. Il nodo `router` scrive `{"categoria": ...}` e il log `router: categoria=%s motivo=%s`; con decisione `None` scrive `conversazione`. Il nodo `rifiuto` aggiunge `AIMessage(risposta_rifiuto(ambito))` senza chiamare il modello e scrive il log `rifiuto: richiesta fuori ambito`.

Validazione in `carica_configurazione`: i tre interi devono essere numeri interi ≥ 0, altrimenti `ErroreConfigurazione` che nomina la variabile; con `SOGLIA_RIASSUNTO > 0` serve `2 ≤ MESSAGGI_DA_CONSERVARE < SOGLIA_RIASSUNTO`. `AMBITO_AGENTE` vuoto o assente → predefinito. (I quattro campi si aggiungono tutti ora: evita di riaprire `config.py` nei task successivi.)

- [ ] **Step 1: test che falliscono**

`tests/test_controllo.py`:

```python
def test_chiedi_strutturato_valido():
    modello = ModelloFinto(risposte=[AIMessage('{"categoria": "fuori_ambito", "motivo": "ricetta"}')])
    d = chiedi_strutturato(modello, DecisioneRouter, [HumanMessage("x")])
    assert (d.categoria, d.motivo) == ("fuori_ambito", "ricetta")

@pytest.mark.parametrize("testo", ["non so", '{"categoria": "boh", "motivo": "x"}', ""])
def test_chiedi_strutturato_non_valido_restituisce_none(testo, caplog):
    assert chiedi_strutturato(ModelloFinto(risposte=[AIMessage(testo)]), DecisioneRouter, [HumanMessage("x")]) is None
    assert "WARNING" in caplog.text

def test_trascrivi():
    messaggi = [HumanMessage("ciao"), AIMessage("", tool_calls=[{"name": "orologio", "args": {}, "id": "c1"}]),
                ToolMessage("10:00", tool_call_id="c1", name="orologio"), AIMessage("Sono le 10")]
    assert trascrivi(messaggi) == "Utente: ciao\nStrumento orologio: 10:00\nAssistente: Sono le 10"

def test_messaggi_router_contiene_ambito_e_contesto():
    cronologia = [HumanMessage("Che ore sono a Roma?"), AIMessage("Le 10."), HumanMessage("e a Tokyo?")]
    sistema, utente = messaggi_router("data e ora", "", cronologia)
    assert "data e ora" in sistema.content
    assert "Che ore sono a Roma?" in utente.content and "e a Tokyo?" in utente.content
```

`tests/test_grafo_lezione6.py` (helper `router(categoria, motivo="m")` che restituisce l'`AIMessage` JSON; `OPZ = OpzioniGrafo(ambito="data e ora")`):

```python
def test_router_in_ambito_passa_all_agente(caplog):
    # risposte: router("conversazione"), AIMessage("Ciao!")
    assert stato["messages"][-1].content == "Ciao!"
    assert "router: categoria=conversazione motivo=m" in caplog.text
    assert "modello: inizio chiamata" in caplog.text

def test_router_fuori_ambito_rifiuta_senza_agente(caplog):
    # risposte: solo router("fuori_ambito")
    assert stato["messages"][-1].content == risposta_rifiuto("data e ora")
    assert len(modello.ricevuti) == 1                      # solo la chiamata del router
    assert "modello: inizio chiamata" not in caplog.text
    assert "router: categoria=fuori_ambito" in caplog.text

def test_router_output_non_valido_lascia_passare(caplog):
    # risposte: AIMessage("boh"), AIMessage("Ciao!")
    assert stato["messages"][-1].content == "Ciao!"
    assert "WARNING" in caplog.text

def test_router_non_vede_gli_strumenti():
    # il messaggio di sistema ricevuto dal router non contiene "orologio"
    assert "orologio" not in modello.ricevuti[0][0].content

def test_senza_opzioni_il_grafo_e_quello_della_lezione_5():
    grafo = costruisci_grafo(ModelloFinto(risposte=[]), "Europe/Rome")
    assert set(grafo.get_graph().nodes) == {"__start__", "modello", "strumenti", "__end__"}
```

`tests/test_config.py`: predefiniti (`ambito == AMBITO_PREDEFINITO`, 2, 12, 6); `AMBITO_AGENTE=" solo calcoli "` → `"solo calcoli"`; `LIMITE_REVISIONI="tante"`, `SOGLIA_RIASSUNTO="-1"` → errore che nomina la variabile; `SOGLIA_RIASSUNTO=4` con `MESSAGGI_DA_CONSERVARE=6` → errore; `SOGLIA_RIASSUNTO=0` → valido.

`tests/test_terminale.py`: con `OpzioniGrafo(ambito="data e ora")` e risposta `router("fuori_ambito")`, l'output contiene `risposta_rifiuto("data e ora")`.

- [ ] **Step 2:** eseguire i test nuovi, devono fallire per import mancanti.
- [ ] **Step 3:** implementare `controllo.py`, poi `config.py`, poi `grafo.py` (`StateGraph(StatoAgente)`; i nodi esistenti restano uguali), poi `__main__.py` (costruisce `OpzioniGrafo` dalla configurazione), poi `terminale.py`: l'ingresso del turno diventa `{"messages": [HumanMessage(domanda)], "revisioni": 0}` e, quando arriva un aggiornamento del nodo `rifiuto`, il testo del suo messaggio viene stampato con `uscita.riga`.
- [ ] **Step 4:** `.\.venv\Scripts\python.exe -m pytest` → tutti verdi (135 + nuovi).
- [ ] **Step 5: prove reali.** In `tests/test_reali.py` aggiungere un helper `grafo_lezione6(cfg, strumenti_mcp, **opzioni)` e:

```python
def test_router_reale_in_ambito(cfg, strumenti_mcp):       # «Che ore sono a Tokyo?» → chiamata a orologio
def test_router_reale_fuori_ambito(cfg, strumenti_mcp):    # «Dammi la ricetta della carbonara»
    assert messaggi[-1].content == risposta_rifiuto(cfg.ambito) and not chiamate(messaggi)
```

Eseguire `.\.venv\Scripts\python.exe -m pytest -m lmstudio -v` e una sessione vera `python -m assistente` con le due domande, conservando le righe di log come evidenza.

- [ ] **Step 6:** `.env.example` (quattro variabili commentate), README (sezione «Lezione 6 · step 1», ambito, evidenze), allineare la specifica sui due scostamenti.
- [ ] **Step 7: commit** `feat(grafo): router che rifiuta le domande fuori ambito` (include specifica e piano).

---

### Task 2: Revisore (step 2)

**Files:** Modify `assistente/controllo.py`, `assistente/grafo.py`, `assistente/terminale.py`, `README.md`; Test `tests/test_controllo.py`, `tests/test_grafo_lezione6.py`, `tests/test_terminale.py`, `tests/test_reali.py`

**Interfaces:**
- Consumes: `chiedi_strutturato`, `e_revisione`, `trascrivi`, `PREFISSO_REVISIONE`, `StatoAgente.revisioni`, `OpzioniGrafo.limite_revisioni`.
- Produces:

```python
class EsitoRevisione(BaseModel):
    coerente: bool
    motivo: str

def messaggi_revisore(messaggi: list) -> list
    # domanda = ultimo HumanMessage non di revisione; risultati = ToolMessage successivi alla domanda;
    # risposta = testo dell'ultimo messaggio. Un SystemMessage con le istruzioni (giudica la copertura
    # della domanda, non la verità dei fatti) e un HumanMessage con le tre parti etichettate.
def indicazione_revisione(motivo: str) -> HumanMessage
    # f"{PREFISSO_REVISIONE} La risposta precedente non è coerente con la domanda: {motivo} Riscrivi la risposta completa."
```

Archi con il revisore acceso: da `modello`, `instrada` resta com'è ma la mappa diventa `{"strumenti": "strumenti", END: "revisore"}`; da `revisore`, `instrada_revisore(state)` va a `modello` se l'ultimo messaggio è un'indicazione di revisione, altrimenti a `END`. Il nodo `revisore`: esito `None` o `coerente` → `{}` e log `revisore: coerente`; non coerente con `revisioni < limite` → `{"messages": [indicazione], "revisioni": n + 1}` e log `revisore: non coerente (revisione %d di %d) motivo=%s`; non coerente al limite → `{}` e log `WARNING revisore: limite di revisioni raggiunto, resta l'ultima risposta`.

- [ ] **Step 1: test che falliscono** (helper `revisore(coerente, motivo="m")`; `OPZ = OpzioniGrafo(limite_revisioni=2)`):

```python
def test_revisore_approva_al_primo_passaggio(caplog):
    # risposte: AIMessage("Sono le 10."), revisore(True)
    assert [type(m) for m in stato["messages"]] == [HumanMessage, AIMessage]
    assert "revisore: coerente" in caplog.text

def test_revisore_boccia_poi_approva():
    # risposte: AIMessage("Sono le 10."), revisore(False, "manca il calcolo"), AIMessage("Sono le 10 e fa 96."), revisore(True)
    assert stato["messages"][-1].content == "Sono le 10 e fa 96."
    assert stato["messages"][2].content.startswith("[Revisione]") and "manca il calcolo" in stato["messages"][2].content
    assert stato["revisioni"] == 1

def test_revisore_che_rifiuta_sempre_si_ferma_al_limite(caplog):
    # risposte: bozza1, no, bozza2, no, bozza3, no
    assert stato["messages"][-1].content == "bozza3" and stato["revisioni"] == 2
    assert "limite di revisioni raggiunto" in caplog.text
    assert modello.risposte == []                           # nessuna chiamata oltre il limite

def test_dopo_la_bocciatura_l_agente_puo_usare_uno_strumento():
    # risposte: AIMessage("Non so."), revisore(False), chiamata("Asia/Tokyo"), AIMessage("Sono le 00:42"), revisore(True)
    assert any(isinstance(m, ToolMessage) for m in stato["messages"]) and stato["revisioni"] == 1

def test_il_revisore_riceve_domanda_risultati_e_risposta():
    # in modello.ricevuti[-1][1].content compaiono la domanda, ORA_TOKYO e la risposta proposta

def test_revisore_output_non_valido_approva(caplog): ...
def test_router_e_revisore_insieme(): ...      # fuori ambito: il revisore non viene chiamato
```

`tests/test_terminale.py`: dopo una bocciatura l'output contiene una riga che inizia con `[revisore] non coerente:` seguita dal motivo, e poi la risposta nuova; al turno successivo `revisioni` riparte da 0.

- [ ] **Step 2:** i test falliscono.
- [ ] **Step 3:** implementare; nel terminale, un aggiornamento del nodo `revisore` che contiene un'indicazione stampa `[revisore] non coerente: <motivo>` (gli aggiornamenti vuoti arrivano come `None`: vanno tollerati).
- [ ] **Step 4:** tutti i test verdi.
- [ ] **Step 5: prova reale** `test_revisore_reale_domanda_in_due_parti`: «Che ore sono a Tokyo e quanto fa 12 × 8?» con `limite_revisioni=2` → la risposta finale contiene `96` e c'è una chiamata a `orologio`. Più una sessione vera, conservando i log del revisore.
- [ ] **Step 6:** README: step 2 e la scelta «la bozza si vede mentre viene scritta».
- [ ] **Step 7: commit** `feat(grafo): revisore della coerenza con limite di revisioni`.

---

### Task 3: Riassunto (step 3)

**Files:** Modify `assistente/controllo.py`, `assistente/grafo.py`, `assistente/terminale.py`, `README.md`, `CLAUDE.md`; Test come sopra

**Interfaces:**
- Consumes: `trascrivi`, `e_revisione`, `StatoAgente.riassunto`, `OpzioniGrafo.soglia_riassunto`, `OpzioniGrafo.messaggi_da_conservare`.
- Produces:

```python
def punto_di_taglio(messaggi: list, conserva: int) -> int
    # indice i più grande con 0 < i <= len(messaggi) - conserva tale che messaggi[i] è un HumanMessage
    # non di revisione; 0 se non esiste. messaggi[:i] si riassume, messaggi[i:] resta.
def messaggi_riassunto(riassunto_precedente: str, vecchi: list) -> list
def messaggio_sistema(fuso: str, riassunto: str = "") -> SystemMessage   # in grafo.py, firma estesa
    # con riassunto non vuoto aggiunge in coda "\n\nRiassunto della conversazione finora: <riassunto>"
```

Archi con il riassunto acceso: `START → riassunto → (router | modello)`. Il nodo: `len(messaggi) <= soglia` → `{}` senza chiamare il modello; taglio 0 → `{}`; testo del riassunto vuoto → `{}` e log `WARNING`; altrimenti `{"riassunto": testo, "messages": [RemoveMessage(id=m.id) for m in vecchi]}` e log `riassunto: messaggi prima=%d dopo=%d`. Il router riceve `state.get("riassunto", "")`.

- [ ] **Step 1: test che falliscono:**

```python
@pytest.mark.parametrize("tipi, conserva, atteso", [
    ("HAHAHAHA", 4, 4),      # H=Human, A=AI testo, C=AI con tool_calls, T=ToolMessage, R=indicazione di revisione
    ("HAHCTAHA", 4, 2),      # len-conserva=4 è un ToolMessage: si arretra all'H in posizione 2
    ("HCTCTCTA", 4, 0),      # un solo turno: nessun taglio
    ("HARAHA", 3, 0),        # l'indicazione di revisione non è un punto di taglio
])
def test_punto_di_taglio(tipi, conserva, atteso): ...

def test_sotto_soglia_non_chiama_il_modello():
    # soglia 12, 3 messaggi: modello.ricevuti ha solo la chiamata dell'agente

def test_sopra_soglia_comprime(caplog):
    # checkpointer, soglia 4, conserva 2; tre turni; al terzo il modello riceve la richiesta di riassunto
    assert "riassunto: messaggi prima=5 dopo=1" in caplog.text
    assert stato["riassunto"] == "L'utente si chiama Jiawei."
    assert "L'utente si chiama Jiawei." in <messaggio di sistema ricevuto dall'agente>.content

def test_il_riassunto_viene_sostituito_non_accumulato(): ...   # seconda compressione: il campo contiene solo il testo nuovo
def test_riassunto_vuoto_non_toglie_messaggi(caplog): ...
def test_il_taglio_non_separa_richiesta_e_toolmessage(): ...   # dopo la compressione ogni ToolMessage ha il suo AIMessage
def test_tre_nodi_insieme(): ...                               # ordine delle chiamate: riassunto, router, agente, revisore
```

`tests/test_terminale.py`: dopo una compressione l'output contiene una riga `[riassunto] cronologia compressa: N messaggi sostituiti`.

- [ ] **Step 2:** i test falliscono.
- [ ] **Step 3:** implementare.
- [ ] **Step 4:** tutti i test verdi.
- [ ] **Step 5: prova reale** `test_riassunto_reale_ricorda_il_nome`: soglia 4, conserva 2, checkpointer; «Mi chiamo Jiawei», due domande con strumenti, poi «Come mi chiamo?» → lo stato ha un riassunto non vuoto e la risposta contiene `Jiawei`. Più una sessione vera con i tre nodi accesi.
- [ ] **Step 6:** README (step 3, diagramma del grafo completo), `CLAUDE.md` (struttura: `controllo.py` e il grafo a sei nodi).
- [ ] **Step 7: commit** `feat(grafo): riassunto della cronologia oltre la soglia`.
