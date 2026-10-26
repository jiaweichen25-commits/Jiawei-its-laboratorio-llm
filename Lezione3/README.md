# ITS Laboratorio LLM

Client Python per un modello locale servito da LM Studio.

## Preparazione

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env   # inserire l'ID del modello reale
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
