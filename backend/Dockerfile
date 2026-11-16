# Immagine del back-end (lezione 6, step 9). Si costruisce dalla cartella del progetto:
#   docker compose build backend
# Contiene solo il back-end e le sue dipendenze: gli altri componenti stanno nelle loro immagini.
FROM python:3.14-slim

WORKDIR /app

# Prima le dipendenze, poi il codice: se cambia solo il codice Docker riusa lo strato con pip install.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/

# 0.0.0.0: in ascolto su tutte le interfacce del container, così gli altri servizi lo raggiungono.
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8002"]
