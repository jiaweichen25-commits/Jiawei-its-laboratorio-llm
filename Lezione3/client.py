import json
import os
import requests
from dotenv import load_dotenv

load_dotenv(".env", override=False)

base_url = os.environ["LM_BASE_URL"].rstrip("/")
model = os.environ["LM_MODEL"]

SYSTEM = "Rispondi in italiano."

messages = [{"role": "system", "content": SYSTEM}]

while True:
    try:
        domanda = input("Tu> ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        break
    if domanda.lower() == "esci":
        break
    if not domanda:
        continue

    messages.append({"role": "user", "content": domanda})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 2048,
        "stream": True,
    }

    try:
        with requests.post(
            f"{base_url}/chat/completions",
            json=payload,
            stream=True,
            timeout=(5, 300),
        ) as response:
            response.raise_for_status()
            testo = ""
            for riga in response.iter_lines():
                riga = riga.decode("utf-8")
                if not riga.startswith("data: "):
                    continue
                dati = riga[len("data: "):]
                if dati == "[DONE]":
                    break
                delta = json.loads(dati)["choices"][0]["delta"]
                frammento = delta.get("content") or ""
                print(frammento, end="", flush=True)
                testo += frammento
            print()
        messages.append({"role": "assistant", "content": testo})
    except requests.exceptions.Timeout:
        messages.pop()
        print("Attesa scaduta: controllare server, carico e tempi.")
    except requests.exceptions.ConnectionError:
        messages.pop()
        print("Connessione fallita: controllare server, URL e porta.")
    except requests.exceptions.HTTPError:
        messages.pop()
        print("Errore HTTP:", response.status_code, response.text)
