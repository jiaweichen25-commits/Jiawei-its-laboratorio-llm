"""Client HTTP del servizio dell'agente (step 6), usato dal back-end.

Distingue due situazioni che il back-end tratta in modo diverso (slide 14, «errore chiaro»):
  - AgenteNonRaggiungibile: spento, sulla porta sbagliata o troppo lento → 503;
  - ErroreAgente: ha risposto, ma con un errore (es. LM Studio spento) → 502 con il suo messaggio.
"""

import httpx


class AgenteNonRaggiungibile(Exception):
    """Nessuna risposta dal servizio dell'agente."""


class ErroreAgente(Exception):
    """Il servizio dell'agente ha risposto con un codice di errore."""

    def __init__(self, codice: int, dettaglio: str):
        super().__init__(f"{codice}: {dettaglio}")
        self.codice = codice
        self.dettaglio = dettaglio


class AgenteHttp:
    def __init__(self, url: str, timeout: float = 600.0, transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/")
        # transport si sostituisce nei test con httpx.MockTransport: risposte finte, nessuna rete.
        self._http = httpx.Client(base_url=self.url, timeout=timeout, transport=transport)

    def _richiesta(self, metodo: str, percorso: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(metodo, percorso, **kwargs)
        except httpx.HTTPError as exc:  # connessione rifiutata, timeout, errori di rete
            raise AgenteNonRaggiungibile(f"{type(exc).__name__}: {exc}") from exc

    def conversazione(self, cronologia: list[dict], riassunto: str, domanda: str) -> dict:
        """POST /conversazione: un turno dell'agente. Restituisce il corpo JSON della risposta."""
        corpo = {"cronologia": cronologia, "riassunto": riassunto, "domanda": domanda, "prompt": None}
        risposta = self._richiesta("POST", "/conversazione", json=corpo)
        if risposta.status_code >= 400:
            try:
                dettaglio = risposta.json().get("detail", risposta.text)
            except ValueError:
                dettaglio = risposta.text
            raise ErroreAgente(risposta.status_code, str(dettaglio))
        return risposta.json()

    def stato(self) -> str:
        """«ok» se l'agente è pronto, altrimenti una frase che dice che cosa manca."""
        try:
            risposta = self._richiesta("GET", "/stato", timeout=10.0)
            valori = risposta.json()
        except AgenteNonRaggiungibile as exc:
            return f"non raggiungibile su {self.url} ({exc})"
        except ValueError:
            return f"risposta inattesa da {self.url}/stato"
        problemi = {k: v for k, v in valori.items() if v != "ok"}
        return "ok" if not problemi else "; ".join(f"{k}: {v}" for k, v in problemi.items())

    def chiudi(self) -> None:
        self._http.close()
