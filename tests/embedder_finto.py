"""Embedder finto per i test della lezione 7: nessuna chiamata a LM Studio.

Ogni parola del testo accende una delle 64 dimensioni del vettore (scelta con un hash stabile).
Testi con parole in comune hanno vettori vicini: basta per provare ingestion e ricerca, non per
misurare la qualità del recupero, che si misura solo con il modello vero.
"""

import hashlib
import math
import re

DIMENSIONE = 64


def _vettore(testo: str) -> list[float]:
    v = [0.0] * DIMENSIONE
    for parola in re.findall(r"\w+", testo.lower()):
        if len(parola) > 2:  # parole vuote come «di», «la»: ignorate
            v[int(hashlib.md5(parola.encode()).hexdigest(), 16) % DIMENSIONE] += 1.0
    norma = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norma for x in v] if any(v) else [1.0 / math.sqrt(DIMENSIONE)] * DIMENSIONE


class EmbedderFinto:
    def __init__(self, modello: str = "modello-finto", prefissi: bool = True):
        self.modello = modello
        self.prefissi = prefissi
        self.documenti_ricevuti: list[str] = []  # testi passati per l'indicizzazione, nell'ordine
        self.domande_ricevute: list[str] = []

    def documenti(self, testi: list[str]) -> list[list[float]]:
        self.documenti_ricevuti.extend(testi)
        return [_vettore(t) for t in testi]

    def domanda(self, testo: str) -> list[float]:
        self.domande_ricevute.append(testo)
        return _vettore(testo)
