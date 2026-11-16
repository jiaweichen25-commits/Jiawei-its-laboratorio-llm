FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assistente/ ./assistente/
# Lezione 6, step 4: il file letto dalla resource utente://preferenze.
COPY preferenze.json .

CMD ["python", "-m", "assistente"]
