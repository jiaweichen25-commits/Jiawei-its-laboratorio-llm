# Lezione 6, blocco 2 — Resource e prompt MCP: piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** aggiungere al server MCP la resource `utente://preferenze` (step 4) e i prompt `spiega` e `riassumi_conversazione` con i comandi `/prompts` e `/prompt` (step 5).

**Architecture:** il server espone le primitive nuove; `ClienteMCP` le legge con la sessione sincrona già esistente; `preferenze.py` valida le preferenze e ripiega sui predefiniti; `comandi.py` contiene la logica pura dei comandi del terminale; `grafo.py` mette le preferenze in cima al messaggio di sistema.

**Tech Stack:** Python, FastMCP 4.1.6, LangGraph 1.2.17, Pydantic 2, pytest. Nessuna dipendenza nuova.

**Spec:** `docs/superpowers/specs/2026-11-16-lezione6-blocco2-mcp-design.md`

## Global Constraints

- I test esistenti passano senza modifiche.
- La resource non compare tra i tool passati a `bind_tools`; l'adattatore resta con tre tool.
- `carica_preferenze` non solleva mai: errore → predefiniti (`italiano`, fuso di `TZ_PREDEFINITO`, `sintetico`) + `WARNING`.
- Senza preferenze il messaggio di sistema è identico a quello attuale.
- Argomenti dei prompt controllati nell'host contro `prompts/list`: errore → nessuna chiamata a server o modello.
- Commit in italiano, staging selettivo, nessun push, nessuna firma `Co-Authored-By`.

## Review Focus

1. `preferenze.json` con un campo in più o uno mancante → campi mancanti presi dai predefiniti, campi in più ignorati (Task 1).
2. Valore con spazi senza virgolette (`argomento=Model Context Protocol`) → `Model` va ad `argomento` e `Context` è una sintassi non valida: errore chiaro, nessuna chiamata (Task 2).
3. Virgolette non chiuse (`argomento="MCP`) → errore di sintassi chiaro, il terminale non si interrompe (Task 2).
4. `/prompt` mentre il server MCP è caduto → «Errore di collegamento MCP», il turno non parte (Task 2).
5. `/PROMPTS` maiuscolo o con spazi → riconosciuto come `/prompts` (Task 2).

---

### Task 1: Resource `utente://preferenze` (step 4)

**Files:** Create `preferenze.json`, `assistente/preferenze.py`, `tests/test_preferenze.py`. Modify `assistente/server_mcp.py`, `assistente/client_mcp.py`, `assistente/grafo.py`, `assistente/__main__.py`, `Dockerfile`, `.env.example`, `README.md`, `CLAUDE.md`. Test `tests/test_server_mcp.py`, `tests/test_client_mcp.py`, `tests/test_grafo_lezione6.py`, `tests/test_reali.py`.

**Interfaces — Produces:**

```python
# assistente/server_mcp.py
URI_PREFERENZE = "utente://preferenze"
def percorso_preferenze_predefinito() -> Path   # env PREFERENZE_FILE, altrimenti <radice>/preferenze.json
def crea_server(adesso=ora_utc, percorso_preferenze: Path | None = None) -> FastMCP

# assistente/client_mcp.py
ClienteMCP.leggi_risorsa(uri: str) -> str   # solleva ErroreCollegamentoMCP se la lettura fallisce

# assistente/preferenze.py
class Preferenze(BaseModel):
    lingua: str = "italiano"           # non vuota
    fuso_predefinito: str              # IANA valido
    stile: Literal["sintetico", "dettagliato"] = "sintetico"
def carica_preferenze(leggi: Callable[[], str], fuso_di_riserva: str) -> Preferenze

# assistente/grafo.py
def messaggio_sistema(fuso: str, riassunto: str = "", preferenze: Preferenze | None = None) -> SystemMessage
def costruisci_grafo(..., opzioni=OpzioniGrafo(), preferenze: Preferenze | None = None)
```

Messaggio di sistema con preferenze: prima riga `Preferenze dell'utente (resource utente://preferenze): rispondi sempre in <lingua>; se l'utente non indica un fuso orario usa <fuso>; <frase stile>.` Frasi stile: sintetico → «risposte brevi, al massimo due o tre frasi»; dettagliato → «risposte complete, con una breve spiegazione». Poi il riassunto, poi le istruzioni attuali con `Rispondi in <lingua>.` e il fuso delle preferenze.

- [ ] **Step 1: test che falliscono.** `test_preferenze.py`: valido; campo mancante → predefinito; campo in più ignorato; JSON rotto, fuso inesistente, stile sconosciuto, lingua vuota, `leggi` che solleva → predefiniti + `WARNING`. `test_server_mcp.py`: la resource è in `list_resources` e non in `list_tools`; `read_resource` restituisce il testo del file indicato; file mancante → errore MCP. `test_client_mcp.py`: `leggi_risorsa` restituisce il testo; URI inesistente → `ErroreCollegamentoMCP`; `crea_strumenti_mcp` resta a tre tool. `test_grafo_lezione6.py`: preferenze in cima e prima del riassunto; `America/New_York` e `inglese` nel testo; senza preferenze testo invariato; `costruisci_grafo` con preferenze passa il fuso delle preferenze al modello.
- [ ] **Step 2:** i test falliscono.
- [ ] **Step 3:** implementare; `__main__.py` legge la resource dopo `cliente.avvia()` con `carica_preferenze(lambda: cliente.leggi_risorsa(URI_PREFERENZE), cfg.fuso_predefinito)` e logga `preferenze: lingua=... fuso=... stile=...`. `Dockerfile` copia `preferenze.json`.
- [ ] **Step 4:** tutti i test verdi.
- [ ] **Step 5: prove reali** con `PREFERENZE_FILE` su un file temporaneo: fuso `America/New_York` → «Che ore sono?» chiama `orologio` con quel fuso; lingua `inglese` → risposta in inglese.
- [ ] **Step 6:** README (step 4, tabella delle tre primitive), `.env.example`, `CLAUDE.md`.
- [ ] **Step 7: commit** `feat(mcp): resource con le preferenze dell'utente`.

### Task 2: Prompt e comandi `/prompts`, `/prompt` (step 5)

**Files:** Create `assistente/comandi.py`, `tests/test_comandi.py`. Modify `assistente/server_mcp.py`, `assistente/client_mcp.py`, `assistente/terminale.py`, `assistente/__main__.py`, `README.md`, `CLAUDE.md`. Test `tests/test_server_mcp.py`, `tests/test_client_mcp.py`, `tests/test_terminale.py`, `tests/test_reali.py`.

**Interfaces:**
- Consumes: `ClienteMCP` di Task 1.
- Produces:

```python
# assistente/client_mcp.py
ClienteMCP.elenco_prompt() -> list            # mcp Prompt, scaricati all'avvio con list_prompts
ClienteMCP.ottieni_prompt(nome: str, argomenti: dict[str, str]) -> list[BaseMessage]
    # user → HumanMessage, assistant → AIMessage; errore → ErroreCollegamentoMCP

# assistente/comandi.py
class ErroreComando(Exception)
def interpreta_prompt(riga: str) -> tuple[str, dict[str, str]]   # "/prompt nome a=1 b=\"x y\"" → ("nome", {...})
def valida_argomenti(prompt, argomenti: dict) -> None            # sconosciuti / obbligatori mancanti → ErroreComando
def formatta_elenco(prompts: list) -> str

# assistente/terminale.py
def conversa(grafo, config, leggi=input, out=sys.stdout, descrivi_errore=..., prompt_mcp=None)
```

- [ ] **Step 1: test che falliscono.** server: due prompt con argomenti obbligatori e facoltativi; messaggi resi. client: elenco e conversione dei ruoli. comandi: virgolette, `chiave=valore` sbagliato, virgolette non chiuse, prompt sconosciuto, obbligatorio mancante, argomento sconosciuto, `/prompt` senza nome; formattazione. terminale: `/prompts`; `/prompt` valido → messaggi in cronologia e risposta del modello; non valido → nessuna chiamata al modello; comando sconosciuto; `/PROMPTS`; senza `prompt_mcp`.
- [ ] **Step 2:** i test falliscono.
- [ ] **Step 3:** implementare.
- [ ] **Step 4:** tutti i test verdi.
- [ ] **Step 5: prove reali**: `spiega` su MCP a livello base; `riassumi_conversazione` dopo due turni.
- [ ] **Step 6:** README (step 5, comandi), `CLAUDE.md`.
- [ ] **Step 7: commit** `feat(mcp): prompt riusabili con /prompts e /prompt`.
