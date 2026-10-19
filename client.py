import os
import requests
from dotenv import load_dotenv

load_dotenv(".env", override=False)

base_url = os.environ["LM_BASE_URL"].rstrip("/")
model = os.environ["LM_MODEL"]

SYSTEM = "Rispondi in italiano."
QUESTION = "Che cosa controllare se Python segnala FileNotFoundError?"

payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": QUESTION},
    ],
    "temperature": 0.2,
    "max_tokens": 2048,
    "stream": False,
}

try:
    response = requests.post(
        f"{base_url}/chat/completions",
        json=payload,
        timeout=(5, 300),
    )
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"]["content"]
    print(text)
except requests.exceptions.Timeout:
    print("Attesa scaduta: controllare server, carico e tempi.")
except requests.exceptions.ConnectionError:
    print("Connessione fallita: controllare server, URL e porta.")
except requests.exceptions.HTTPError:
    print("Errore HTTP:", response.status_code, response.text)
