"""Client del modello di embedding servito da LM Studio (endpoint /v1/embeddings).

Generazione ed embedding sono compiti distinti (slide 10): qui il modello riceve testi e
restituisce vettori di numeri, uno per testo. Lo stesso modello, con la stessa configurazione,
serve sia per i documenti (ingestion) sia per le domande (ricerca).

Prefissi: il modello nomic-embed-text è addestrato a ricevere «search_document: » davanti ai
testi da indicizzare e «search_query: » davanti alle domande, e la sua documentazione chiede di
usarli. Si possono spegnere dalla configurazione per un confronto.
"""

import httpx

PREFISSO_DOCUMENTO = "search_document: "
PREFISSO_DOMANDA = "search_query: "


class ErroreEmbedding(Exception):
    """LM Studio non raggiungibile, modello non caricato o risposta inattesa."""


class EmbedderLMStudio:
    def __init__(self, base_url: str, modello: str, prefissi: bool = True, lotto: int = 32,
                 timeout: float = 120.0, transport: httpx.BaseTransport | None = None):
        self.modello = modello
        self.prefissi = prefissi
        self._lotto = lotto  # quanti testi per richiesta: meno richieste, ma ognuna più lunga
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def _chiama(self, testi: list[str]) -> list[list[float]]:
        try:
            risposta = self._http.post(self._url, json={"model": self.modello, "input": testi})
        except httpx.HTTPError as exc:
            raise ErroreEmbedding(
                f"LM Studio non raggiungibile su {self._url}: avviare il server e caricare il modello «{self.modello}» "
                f"({type(exc).__name__})."
            ) from None
        if risposta.status_code >= 400:
            raise ErroreEmbedding(
                f"LM Studio ha risposto {risposta.status_code} per il modello «{self.modello}»: {risposta.text[:300]}"
            )
        try:
            dati = risposta.json()["data"]
            # LM Studio restituisce un elemento per testo con il suo «index»: si riordina per sicurezza.
            return [elemento["embedding"] for elemento in sorted(dati, key=lambda e: e["index"])]
        except (ValueError, KeyError, TypeError) as exc:
            raise ErroreEmbedding(f"Risposta inattesa da {self._url}: {risposta.text[:300]}") from exc

    def documenti(self, testi: list[str]) -> list[list[float]]:
        """Vettori dei testi da indicizzare, calcolati a lotti."""
        prefisso = PREFISSO_DOCUMENTO if self.prefissi else ""
        vettori = []
        for inizio in range(0, len(testi), self._lotto):
            vettori.extend(self._chiama([prefisso + t for t in testi[inizio:inizio + self._lotto]]))
        return vettori

    def domanda(self, testo: str) -> list[float]:
        """Vettore di una domanda, con lo stesso modello dei documenti."""
        return self._chiama([(PREFISSO_DOMANDA if self.prefissi else "") + testo])[0]
