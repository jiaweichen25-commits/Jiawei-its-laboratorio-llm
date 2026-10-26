# ITS Laboratorio LLM

Client Python per un modello locale servito da LM Studio.

## Preparazione

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
notepad .env   # creare il file con le variabili indicate sotto
```

Contenuto di `.env`:

```
LM_BASE_URL=http://localhost:1234/v1
LM_MODEL=<ID del modello caricato>
```

Per conoscere gli ID dei modelli caricati in LM Studio:

```powershell
(Invoke-RestMethod 'http://localhost:1234/v1/models' -TimeoutSec 5).data | Select-Object id
```

## Avvio

```powershell
.\.venv\Scripts\python.exe client.py
```

## Configurazione

| Variabile     | Descrizione                          |
|---------------|--------------------------------------|
| LM_BASE_URL   | Indirizzo del server LM Studio       |
| LM_MODEL      | Identificativo del modello caricato  |

## Dipendenze

- `requests` — chiamate HTTP al server locale
- `python-dotenv` — lettura della configurazione da `.env`
