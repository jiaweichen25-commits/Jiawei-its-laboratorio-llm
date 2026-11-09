# Lezione 5 — Varianti dell'orologio e strumenti MCP: piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** l'orologio raggiungibile in tre varianti (locale, FastAPI, FastMCP) e due nuovi tool MCP (`calcola`, `converti`) collegati al grafo esistente con discovery reale.

**Architecture:** logica pura in `logica.py`; tre adattatori (tool locale, wrapper HTTP, client MCP) producono tutti `BaseTool` LangChain; `varianti.py` sceglie quale `orologio` esporre; il grafo resta invariato tranne il log.

**Tech Stack:** Python 3.14, LangGraph 1.2.17, langchain-core 1.7, fastmcp 4.1.6 (mcp 2.3.0), FastAPI 0.162.2, uvicorn 0.54.0, httpx 0.28.1, pytest 9.1.1.

**Spec:** `docs/superpowers/specs/2026-11-09-lezione5-mcp-design.md`

## Global Constraints

- Codice sincrono nel grafo; l'asincronia MCP resta dentro `client_mcp.py`.
- Contratti identici tra varianti: tool `orologio(fuso)`, risultato `AAAA-MM-GGTHH:MM:SS+HH:MM (Fuso), giorno`.
- Errori come testo che inizia con `Errore:`; i guasti di trasporto con `Errore di collegamento`.
- Server MCP: niente `print` su stdout (riservato al protocollo).
- Dipendenze con versione fissata in `requirements.txt`.
- Codice commentato in italiano, in modo da poterlo spiegare all'orale.
- Commit `fix(<ambito>): ...` (richiesta dello studente), senza righe Co-Authored-By.

## Review Focus

1. Il modello passa `valore` come stringa (`"10"`) a `converti`: lo schema del server lo rifiuta con un errore leggibile, non un crash → test in Task 4.
2. Espressioni ostili alla calcolatrice (`__import__('os')`, `9**9**9`, `True+1`, `1j`) → rifiutate, test in Task 1.
3. Il server MCP non parte (modulo errato) → `ErroreCollegamentoMCP` all'avvio, uscita 1 → test in Task 5.
4. Servizio FastAPI spento → `Errore di collegamento`, distinto dal fuso non valido → test in Task 3.
5. Chiusura del programma: il sottoprocesso MCP viene terminato e il thread si ferma → test `chiudi()` in Task 5.

---

### Task 1: Logica pura (`logica.py`) e orologio locale

**Files:** Create `assistente/logica.py`, `tests/test_logica.py`; Modify `assistente/strumenti.py`.

**Interfaces — Produces:**
- `class ErroreStrumento(ValueError)`
- `ora_utc() -> datetime` (spostata da `strumenti.py`, che la reimporta)
- `ora_nel_fuso(fuso: str, adesso: datetime) -> str` — solleva `ErroreStrumento("fuso orario sconosciuto: «X»")`
- `calcola(espressione: str) -> str` — es. `"(2+3)*4 = 20"`
- `converti(valore: float, da: str, a: str) -> str` — es. `"10 km = 6.21371 mi"`
- `Unita = Literal["mm","cm","m","km","in","ft","mi","g","kg","lb","oz","C","F","K"]`

- [ ] Test: `calcola("(2+3)*4") == "(2+3)*4 = 20"`, `calcola("7/2") == "7/2 = 3.5"`, `calcola("-2**2") == "-2**2 = -4"`; rifiuto con `ErroreStrumento` di `__import__('os')`, `x+1`, `2**99999`, `9**9**9`, `1/0`, `True+1`, `1j`, `"1+"`, stringa di 201 caratteri, `""`.
- [ ] Test: `converti(10,"km","mi") == "10 km = 6.21371 mi"`, `converti(100,"C","F") == "100 C = 212 F"`, `converti(0,"C","K") == "0 C = 273.15 K"`, `converti(1,"lb","g") == "1 lb = 453.592 g"`; `converti(1,"kg","m")` → `ErroreStrumento` che cita le due categorie; unità fuori elenco → `ErroreStrumento`.
- [ ] Test: `ora_nel_fuso` con istante fisso come i test esistenti; `Mars/Olympus` → errore.
- [ ] Implementa con `ast.parse(mode="eval")` e visita ricorsiva: ammessi `Expression`, `BinOp` (`Add Sub Mult Div FloorDiv Mod Pow`), `UnaryOp` (`UAdd USub`), `Constant` int/float non bool. Esponente con valore assoluto > 1000 → errore; risultato con valore assoluto > 1e100 o `OverflowError` → «risultato troppo grande». Numeri: interi così come sono, float con `format(x, ".6g")` nel convertitore e `".12g"` nella calcolatrice.
- [ ] `strumenti.crea_orologio` usa `ora_nel_fuso` e converte `ErroreStrumento` in `"Errore: ..."`; `metadata={"variante": "locale"}`. Test esistenti verdi.
- [ ] `pytest` verde → commit `fix(logica): separa la logica di orologio, calcolatrice e convertitore`.

### Task 2: Servizio FastAPI (`servizio_api.py`)

**Files:** Create `assistente/servizio_api.py`, `tests/test_servizio_api.py`; Modify `requirements.txt`.

**Interfaces — Produces:** `app: FastAPI`; `GET /orologio?fuso=...` → 200 `{"risultato": "<ora_nel_fuso>"}`; fuso non valido → 400 `{"detail": "fuso orario sconosciuto: «X»"}`. Avvio: `uvicorn assistente.servizio_api:app --port 8000`.

- [ ] Test con `fastapi.testclient.TestClient`: 200 con regex `\+09:00 \(Asia/Tokyo\)`; 400 con `Mars/Olympus` nel `detail`; 422 senza parametro; `/openapi.json` contiene `/orologio`.
- [ ] Implementa; aggiungi `fastapi==0.162.2`, `uvicorn==0.54.0`, `httpx==0.28.1`, `fastmcp==4.1.6` a `requirements.txt`.
- [ ] Commit `fix(api): servizio FastAPI per la variante HTTP dell'orologio`.

### Task 3: Wrapper HTTP (`wrapper_http.py`)

**Files:** Create `assistente/wrapper_http.py`, `tests/test_wrapper_http.py`.

**Interfaces — Produces:** `crea_orologio_http(base_url: str, client: httpx.Client | None = None) -> BaseTool` — tool `orologio(fuso)`, `metadata={"variante": "fastapi"}`, timeout 5 s.

- [ ] Test con `httpx.MockTransport`: 200 → `risultato`; 400 → `"Errore: fuso orario sconosciuto: «Mars/Olympus»"`; 500 → inizia con `"Errore di collegamento"`; `httpx.ConnectError` → inizia con `"Errore di collegamento al servizio orologio"`; la richiesta ha path `/orologio` e parametro `fuso`.
- [ ] Implementa; schema scritto a mano con la stessa descrizione di `strumenti.DESCRIZIONE_OROLOGIO`.
- [ ] Commit `fix(api): wrapper HTTP registrato come tool`.

### Task 4: Server FastMCP (`server_mcp.py`)

**Files:** Create `assistente/server_mcp.py`, `tests/test_server_mcp.py`.

**Interfaces — Produces:** `crea_server(adesso: Callable[[], datetime] = ora_utc) -> FastMCP` con tool `orologio(fuso: str)`, `calcola(espressione: str)`, `converti(valore: float, da: Unita, a: Unita)`; gli errori di dominio diventano `ToolError` (→ `is_error=True`). `python -m assistente.server_mcp` avvia lo stdio.

- [ ] Test in memoria con `fastmcp.Client(crea_server(...))`: `list_tools()` ha i nomi `{"orologio","calcola","converti"}`; `input_schema` di `converti` ha `enum` con `"km"` in `da` e `required == ["valore","da","a"]`; `call_tool("orologio", {"fuso":"Asia/Tokyo"})` → testo atteso; `Mars/Olympus` → `is_error` e testo con «Mars/Olympus»; `converti` con `valore="dieci"` → `is_error`.
- [ ] Implementa con descrizioni dei parametri (`Annotated[..., Field(description=...)]`).
- [ ] Commit `fix(mcp): server FastMCP con orologio, calcolatrice e convertitore`.

### Task 5: Client e adattatore MCP (`client_mcp.py`)

**Files:** Create `assistente/client_mcp.py`, `tests/test_client_mcp.py`.

**Interfaces — Produces:**
- `class ErroreCollegamentoMCP(Exception)`
- `class ClienteMCP(sorgente, timeout: float = 15.0)` con `avvia() -> None`, `catalogo() -> list[mcp_types.Tool]`, `chiama(nome: str, argomenti: dict) -> str`, `chiudi() -> None`; context manager.
- `trasporto_stdio() -> StdioTransport` (`sys.executable -m assistente.server_mcp`, cwd = radice del progetto)
- `crea_strumenti_mcp(cliente: ClienteMCP) -> list[BaseTool]` — `StructuredTool` con `args_schema=tool.input_schema`, `metadata={"variante": "mcp"}`.

- [ ] Test con il server in memoria: catalogo con 3 voci; `crea_strumenti_mcp` dà tool con nomi e schemi del server; `invoke({"fuso":"Asia/Tokyo"})` sincrono → ora; errore del server → `"Errore: ..."`; dopo `chiudi()` una chiamata → `"Errore di collegamento MCP"`; tool usato dentro `costruisci_grafo` con `ModelloFinto` → `ToolMessage` correlato a `call_01`.
- [ ] Test stdio reale (sottoprocesso, senza modello): `ClienteMCP(trasporto_stdio())` elenca 3 tool; trasporto verso modulo inesistente → `ErroreCollegamentoMCP` su `avvia()`.
- [ ] Implementa: thread con `asyncio.new_event_loop()`; una coroutine `_sessione()` tiene `async with Client(...)` aperto finché non arriva lo stop; chiamate via `asyncio.run_coroutine_threadsafe(...).result(timeout)`.
- [ ] Commit `fix(mcp): client persistente e adattatore dal catalogo ai tool LangChain`.

### Task 6: Scelta della variante, configurazione, avvio, log

**Files:** Create `assistente/varianti.py`, `tests/test_varianti.py`; Modify `assistente/config.py`, `assistente/__main__.py`, `assistente/grafo.py`, `.env.example`, `tests/test_config.py`, `tests/test_grafo.py`, `tests/test_reali.py`.

**Interfaces — Produces:**
- `Configurazione.variante: str = "mcp"`, `Configurazione.orologio_api_url: str = "http://localhost:8000"`; `VARIANTI = ("locale","fastapi","mcp")`
- `strumenti_per_variante(variante: str, strumenti_mcp: list[BaseTool], orologio_api_url: str) -> list[BaseTool]`

- [ ] Test: `VARIANTE_OROLOGIO=sole` → `ErroreConfigurazione` che elenca i valori ammessi; predefinita `mcp`; maiuscole accettate.
- [ ] Test: per ogni variante c'è esattamente un `orologio` con `metadata["variante"]` atteso, più `calcola` e `converti`.
- [ ] Test: il log del nodo strumenti contiene `variante=locale`, `call_id=c1` e `esito=ok` / `esito=errore`.
- [ ] `messaggio_sistema` cita anche `calcola` e `converti`.
- [ ] `__main__`: avvia `ClienteMCP(trasporto_stdio())`, in caso di errore stampa il messaggio ed esce con 1, poi costruisce gli strumenti, esegue `conversa` e alla fine chiude il client.
- [ ] Prove reali (`lmstudio`): orologio, calcolatrice e convertitore con la variante `mcp`.
- [ ] Commit `fix(agente): scelta della variante dell'orologio e collegamento MCP al grafo`.

### Task 7: Documentazione e consegna

**Files:** Modify `README.md`, `CLAUDE.md`; Create `C:\Users\Jiawei\Desktop\Materiale\Spiegazione_Lezione5_MCP.md` (fuori dalla repository).

- [ ] README: variabili nuove, avvio delle tre varianti (uvicorn per fastapi), test, diagnosi MCP (slide 24).
- [ ] CLAUDE.md: struttura dei file aggiornata.
- [ ] Verifica finale: `pytest` completo; `docker compose build` se Docker è attivo; prove reali se LM Studio è attivo.
- [ ] Commit `fix(docs): README e CLAUDE.md per la lezione 5`, poi `git push`.
