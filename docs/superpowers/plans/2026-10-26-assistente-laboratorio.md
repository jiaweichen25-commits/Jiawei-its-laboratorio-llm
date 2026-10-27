# Assistente del laboratorio — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** applicazione da terminale con grafo LangGraph esplicito, modello LM Studio in streaming, cronologia di sessione, strumento `orologio` eseguito dal programma, avvio con Docker Compose.

**Architecture:** `StateGraph` su `MessagesState` con nodi `modello` e `strumenti` e funzione `instrada`; cronologia in `InMemorySaver`. Il modello (`ChatOpenAI` verso LM Studio) è iniettato nel grafo, così i test usano un modello finto. Il terminale consuma `grafo.stream(stream_mode=["messages", "updates"])`.

**Tech Stack:** Python 3.14 (ripiego 3.13), langgraph, langchain-openai, python-dotenv, tzdata, pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-26-assistente-laboratorio-design.md`

## Global Constraints

- Tutto il lavoro nella root `its-laboratorio-llm/`; `Lezione3/` non va letta né modificata.
- Codice sincrono; un modulo per responsabilità come nella sezione 3 della specifica.
- Versioni fissate: `langgraph==1.2.17`, `langchain-openai==1.7.2`, `python-dotenv==1.2.4`, `tzdata==2026.5`, `pytest==9.1.1` (solo dev). Nessun'altra dipendenza diretta.
- Variabili: `LM_BASE_URL`, `LM_MODEL`, `TZ_PREDEFINITO` obbligatorie; `LOG_LEVEL` facoltativa (predefinito `INFO`). Solo `config.py` legge l'ambiente.
- Chiave API fissa `lm-studio`; nessun servizio cloud, nessuna variabile LangSmith.
- Testi per l'utente in italiano. Comandi in PowerShell.
- Prima di ogni commit: `git status`, `git diff`, staging dei soli file del task. Conventional Commits in italiano con la riga `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nessun push.
- Comando dei test: `.\.venv\Scripts\python.exe -m pytest` (di seguito `pytest`).

## Review Focus

1. Il modello scrive del testo **e** chiama lo strumento nello stesso messaggio («Controllo l'ora…»): testo, poi riga `[strumento]` su una riga propria, poi la risposta. → test in Task 6.
2. Più chiamate in un messaggio («ore a Roma e a Tokyo»): due `ToolMessage` nell'ordine delle chiamate, due righe `[strumento]`. → test in Task 6.
3. `LM_BASE_URL` senza `/v1` o con `/` finale: la `/` finale si toglie; un 404 su `/models` produce un messaggio che suggerisce `/v1`. → test in Task 2.
4. Ctrl+C mentre la risposta arriva: uscita pulita senza traceback. → test in Task 4.
5. Output rediretto su Windows (codifica cp1252) con `→` e `«»`: niente `UnicodeEncodeError`. → test in Task 4.

---

### Task 1: Struttura del progetto e grafo con risposta fissa

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.gitignore`
- Create: `assistente/__init__.py` (vuoto), `assistente/grafo.py`, `assistente/terminale.py`, `assistente/__main__.py`
- Create: `tests/__init__.py` (vuoto), `tests/test_grafo.py`, `tests/test_terminale.py`

**Interfaces:**
- Produces: `grafo.costruisci_grafo(checkpointer=None) -> CompiledStateGraph`; `grafo.config_sessione() -> dict` = `{"configurable": {"thread_id": "sessione"}, "recursion_limit": LIMITE_PASSAGGI}` con `LIMITE_PASSAGGI = 10`; `terminale.conversa(grafo, config, leggi=input, out=sys.stdout) -> None`.

- [ ] **Step 1: Ambiente**

`requirements.txt` con le quattro dipendenze fissate; `requirements-dev.txt` = `-r requirements.txt` + `pytest==9.1.1`. `.gitignore`: `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`. `pytest.ini`:

```ini
[pytest]
pythonpath = .
testpaths = tests
addopts = -m "not lmstudio and not docker"
markers =
    lmstudio: prova reale con LM Studio attivo
    docker: prova reale con Docker e LM Studio attivi
```

Run: `py -3.14 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`
Expected: installazione completata. Se un pacchetto non supporta 3.14: rimuovere `.venv`, ripetere con `py -3.13` e annotarlo per il Task 7 (immagine `python:3.13-slim`).

- [ ] **Step 2: Test che falliscono**

`tests/test_grafo.py::test_grafo_fisso_risponde_una_volta`: `costruisci_grafo().invoke({"messages": [HumanMessage("ciao")]})` → l'ultimo messaggio è un `AIMessage` con contenuto `"Il grafo è in esecuzione."` e lo stato contiene esattamente 2 messaggi.

`tests/test_terminale.py::test_risposta_fissa_ed_esci`: `leggi` restituisce in sequenza `"ciao"`, `"esci"`; `out = io.StringIO()`; dopo `conversa(costruisci_grafo(InMemorySaver()), config_sessione(), leggi, out)` l'output contiene `"Il grafo è in esecuzione."`.

Run: `pytest -v` → Expected: FAIL (`ModuleNotFoundError: assistente.grafo`).

- [ ] **Step 3: Implementare**

`grafo.py`: `StateGraph(MessagesState)`, nodo `modello` che restituisce `{"messages": [AIMessage("Il grafo è in esecuzione.")]}`, archi `START → modello → END`, `compile(checkpointer=checkpointer)`.
`terminale.py`: ciclo con prompt `Tu> `; `esci` (senza distinzione di maiuscole, spazi tolti), EOF e Ctrl+C chiudono; input vuoto ignorato; per ogni domanda `grafo.invoke(...)` e stampa del contenuto dell'ultimo messaggio. (Lo streaming arriva nel Task 4.)
`__main__.py`: `main() -> int` che costruisce il grafo con `InMemorySaver()` e chiama `conversa`; `raise SystemExit(main())`.

- [ ] **Step 4: Verificare**

Run: `pytest -v` → Expected: 2 passed.
Run: `"ciao`nesci" | .\.venv\Scripts\python.exe -m assistente` → Expected: compare `Il grafo è in esecuzione.` e il processo termina.

- [ ] **Step 5: Commit**

`git add requirements.txt requirements-dev.txt pytest.ini .gitignore assistente tests` → `feat(grafo): grafo minimo con risposta fissa`

---

### Task 2: Configurazione e controlli all'avvio

**Files:**
- Create: `assistente/config.py`, `tests/test_config.py`, `.env.example`, `.env` (non versionato)

**Interfaces:**
- Produces: `@dataclass(frozen=True) Configurazione(base_url: str, modello: str, fuso_predefinito: str, log_level: str)`; `class ErroreConfigurazione(Exception)`; `carica_configurazione(env: Mapping[str, str]) -> Configurazione`; `scarica_id_modelli(base_url: str) -> list[str]`; `verifica_modello(cfg: Configurazione, scarica=scarica_id_modelli) -> None`.

- [ ] **Step 1: Test che falliscono** (`tests/test_config.py`)

- `test_configurazione_valida`: env completo con `LM_BASE_URL="http://localhost:1234/v1/"` → `base_url == "http://localhost:1234/v1"`, `log_level == "INFO"`.
- `test_variabile_mancante` (parametrizzato sulle tre obbligatorie): `ErroreConfigurazione` il cui messaggio contiene il nome della variabile.
- `test_fuso_predefinito_non_valido`: `TZ_PREDEFINITO="Marte/Base"` → `ErroreConfigurazione` con `"Marte/Base"` nel messaggio.
- `test_modello_presente`: `scarica=lambda url: ["google/gemma-4-e4b"]` → nessuna eccezione.
- `test_modello_assente_elenca_id`: `scarica` restituisce `["a", "b"]`, `LM_MODEL="x"` → messaggio contiene `"x"`, `"a"`, `"b"`.
- `test_server_irraggiungibile`: `scarica_id_modelli("http://127.0.0.1:9/v1")` → `ErroreConfigurazione` con `"LM Studio"` nel messaggio.
- `test_404_suggerisce_v1` (Review Focus 3): con `urllib.request.urlopen` sostituito (monkeypatch) da una funzione che solleva `HTTPError(url, 404, ...)` → messaggio contiene `"/v1"`.

Run: `pytest tests/test_config.py -v` → Expected: FAIL (modulo mancante).

- [ ] **Step 2: Implementare `config.py`**

Fuso validato con `zoneinfo.ZoneInfo` (catturare `ZoneInfoNotFoundError` e `ValueError`). `scarica_id_modelli`: `urllib.request.urlopen(f"{base_url}/models", timeout=5)`, JSON → `[m["id"] for m in data["data"]]`; `URLError`/`TimeoutError` → «LM Studio non raggiungibile: controllare che il server sia avviato, URL e porta»; `HTTPError` 404 → «Endpoint non trovato: LM_BASE_URL deve terminare con /v1».

- [ ] **Step 3: Verificare** — `pytest -v` → Expected: tutti passed.

- [ ] **Step 4: File di configurazione**

`.env.example`: `LM_BASE_URL=http://localhost:1234/v1`, `LM_MODEL=<ID restituito da GET /v1/models>`, `TZ_PREDEFINITO=Europe/Rome`, `LOG_LEVEL=INFO`. `.env` reale con gli stessi valori e `LM_MODEL=google/gemma-4-e4b` (ID verificato con `Invoke-RestMethod http://localhost:1234/v1/models`).
Run: `git status --short` → Expected: `.env` non compare.

- [ ] **Step 5: Commit** — `git add assistente/config.py tests/test_config.py .env.example` → `feat(config): configurazione da ambiente e controllo del modello`

---

### Task 3: Nodo LLM e cronologia

**Files:**
- Create: `assistente/modello.py`, `tests/modello_finto.py`, `tests/test_cronologia.py`, `tests/test_modello.py`
- Modify: `assistente/grafo.py`, `tests/test_grafo.py`, `tests/test_terminale.py` (adeguare alla nuova firma)

**Interfaces:**
- Consumes: `Configurazione` (Task 2).
- Produces: `modello.crea_modello(cfg: Configurazione) -> ChatOpenAI`; `modello.descrivi_errore(exc: BaseException) -> str | None`; `grafo.costruisci_grafo(modello: BaseChatModel, fuso_predefinito: str, strumenti: Sequence[BaseTool] = (), checkpointer=None)`; `grafo.messaggio_sistema(fuso: str) -> SystemMessage`; `tests.modello_finto.ModelloFinto`.

- [ ] **Step 1: Modello finto** (`tests/modello_finto.py`)

```python
class ModelloFinto(BaseChatModel):
    risposte: list            # AIMessage o eccezioni, consumate in ordine
    ricevuti: list = []       # liste di messaggi ricevute a ogni chiamata

    @property
    def _llm_type(self) -> str:
        return "finto"

    def bind_tools(self, tools, **kwargs):
        return self

    def _prossima(self, messages):
        self.ricevuti.append(list(messages))
        r = self.risposte.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._prossima(messages))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        r = self._prossima(messages)
        for parola in re.findall(r"\S+\s*", r.content):
            yield ChatGenerationChunk(message=AIMessageChunk(content=parola))
        if r.tool_calls:
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(r.tool_calls)]))
```

- [ ] **Step 2: Test che falliscono**

`test_grafo.py::test_risposta_del_modello`: `ModelloFinto(risposte=[AIMessage("Ciao!")])` → ultimo messaggio `"Ciao!"`; `ricevuti[0][0]` è `SystemMessage` che contiene `"Europe/Rome"` e `"orologio"`.
`test_grafo.py::test_log_inizio_fine_modello` (caplog, INFO): compaiono `"modello: inizio chiamata"` e `"modello: fine chiamata"`.
`test_cronologia.py::test_due_turni_senza_duplicati`: due `invoke` nello stesso thread → lo stato contiene esattamente `[Human1, AI1, Human2, AI2]`; `ricevuti[1]` = `[SystemMessage, Human1, AI1, Human2]`.
`test_cronologia.py::test_sistema_non_salvato`: nessun `SystemMessage` nello stato dopo un turno.
`test_modello.py::test_descrivi_errore`: `openai.APITimeoutError(request=httpx.Request("POST", "http://x"))` → testo con `"Attesa scaduta"`; `openai.APIConnectionError(request=...)` → `"Connessione a LM Studio fallita"`; `ValueError()` → `None`.
`test_modello.py::test_crea_modello`: `crea_modello(cfg)` ha `model_name == cfg.modello`, `max_retries == 0`, `openai_api_base == cfg.base_url`.

Run: `pytest -v` → Expected: FAIL.

- [ ] **Step 3: Implementare**

`modello.py`: `ChatOpenAI(base_url=cfg.base_url, api_key="lm-studio", model=cfg.modello, temperature=0.2, timeout=120, max_retries=0)`. `descrivi_errore`: `APITimeoutError` (controllarlo prima: è sottoclasse di `APIConnectionError`) → «Attesa scaduta: LM Studio non ha risposto in tempo.»; `APIConnectionError` → «Connessione a LM Studio fallita: controllare server, URL e porta.»; `APIStatusError` → `f"Errore HTTP {exc.status_code} da LM Studio: {exc.message}"`; altrimenti `None`.
`grafo.py`: `messaggio_sistema` con il testo esatto della specifica, sezione 5; nodo `modello` = `modello.bind_tools(strumenti)` se ci sono strumenti, invoca `[messaggio_sistema(fuso)] + state["messages"]`, log `modello: inizio chiamata` / `modello: fine chiamata (%.1f s, tool_calls=%d)` su `logging.getLogger("assistente.grafo")`.

- [ ] **Step 4: Verificare** — `pytest -v` → Expected: tutti passed.

- [ ] **Step 5: Commit** — `feat(grafo): chiamata al modello locale e cronologia di sessione`

---

### Task 4: Terminale in streaming, errori e avvio reale

**Files:**
- Modify: `assistente/terminale.py`, `assistente/__main__.py`, `tests/test_terminale.py`

**Interfaces:**
- Consumes: `costruisci_grafo`, `config_sessione`, `crea_modello`, `descrivi_errore`, `carica_configurazione`, `verifica_modello`.
- Produces: `terminale.conversa(grafo, config, leggi=input, out=sys.stdout, descrivi_errore=lambda e: None) -> None`; `__main__.configura_output() -> None`.

- [ ] **Step 1: Test che falliscono** (`tests/test_terminale.py`, grafo con `ModelloFinto` e `InMemorySaver`)

- `test_streaming_in_ordine`: risposta `"Sono le dieci"` → `out` contiene `"Sono le dieci"`; `ricevuti` ha una sola chiamata (nessuna doppia stampa: `out.getvalue().count("Sono") == 1`).
- `test_uscite`: `"  ESCI "` chiude; EOF (`leggi` solleva `EOFError`) chiude; `"   "` non chiama il modello.
- `test_errore_connessione_e_ripresa`: risposte `[APIConnectionError(...), AIMessage("ok")]`, input `"a"`, `"b"`, `"esci"`, `descrivi_errore=modello.descrivi_errore` → `out` contiene `"Connessione a LM Studio fallita"` e poi `"ok"`; lo stato finale è `[Human("b"), AI("ok")]` (turno fallito rimosso); `ricevuti[1]` non contiene `"a"`.
- `test_ctrl_c_durante_risposta` (Review Focus 4): la risposta è `KeyboardInterrupt()` → `conversa` ritorna senza eccezioni.
- `test_output_cp1252` (Review Focus 5): `subprocess.run([sys.executable, "-c", "from assistente.__main__ import configura_output; configura_output(); print('→ «x»')"], env={**os.environ, "PYTHONIOENCODING": "cp1252"}, cwd=<root del progetto>, capture_output=True)` → `returncode == 0` (senza `configura_output` lo stesso comando fallisce con `UnicodeEncodeError`).

Run: `pytest tests/test_terminale.py -v` → Expected: FAIL.

- [ ] **Step 2: Implementare `conversa`**

Per ogni turno: annotare gli id dei messaggi nello stato (`grafo.get_state(config)`), poi `for modo, dati in grafo.stream({"messages": [HumanMessage(domanda)]}, config, stream_mode=["messages", "updates"])`. Modo `messages`: `(chunk, meta)`; stampare `chunk.content` se `meta["langgraph_node"] == "modello"` ed è una stringa non vuota, con `flush`. A fine turno andare a capo se è stato stampato del testo. Eccezione: `GraphRecursionError` → «Troppi passaggi tra modello e strumenti: turno interrotto.»; altre eccezioni → `descrivi_errore(exc)`, rilanciare se `None`. In entrambi i casi: a capo se serve, stampa, log `ERROR`, poi rimuovere con `grafo.update_state(config, {"messages": [RemoveMessage(id=i) ...]}, as_node="modello")` i messaggi con id nuovi. `KeyboardInterrupt` in qualsiasi punto → a capo e uscita.

- [ ] **Step 3: Implementare `__main__.main`**

`configura_output()` = `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` e lo stesso per `sys.stderr`. Sequenza: `configura_output()`, `load_dotenv(override=False)`, `carica_configurazione(os.environ)`, `logging.basicConfig(level=cfg.log_level, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")`, `logging.getLogger("httpx").setLevel(logging.WARNING)`, `verifica_modello(cfg)`, grafo con `crea_modello(cfg)` e `InMemorySaver()`, `conversa(..., descrivi_errore=descrivi_errore)`. `ErroreConfigurazione` → messaggio su stderr, `return 1`.

- [ ] **Step 4: Verificare**

Run: `pytest -v` → Expected: tutti passed.
Prova reale (LM Studio attivo): `.\.venv\Scripts\python.exe -m assistente`, poi «Mi chiamo Jiawei», poi «Come mi chiamo?», poi `esci` → Expected: la risposta compare in streaming; la seconda risposta usa il nome; nei log ci sono inizio e fine di ogni chiamata. Prova con LM Studio fermo → Expected: messaggio «LM Studio non raggiungibile…», codice di uscita 1. Annotare gli esiti per il resoconto.

- [ ] **Step 5: Commit** — `feat(terminale): risposta in streaming e gestione degli errori`

---

### Task 5: Strumento orologio

**Files:**
- Create: `assistente/strumenti.py`, `tests/test_strumenti.py`

**Interfaces:**
- Produces: `strumenti.crea_orologio(adesso: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> BaseTool` con nome `orologio`, parametro `fuso: str` e la descrizione esatta della specifica, sezione 6.

- [ ] **Step 1: Test che falliscono** — istante fisso `ISTANTE = datetime(2026, 10, 26, 15, 42, 10, tzinfo=timezone.utc)`, `o = crea_orologio(lambda: ISTANTE)`:

```python
assert o.name == "orologio"
assert o.invoke({"fuso": "Asia/Tokyo"}) == "2026-10-27T00:42:10+09:00 (Asia/Tokyo)"
assert o.invoke({"fuso": "Europe/Rome"}) == "2026-10-26T16:42:10+01:00 (Europe/Rome)"   # dopo il cambio del 25/10
assert o.invoke({"fuso": "UTC"}) == "2026-10-26T15:42:10+00:00 (UTC)"
assert crea_orologio(lambda: datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)).invoke(
    {"fuso": "Europe/Rome"}) == "2026-07-15T12:00:00+02:00 (Europe/Rome)"
assert o.invoke({"fuso": "Marte/Base"}) == "Errore: fuso orario sconosciuto: «Marte/Base»"
assert o.invoke({"fuso": "../etc"}).startswith("Errore: fuso orario sconosciuto")
```

Run: `pytest tests/test_strumenti.py -v` → Expected: FAIL.

- [ ] **Step 2: Implementare** — `adesso().astimezone(ZoneInfo(fuso)).isoformat(timespec="seconds")` + `f" ({fuso})"`; `ZoneInfoNotFoundError` e `ValueError` → stringa di errore.
- [ ] **Step 3: Verificare** — `pytest -v` → Expected: tutti passed.
- [ ] **Step 4: Commit** — `feat(strumenti): aggiunge lo strumento orologio`

---

### Task 6: Instradamento, nodo strumenti, traccia e prova reale

**Files:**
- Modify: `assistente/grafo.py`, `assistente/terminale.py`, `assistente/__main__.py`, `tests/test_grafo.py`, `tests/test_terminale.py`
- Create: `tests/test_reali.py`

**Interfaces:**
- Consumes: `crea_orologio` (Task 5), `ModelloFinto` (Task 3).
- Produces: `grafo.instrada(state) -> Literal["strumenti", "__end__"]`; `terminale.formatta_traccia(nome: str, args: dict, risultato: str) -> str`.

- [ ] **Step 1: Test che falliscono**

Helper nei test: `chiamata(fuso, id="c1") = AIMessage("", tool_calls=[{"name": "orologio", "args": {"fuso": fuso}, "id": id}])`; orologio con l'`ISTANTE` del Task 5.

- `test_grafo.py::test_senza_strumenti_va_a_end`: una risposta di solo testo → nessun `ToolMessage` nello stato.
- `test_grafo.py::test_ciclo_orologio`: risposte `[chiamata("Asia/Tokyo"), AIMessage("Sono le 00:42")]` → messaggi `[Human, AI(tool_calls), ToolMessage, AI]`; `ToolMessage.content == "2026-10-27T00:42:10+09:00 (Asia/Tokyo)"`, `tool_call_id == "c1"`; il modello è chiamato 2 volte e la seconda volta riceve il `ToolMessage`.
- `test_grafo.py::test_strumento_sconosciuto`: tool call con nome `"meteo"` → `ToolMessage` che inizia per `"Errore: strumento sconosciuto"`.
- `test_grafo.py::test_argomenti_non_validi`: args `{}` → `ToolMessage` che inizia per `"Errore:"`, nessuna eccezione.
- `test_grafo.py::test_limite_passaggi`: 20 risposte `chiamata(...)` con id diversi → `pytest.raises(GraphRecursionError)`.
- `test_grafo.py::test_log_strumenti` (caplog): `"strumenti: richiesta orologio"` e `"strumenti: risultato orologio"`.
- `test_grafo.py::test_due_chiamate_in_ordine` (Review Focus 2): un `AIMessage` con chiamate `Europe/Rome` (c1) e `Asia/Tokyo` (c2) → due `ToolMessage` con id `c1`, `c2` in quest'ordine.
- `test_terminale.py::test_formatta_traccia`: `formatta_traccia("orologio", {"fuso": "Asia/Tokyo"}, "X") == '[strumento] orologio(fuso="Asia/Tokyo") → X'`.
- `test_terminale.py::test_testo_poi_traccia` (Review Focus 1): prima risposta `AIMessage("Controllo l'ora.", tool_calls=[...])`, poi `AIMessage("Sono le 00:42.")` → in `out`, nell'ordine: `"Controllo l'ora."`, un a capo, la riga `[strumento] orologio(fuso="Asia/Tokyo") → 2026-10-27T00:42:10+09:00 (Asia/Tokyo)`, `"Sono le 00:42."`.

Run: `pytest -v` → Expected: FAIL.

- [ ] **Step 2: Implementare il grafo**

`instrada`: `"strumenti"` se `state["messages"][-1].tool_calls`, altrimenti `END`. Nodo `strumenti`: dizionario `{s.name: s}`; per ogni chiamata nell'ordine, `ToolMessage(content, tool_call_id=c["id"], name=c["name"])`; nome sconosciuto → `"Errore: strumento sconosciuto: «<nome>»"`; eccezione dell'invocazione (validazione compresa) → `f"Errore: argomenti non validi per {nome}: {exc}"`. Log `strumenti: richiesta %s %s` e `strumenti: risultato %s → %s`. Archi: `START → modello`, `add_conditional_edges("modello", instrada, ["strumenti", END])`, `strumenti → modello`.

- [ ] **Step 3: Implementare la traccia nel terminale**

Modo `updates`: da `dati["modello"]` memorizzare `{c["id"]: c for c in ultimo.tool_calls}`; da `dati["strumenti"]`, per ogni `ToolMessage`, andare a capo se la riga è a metà e stampare `formatta_traccia(nome, args della chiamata con quell'id, tm.content)`. `__main__`: passare `strumenti=[crea_orologio()]` e `fuso_predefinito=cfg.fuso_predefinito`.

- [ ] **Step 4: Verificare i test automatici** — `pytest -v` → Expected: tutti passed.

- [ ] **Step 5: Prova reale** (`tests/test_reali.py`, `pytestmark = pytest.mark.lmstudio`; grafo vero costruito da `.env`)

- `test_orologio_reale`: «Che ore sono a Tokyo?» → nello stato c'è un `AIMessage` con chiamata `orologio` e `args["fuso"] == "Asia/Tokyo"`; un `ToolMessage` che corrisponde a `r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+09:00 \(Asia/Tokyo\)$"`; l'ultimo messaggio è un `AIMessage` senza `tool_calls` e con testo.
- `test_conversazione_ordinaria`: «Ciao, come stai?» → nessun `ToolMessage`.

Run: `pytest -m lmstudio -v` → Expected: 2 passed. Poi una prova manuale con `python -m assistente`: «Che ore sono?» → riga `[strumento] orologio(fuso="Europe/Rome") → …` e risposta coerente. Se il modello non chiama lo strumento, riportarlo come problema aperto: non modificare i test per farli passare.

- [ ] **Step 6: Commit** — `feat(grafo): instradamento verso lo strumento orologio` (i test reali possono andare in un commit `test(reali): ...` separato)

---

### Task 7: Docker Compose

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `compose.yaml`, `tests/test_docker.py`

- [ ] **Step 1: File** — contenuti come nella specifica, sezione 9 (immagine `python:3.14-slim`, oppure 3.13 se così deciso nel Task 1; `WORKDIR /app`; `.dockerignore` con `Lezione3/`; servizio `assistente`; nessuna porta pubblicata).

- [ ] **Step 2: Test reale** (`tests/test_docker.py`, `pytestmark = pytest.mark.docker`; `pytest.skip` se manca `.env`)

`test_compose_orologio`: `docker compose build` (returncode 0), poi `docker compose run --rm -T assistente` con `input="Che ore sono a Tokyo?\nesci\n"`, `timeout=300` → `returncode == 0` e `"[strumento] orologio(" in stdout`.

- [ ] **Step 3: Verificare**

Run: `pytest -m docker -v` → Expected: 1 passed. Se fallisce per connessione: controllare «Serve on Local Network» in LM Studio e il firewall, annotare la soluzione per il README.
Prova manuale: `docker compose run --rm --name assistente-demo assistente` e, da un secondo terminale, `docker logs -f assistente-demo` → Expected: log di inizio e fine della chiamata e degli strumenti.
Run: `docker run --rm --entrypoint ls its-laboratorio-llm-assistente -a /app` → Expected: niente `.env`, `.venv`, `Lezione3`.

- [ ] **Step 4: Commit** — `feat(docker): avvio con Docker Compose`

---

### Task 8: README, CLAUDE.md e verifica finale

**Files:**
- Create: `README.md`
- Modify: `CLAUDE.md` (sezioni struttura e comandi: sostituire «verranno definiti con la specifica e il piano»)

- [ ] **Step 1: README** — preparazione (venv, `.env` da `.env.example`, verifica di `/v1/models`), avvio locale, avvio con Compose, test automatici, prove reali (`-m lmstudio`, `-m docker`), diagnosi (sintomi della slide 17 con le soluzioni effettivamente verificate). Solo comandi eseguiti nei task precedenti.
- [ ] **Step 2: CLAUDE.md** — struttura dei moduli, comando dei test, comandi delle prove reali; nient'altro.
- [ ] **Step 3: Verifica finale** con `superpowers:verification-before-completion`: `pytest -v`, `pytest -m lmstudio -v`, `pytest -m docker -v`, prova manuale con Compose. Resoconto con: test eseguiti ed esiti, problemi aperti, `git status`, `git log --oneline` dei commit prodotti.
- [ ] **Step 4: Commit** — `docs: README e comandi del progetto`. Nessun push.

---

### Task 9: Giorno della settimana nel risultato dell'orologio

Aggiunto il 2026-10-27 su decisione dell'utente: nella prova reale del Task 6 il modello ha scritto «giovedì 26 ottobre» quando era lunedì, perché lo strumento non restituiva il giorno della settimana.

**Files:**
- Modify: `assistente/strumenti.py`, `tests/test_strumenti.py`, `tests/test_grafo.py`, `tests/test_terminale.py`, `tests/test_reali.py`, `docs/superpowers/specs/2026-10-26-assistente-laboratorio-design.md` (sezione 6), `README.md`

- [ ] **Step 1: Test (rosso)** — in `test_strumenti.py` il risultato diventa ISO 8601 + fuso + `, ` + giorno della settimana in italiano, minuscolo, calcolato sulla data locale del fuso (non su quella UTC). Con l'istante `2026-10-26T15:42:10Z`: `Asia/Tokyo` → `"2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì"`; `Europe/Rome` → `"2026-10-26T16:42:10+01:00 (Europe/Rome), lunedì"`; `UTC` → `"2026-10-26T15:42:10+00:00 (UTC), lunedì"`. Estate: `"2026-07-15T12:00:00+02:00 (Europe/Rome), mercoledì"`. Gli errori restano invariati. La descrizione per il modello diventa «Restituisce la data, l'ora e il giorno della settimana correnti nel fuso orario indicato. Usalo ogni volta che servono data, ora o giorno attuali.»
- [ ] **Step 2: Implementazione** — tupla `GIORNI = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")` indicizzata con `weekday()` della data locale; niente `locale`/`strftime("%A")` (dipende dalla macchina).
- [ ] **Step 3: Allineare** le costanti attese in `test_grafo.py`, `test_terminale.py` e la regex di `test_reali.py` (`..., \(Asia/Tokyo\), (lunedì|martedì|...|domenica)`).
- [ ] **Step 4: Documenti** — specifica §6 (descrizione e formato del risultato con esempio `2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì`); README: togliere il limite «non restituisce il giorno della settimana» e aggiornare eventuali esempi.
- [ ] **Step 5: Verificare** — `pytest -v` tutto verde; `pytest -m lmstudio -v` → 2 passed; prova manuale «Che giorno è oggi?» con il modello reale.
- [ ] **Step 6: Commit** — `feat(strumenti): aggiunge il giorno della settimana all'orologio`. Nessun push.
