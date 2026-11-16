FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assistente/ ./assistente/
# Lezione 6, step 4: il file letto dalla resource utente://preferenze.
COPY preferenze.json .

# Lezione 6, step 6: il container serve l'API dell'agente; 0.0.0.0 la rende raggiungibile da fuori.
CMD ["python", "-m", "uvicorn", "assistente.servizio_agente:app", "--host", "0.0.0.0", "--port", "8001"]
