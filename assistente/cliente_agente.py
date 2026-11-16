"""Lezione 6, step 6: client HTTP del servizio dell'agente, usato dalla CLI.

Traduce gli errori di rete e i codici HTTP in un'unica eccezione con un messaggio leggibile,
così il terminale non deve conoscere httpx.
"""

import httpx
from mcp.types import Prompt, PromptArgument


class ErroreServizio(Exception):
    """Il servizio dell'agente non risponde o ha risposto con un errore."""


class ClienteAgente:
    def __init__(self, url: str, timeout: float = 600.0, transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/")
        # transport si sostituisce nei test con httpx.MockTransport (nessuna rete).
        self._http = httpx.Client(base_url=self.url, timeout=timeout, transport=transport)

    def _richiesta(self, metodo: str, percorso: str, accetta_503: bool = False, **kwargs):
        try:
            risposta = self._http.request(metodo, percorso, **kwargs)
        except httpx.ConnectError:
            raise ErroreServizio(
                f"Servizio agente non raggiungibile su {self.url}. Avvialo con: "
                ".\\.venv\\Scripts\\python.exe -m uvicorn assistente.servizio_agente:app --port 8001"
            ) from None
        except httpx.TimeoutException:
            raise ErroreServizio(f"Il servizio agente non ha risposto in tempo ({self._http.timeout.read:.0f} s).") from None
        except httpx.HTTPError as exc:
            raise ErroreServizio(f"Errore di comunicazione con il servizio agente: {exc}") from None
        if risposta.status_code >= 400 and not (accetta_503 and risposta.status_code == 503):
            try:
                dettaglio = risposta.json().get("detail", risposta.text)
            except ValueError:
                dettaglio = risposta.text
            raise ErroreServizio(f"Errore {risposta.status_code} dal servizio agente: {dettaglio}")
        return risposta.json()

    def conversazione(self, cronologia: list[dict], riassunto: str = "", domanda: str | None = None,
                      prompt: dict | None = None) -> dict:
        """POST /conversazione: un turno. Restituisce il corpo JSON della risposta."""
        corpo = {"cronologia": cronologia, "riassunto": riassunto, "domanda": domanda, "prompt": prompt}
        return self._richiesta("POST", "/conversazione", json=corpo)

    def prompts(self) -> list[Prompt]:
        """GET /prompts, convertiti negli oggetti MCP che comandi.py sa già controllare e formattare."""
        return [
            Prompt(
                name=p["nome"],
                description=p["descrizione"],
                arguments=[PromptArgument(name=a["nome"], description=a["descrizione"], required=a["obbligatorio"])
                           for a in p["argomenti"]],
            )
            for p in self._richiesta("GET", "/prompts")
        ]

    def stato(self) -> dict:
        """GET /stato. Un 503 non è un'eccezione: il corpo dice che cosa manca."""
        return self._richiesta("GET", "/stato", accetta_503=True)
