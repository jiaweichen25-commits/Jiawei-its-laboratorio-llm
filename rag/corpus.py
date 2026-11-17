"""Lettura del ricettario: pulizia del testo e divisione in ricette (scelta 1 della specifica).

Un documento è una ricetta, con numero, titolo e capitolo. Tutto il resto del libro
(prefazione, introduzioni dei capitoli, appendice, menu, indice) viene scartato.

Com'è fatto il file (slide 26):
  - intestazione e licenza del Project Gutenberg all'inizio e alla fine;
  - capitoli in maiuscolo su una riga, per esempio «FRITTI»;
  - ricette nel formato «89. Gnocchi di patate»;
  - righe spezzate a circa 70 caratteri, paragrafi separati da una riga vuota.
"""

import re
import unicodedata
from dataclasses import dataclass

# I 23 capitoli, nell'ordine del libro, scritti come compariranno nel payload e nei filtri.
CAPITOLI = (
    "Brodi, gelatina e sughi",
    "Minestre in brodo",
    "Minestre asciutte e di magro",
    "Principii",
    "Salse",
    "Uova",
    "Paste e pastelle",
    "Ripieni",
    "Fritti",
    "Lesso",
    "Tramessi",
    "Umidi",
    "Rifreddi",
    "Erbaggi e legumi",
    "Piatti di pesce",
    "Arrosti",
    "Pasticceria",
    "Torte e dolci al cucchiaio",
    "Siroppi",
    "Conserve",
    "Liquori",
    "Gelati",
    "Cose diverse",
)
# Nel file i capitoli sono in maiuscolo: «PIATTI DI PESCE» → «Piatti di pesce».
_PER_MAIUSCOLO = {c.upper(): c for c in CAPITOLI}
# Intestazioni che chiudono la ricetta in corso senza essere un capitolo: «MINESTRE» raggruppa
# «Minestre in brodo» e «Minestre asciutte e di magro» ed è seguita da un'introduzione da scartare.
# Le altre righe in maiuscolo («PASTA FROLLA», «RICETTA A», «PRIMA RICETTA»…) sono parti di una
# ricetta e restano nel suo testo.
_SEPARATORI = {"MINESTRE"}

_TITOLO = re.compile(r"^(\d{1,3})\. (\S.*)$")
_INIZIO_GUTENBERG = re.compile(r"^\*\*\* START OF TH(E|IS) PROJECT GUTENBERG EBOOK.*$", re.MULTILINE)
_FINE_GUTENBERG = re.compile(r"^\*\*\* END OF TH(E|IS) PROJECT GUTENBERG EBOOK.*$", re.MULTILINE)


@dataclass(frozen=True)
class Ricetta:
    numero: int
    titolo: str
    capitolo: str
    testo: str  # paragrafi separati da una riga vuota ("\n\n"); dentro un paragrafo, una riga sola


def pulisci(testo_grezzo: str) -> str:
    """Toglie intestazione e licenza del Project Gutenberg, i fine riga di Windows e i caratteri di controllo."""
    testo = testo_grezzo.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    inizio = _INIZIO_GUTENBERG.search(testo)
    if inizio:
        testo = testo[inizio.end():]
    fine = _FINE_GUTENBERG.search(testo)
    if fine:
        testo = testo[:fine.start()]
    # Caratteri di controllo (categoria «Cc»), tranne l'a capo che serve a riconoscere righe e paragrafi.
    return "".join(c for c in testo if c == "\n" or unicodedata.category(c) != "Cc")


def _paragrafi(righe: list[str]) -> str:
    """Riunisce le righe spezzate: dentro un paragrafo con uno spazio, tra paragrafi con una riga vuota."""
    paragrafi, corrente = [], []
    for riga in righe:
        if riga.strip():
            corrente.append(riga.strip())
        elif corrente:
            paragrafi.append(" ".join(" ".join(corrente).split()))
            corrente = []
    if corrente:
        paragrafi.append(" ".join(" ".join(corrente).split()))
    return "\n\n".join(paragrafi)


def leggi_ricette(testo: str) -> list[Ricetta]:
    """Divide il testo pulito nelle 790 ricette.

    Un titolo di ricetta è una riga «N. Titolo» in cui N è esattamente il numero atteso (il
    precedente + 1). Così una riga di testo che comincia per caso con un numero (un rimando
    come «…balsamella N.» / «137. Mettete il composto…») non viene scambiata per una ricetta.
    Il testo di una ricetta finisce dove comincia la successiva, un capitolo nuovo o l'appendice.
    """
    righe = testo.split("\n")
    ricette = []
    atteso, capitolo = 1, None
    titolo_corrente, numero_corrente, capitolo_corrente, corpo = None, None, None, []

    def chiudi():
        if titolo_corrente is not None:
            ricette.append(Ricetta(numero_corrente, titolo_corrente, capitolo_corrente, _paragrafi(corpo)))

    for riga in righe:
        pulita = riga.strip()
        if pulita in _PER_MAIUSCOLO or pulita in _SEPARATORI:
            # Capitolo nuovo: chiude la ricetta in corso (il titolo del capitolo non le appartiene).
            # L'eventuale introduzione del capitolo, fino alla prima ricetta, viene scartata.
            chiudi()
            titolo_corrente, corpo = None, []
            capitolo = _PER_MAIUSCOLO.get(pulita, capitolo)
            continue
        if pulita == "APPENDICE" and atteso > 790:
            break  # dopo l'ultima ricetta: l'appendice e il resto non sono ricette
        m = _TITOLO.match(riga)
        if m and int(m.group(1)) == atteso and capitolo is not None:
            chiudi()
            numero_corrente, titolo_corrente, capitolo_corrente, corpo = atteso, m.group(2).strip(), capitolo, []
            atteso += 1
            continue
        if titolo_corrente is not None:
            corpo.append(riga)
    chiudi()
    return ricette
