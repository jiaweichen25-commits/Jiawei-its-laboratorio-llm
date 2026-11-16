# Lezione 6, step 9 — Docker Compose: un container per componente

Data: 2026-11-16. Chiude la lezione 6 (step 1–8). Slide di riferimento: `LLM_Lez_6.pdf`, pagine 12, 16 e 19.

## Perché

Finora i componenti si avviano a mano in terminali diversi. La slide 16 chiede che **un solo comando** avvii
l'intera applicazione, pronta all'uso dal browser, con un container per componente. Evidenza minima (slide 19):
quattro container avviati con un comando; agente non esposto.

## Obiettivi

```
        computer                         rete interna di Docker Compose
  ┌──────────────────┐      ┌───────────┐      ┌──────────┐      ┌─────────┐
  │ browser          │─────▶│ frontend  │─────▶│ backend  │─────▶│ agente  │──▶ LM Studio sul computer
  │ localhost:8085   │      │ nginx     │ /api │ FastAPI  │      │ + MCP   │    (host.docker.internal)
  └──────────────────┘      └───────────┘      └────┬─────┘      └─────────┘
                                                    ▼
                                               ┌──────────┐
                                               │ postgres │── volume dati_postgres
                                               └──────────┘
```

1. Quattro servizi in `compose.yaml`: `frontend`, `backend` e `agente` con il proprio Dockerfile, `postgres` con
   l'immagine ufficiale.
2. Rete: il browser raggiunge solo il front-end. Le chiamate API passano da un **proxy**: nginx inoltra `/api/...` al
   back-end. Back-end e agente non pubblicano porte sul computer; l'agente è raggiungibile solo dal back-end.
3. Volume per i dati di PostgreSQL; credenziali nel `.env` escluso da Git; il back-end parte solo quando il
   database è pronto (controllo di salute).
4. L'agente raggiunge LM Studio con `host.docker.internal`; il server MCP stdio parte dentro il suo container.

## Non obiettivi

- HTTPS, più repliche, immagini pubblicate su un registro.
- La CLI dentro Docker: per usarla si avvia l'agente in locale come allo step 6.

## Approcci considerati

**Come arrivano le chiamate API al back-end** (la slide ammette «porta pubblicata o proxy»)

1. **Proxy nel container del front-end** — scelto. Il browser vede un solo indirizzo, pagina e API hanno la stessa
   origine quindi CORS non serve, e il back-end non è esposto sul computer.
2. Porta del back-end pubblicata (8002) e front-end che la chiama direttamente. Più semplice da spiegare, ma
   richiede CORS, espone un servizio in più e occupa un'altra porta del computer.

## Scelte di progetto

### File

```
Dockerfile                 agente (esiste dallo step 6)
backend/Dockerfile         python:3.14-slim + backend/requirements.txt + backend/
frontend/Dockerfile        nginx + i file statici + configurazione del container
frontend/docker/nginx.conf proxy di /api/ verso il back-end, adatto allo streaming
frontend/docker/config.js  window.CONFIGURAZIONE = { backendUrl: "/api" }  (sostituisce config.js nell'immagine)
compose.yaml               i quattro servizi
```

### Servizi

| Servizio | Immagine | Porta sul computer | Dipende da | Note |
|---|---|---|---|---|
| `frontend` | `frontend/Dockerfile` (nginx) | `${PORTA_WEB:-8085}` → 80 | `backend` | serve la pagina e fa da proxy per `/api/` |
| `backend` | `backend/Dockerfile` | nessuna | `postgres` **sano**, `agente` avviato | `DATABASE_URL` verso `postgres:5432`, `AGENTE_URL=http://agente:8001` |
| `agente` | `Dockerfile` | nessuna | — | `LM_BASE_URL=http://host.docker.internal:1234/v1`, `VARIANTE_OROLOGIO=mcp` |
| `postgres` | `postgres:17` | `127.0.0.1:5434` → 5432 | — | volume `dati_postgres`, controllo di salute con `pg_isready` |

- La porta web predefinita è 8085 e si cambia con `PORTA_WEB` nel `.env`: la 8080 sulla macchina di sviluppo è
  occupata da un altro progetto.
- PostgreSQL resta raggiungibile dal solo computer locale (`127.0.0.1:5434`): serve per avviare il back-end in
  locale durante lo sviluppo e per le prove dello step 7. Non è raggiungibile dalla rete.
- Nel container l'agente usa sempre la variante `mcp` dell'orologio: la variante `fastapi` richiederebbe un quinto
  servizio.
- `DATABASE_URL` del back-end è composto in `compose.yaml` dalle variabili `POSTGRES_*` del `.env`. La password
  non deve contenere `@`, `:` o `/`, che in un indirizzo hanno un significato.

### Proxy e streaming

In `nginx.conf`, per `/api/`: `proxy_buffering off` (gli eventi SSE devono passare subito, non a blocchi) e
`proxy_read_timeout 900s` (tra un evento e l'altro possono passare decine di secondi; il valore predefinito di 60 s
chiuderebbe il collegamento mentre il router o il revisore stanno lavorando).

## Test

- Automatici: `docker compose config` valido; `compose.yaml` ha i quattro servizi, tre con `build`; `agente` e
  `backend` senza `ports`; `backend` aspetta `postgres` sano; nessuna credenziale scritta in `compose.yaml`.
- Prova reale (marker `docker`, con Docker e LM Studio attivi), che sostituisce quella dello step 6:
  1. `docker compose up -d --build` → `docker compose ps` mostra i quattro servizi attivi;
  2. la pagina risponde su `http://localhost:8085` e `/api/stato` dice che tutto è `ok`;
  3. l'agente non è raggiungibile dal computer (nessuna porta pubblicata);
  4. chat creata e domanda «Che ore sono a Tokyo?» inviata in streaming attraverso il proxy: arrivano gli eventi,
     l'orologio risponde, e `docker compose logs agente` contiene la traccia dello strumento;
  5. `docker compose down` e poi `up`: la chat è ancora presente.
- Prova nel browser, come allo step 8, ma sulla porta 8085.

## Consegna

Un commit `feat(docker): applicazione completa con un container per componente`, poi push. README (avvio con un
comando, schema, porte, cosa cambia rispetto all'avvio locale), `.env.example` (`PORTA_WEB`), `CLAUDE.md`,
`.dockerignore`.
