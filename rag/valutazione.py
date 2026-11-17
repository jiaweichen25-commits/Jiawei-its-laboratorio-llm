"""Valutazione del retrieval: python -m rag.valutazione [--k 5]

Prima di cercare si decide quale ricetta dovrebbe comparire (fonte attesa, slide 21); poi si
registra dove compare davvero e con che score. La ricerca è deterministica: a parità di indice
e domande la tabella è sempre la stessa, quindi si confronta prima e dopo una modifica (slide 6).

Le domande senza risposta nel corpus (fonte attesa vuota) servono a vedere che la ricerca
restituisce comunque k risultati, con score simili agli altri (slide 9 e 22).
"""

import argparse
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from rag.archivio import Risultato
from rag.config import ErroreConfigurazione, carica_configurazione
from rag.ingestion import descrivi_errore

DOMANDE = Path(__file__).resolve().parent / "domande.json"


@dataclass(frozen=True)
class Domanda:
    domanda: str
    attese: list[int]               # numeri delle ricette che rispondono; vuota = nessuna risposta nel corpus
    capitolo: str | None = None     # filtro facoltativo
    propria: bool = False           # scritta da noi (slide 27), non presa dalle slide
    nota: str = ""


@dataclass(frozen=True)
class Riga:
    domanda: str
    attese: list[int]
    posizione: int | None           # classifica della prima fonte attesa tra i primi k; None = assente
    score_fonte: float | None
    score_primo: float | None
    primo: str                      # «89 · Gnocchi di patate»
    capitolo: str | None = None
    propria: bool = False


def carica_domande(percorso: Path = DOMANDE) -> list[Domanda]:
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    return [Domanda(d["domanda"], list(d.get("attese", [])), d.get("capitolo"), bool(d.get("propria", False)),
                    d.get("nota", "")) for d in dati]


def valuta(domande: list[Domanda], cerca_fn: Callable[[str, int, str | None], list[Risultato]], k: int) -> list[Riga]:
    righe = []
    for d in domande:
        risultati = cerca_fn(d.domanda, k, d.capitolo)
        trovato = next((r for r in risultati if r.numero in d.attese), None)
        primo = risultati[0] if risultati else None
        righe.append(Riga(
            domanda=d.domanda, attese=d.attese,
            posizione=trovato.classifica if trovato else None,
            score_fonte=trovato.score if trovato else None,
            score_primo=primo.score if primo else None,
            primo=f"{primo.numero} · {primo.titolo}" if primo else "—",
            capitolo=d.capitolo, propria=d.propria,
        ))
    return righe


def _score(valore: float | None) -> str:
    return "—" if valore is None else f"{valore:.3f}".replace(".", ",")


def tabella_markdown(righe: list[Riga], k: int) -> str:
    intestazione = ("| Domanda | Fonte attesa | Posizione | Score fonte | Score 1° | 1° risultato |\n"
                    "|---|---|---|---|---|---|")
    corpo = []
    for r in righe:
        domanda = r.domanda + (f" *(capitolo {r.capitolo})*" if r.capitolo else "") + (" ✎" if r.propria else "")
        attese = ", ".join(map(str, r.attese)) if r.attese else "— (nessuna)"
        posizione = "—" if not r.attese else (str(r.posizione) if r.posizione else "assente")
        corpo.append(f"| {domanda} | {attese} | {posizione} | {_score(r.score_fonte)} | {_score(r.score_primo)} | {r.primo} |")
    con_risposta = [r for r in righe if r.attese]
    trovate = sum(1 for r in con_risposta if r.posizione)
    riepilogo = (f"\nFonte attesa trovata tra i primi {k}: {trovate} su {len(con_risposta)}."
                 + (f" In prima posizione: {sum(1 for r in con_risposta if r.posizione == 1)}." if con_risposta else "")
                 + "\n✎ = domanda scritta per questo progetto (non presa dalle slide).")
    return "\n".join([intestazione, *corpo]) + "\n" + riepilogo


def main() -> int:
    for flusso in (sys.stdout, sys.stderr):
        flusso.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Valutazione della ricerca sulle domande con fonte attesa.")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--domande", type=Path, default=DOMANDE)
    argomenti = parser.parse_args()

    load_dotenv(override=False)
    try:
        cfg = carica_configurazione(os.environ)
    except ErroreConfigurazione as exc:
        print(exc, file=sys.stderr)
        return 1
    from rag.ricerca import cerca  # import qui: evita un import circolare tra ricerca e valutazione

    try:
        righe = valuta(carica_domande(argomenti.domande), lambda d, k, c: cerca(cfg, d, k=k, capitolo=c), argomenti.k)
    except Exception as exc:
        messaggio = descrivi_errore(exc, cfg)
        if messaggio is None:
            raise
        print(messaggio, file=sys.stderr)
        return 1
    print(f"Modello {cfg.embedding_model} · prefissi {'sì' if cfg.prefissi else 'no'} · chunk {cfg.chunk_dimensione}/"
          f"{cfg.chunk_overlap} · top-k {argomenti.k}\n")
    print(tabella_markdown(righe, argomenti.k))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
