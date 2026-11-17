"""Divisione delle ricette in chunk (scelta 2 della specifica) e identificativi stabili (scelta 4).

Strategia: «per sezione, poi a paragrafi le sezioni troppo lunghe» (slide 15), dove la sezione
è la ricetta.
  - ricetta entro `dimensione` caratteri → un chunk solo;
  - ricetta più lunga → si riuniscono paragrafi consecutivi finché stanno in `dimensione`;
    ogni chunk dopo il primo ricomincia con la coda del precedente (`overlap` caratteri, da inizio parola);
  - un paragrafo da solo più lungo di `dimensione` → tagliato a finestra, sempre a parole intere.
"""

import uuid
from dataclasses import dataclass

from rag.corpus import Ricetta

# Spazio dei nomi fisso per gli UUID v5: stesso testo → stesso UUID, su qualsiasi computer.
_SPAZIO_ID = uuid.uuid5(uuid.NAMESPACE_URL, "its-laboratorio-llm/rag/artusi")


@dataclass(frozen=True)
class Chunk:
    documento_id: str   # «ricetta-089»
    numero: int
    titolo: str
    capitolo: str
    posizione: int      # 0, 1, 2… nell'ordine della ricetta
    chunk_totali: int   # quanti chunk ha la ricetta: 1 = il chunk è la ricetta intera
    testo: str


def id_punto(documento_id: str, posizione: int) -> str:
    """ID del punto in Qdrant: UUID versione 5, deterministico (slide 18, strategia A).

    Qdrant accetta come ID solo interi o UUID. L'UUID v5 si calcola da un testo: rieseguendo
    l'ingestion lo stesso chunk riceve lo stesso ID e viene sostituito, non duplicato.
    """
    return str(uuid.uuid5(_SPAZIO_ID, f"{documento_id}:{posizione}"))


def _coda(testo: str, overlap: int) -> str:
    """Gli ultimi `overlap` caratteri di `testo`, cominciando da una parola intera."""
    if overlap == 0 or len(testo) <= overlap:
        return "" if overlap == 0 else testo
    coda = testo[-overlap:]
    spazio = coda.find(" ")
    return coda[spazio + 1:] if spazio != -1 else coda


def _finestre(paragrafo: str, dimensione: int, overlap: int) -> list[str]:
    """Taglia un paragrafo troppo lungo in pezzi di parole intere, con sovrapposizione."""
    parole, pezzi, corrente = paragrafo.split(), [], ""
    for parola in parole:
        candidato = f"{corrente} {parola}" if corrente else parola
        if len(candidato) <= dimensione:
            corrente = candidato
            continue
        pezzi.append(corrente)
        ripresa = _coda(corrente, overlap)
        corrente = f"{ripresa} {parola}" if ripresa and len(ripresa) + 1 + len(parola) <= dimensione else parola
    if corrente:
        pezzi.append(corrente)
    return pezzi


def dividi(ricetta: Ricetta, dimensione: int, overlap: int) -> list[Chunk]:
    if dimensione <= 0 or not 0 <= overlap < dimensione:
        raise ValueError(f"serve dimensione > 0 e 0 <= overlap < dimensione (dimensione={dimensione}, overlap={overlap})")

    # 1) Paragrafi, con quelli troppo lunghi già tagliati a finestra.
    unita = []
    for paragrafo in ricetta.testo.split("\n\n"):
        unita.extend([paragrafo] if len(paragrafo) <= dimensione else _finestre(paragrafo, dimensione, overlap))

    # 2) Paragrafi consecutivi riuniti finché stanno nella dimensione; ogni chunk nuovo riparte dalla coda del precedente.
    testi, corrente = [], ""
    for pezzo in unita:
        candidato = f"{corrente}\n\n{pezzo}" if corrente else pezzo
        if len(candidato) <= dimensione:
            corrente = candidato
            continue
        testi.append(corrente)
        ripresa = _coda(corrente, overlap)
        corrente = f"{ripresa}\n\n{pezzo}" if ripresa and len(ripresa) + 2 + len(pezzo) <= dimensione else pezzo
    if corrente:
        testi.append(corrente)

    documento_id = f"ricetta-{ricetta.numero:03d}"
    return [
        Chunk(documento_id, ricetta.numero, ricetta.titolo, ricetta.capitolo, posizione, len(testi), testo)
        for posizione, testo in enumerate(testi)
    ]
