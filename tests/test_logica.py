"""Test della logica pura: orologio, calcolatrice sicura e convertitore di unità.

Queste funzioni non dipendono da LangChain, da HTTP o da MCP: sono la «logica di dominio»
che le tre varianti (locale, FastAPI, FastMCP) riutilizzano senza copiarla.
"""

from datetime import datetime, timezone

import pytest

from assistente.logica import ErroreStrumento, calcola, converti, ora_nel_fuso

ISTANTE = datetime(2026, 10, 26, 15, 42, 10, tzinfo=timezone.utc)


# ---------------------------------------------------------------- orologio

def test_ora_nel_fuso_tokyo():
    assert ora_nel_fuso("Asia/Tokyo", ISTANTE) == "2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì"


def test_ora_nel_fuso_sconosciuto():
    # Slide 23: per un fuso non valido serve un errore, mai un'ora inventata.
    with pytest.raises(ErroreStrumento, match="«Mars/Olympus»"):
        ora_nel_fuso("Mars/Olympus", ISTANTE)


# ---------------------------------------------------------------- calcolatrice

@pytest.mark.parametrize("espressione, atteso", [
    ("(2+3)*4", "(2+3)*4 = 20"),
    ("7/2", "7/2 = 3.5"),
    ("-2**2", "-2**2 = -4"),          # come in Python: la potenza lega più del segno
    ("17 // 5", "17 // 5 = 3"),
    ("17 % 5", "17 % 5 = 2"),
    ("1/3", "1/3 = 0.333333333333"),  # float mostrati con 12 cifre significative
    ("2**10", "2**10 = 1024"),
    ("+4.5 - 0.5", "+4.5 - 0.5 = 4"),
])
def test_calcola_espressioni_valide(espressione, atteso):
    assert calcola(espressione) == atteso


@pytest.mark.parametrize("espressione, motivo", [
    ("__import__('os')", "non consentit"),  # chiamata di funzione: il motivo per cui non si usa eval
    ("x + 1", "non consentit"),             # nomi di variabile
    ("(1).real", "non consentit"),          # accesso ad attributi
    ("True + 1", "non consentit"),          # i booleani non sono numeri per la calcolatrice
    ("1j * 2", "non consentit"),            # numeri complessi
    ("'a' * 3", "non consentit"),           # stringhe
    ("1 < 2", "non consentit"),             # confronti
    ("2**99999", "troppo grande"),          # esponente enorme: rischio di bloccare il programma
    ("9**9**9", "troppo grande"),
    ("10.0**400", "troppo grande"),         # overflow dei float
    ("1/0", "divisione per zero"),
    ("5 % 0", "divisione per zero"),
    ("1+", "sintassi"),
    ("", "vuota"),
    ("1+" * 100 + "1", "troppo lunga"),     # 201 caratteri
])
def test_calcola_rifiuta_input_non_validi(espressione, motivo):
    with pytest.raises(ErroreStrumento, match=motivo):
        calcola(espressione)


# ---------------------------------------------------------------- convertitore

@pytest.mark.parametrize("valore, da, a, atteso", [
    (10, "km", "mi", "10 km = 6.21371 mi"),
    (1, "m", "cm", "1 m = 100 cm"),
    (12, "in", "ft", "12 in = 1 ft"),
    (1, "lb", "g", "1 lb = 453.592 g"),
    (2.5, "kg", "kg", "2.5 kg = 2.5 kg"),
    (100, "C", "F", "100 C = 212 F"),       # temperature: serve anche l'offset, non solo un fattore
    (0, "C", "K", "0 C = 273.15 K"),
    (32, "F", "C", "32 F = 0 C"),
])
def test_converti_unita_compatibili(valore, da, a, atteso):
    assert converti(valore, da, a) == atteso


def test_converti_categorie_incompatibili():
    with pytest.raises(ErroreStrumento) as errore:
        converti(1, "kg", "m")
    messaggio = str(errore.value)
    assert "massa" in messaggio and "lunghezza" in messaggio


def test_converti_unita_fuori_elenco():
    with pytest.raises(ErroreStrumento, match="«parsec»"):
        converti(1, "parsec", "m")


# ---------------------------------------------------------------- correzioni dopo la revisione

@pytest.mark.parametrize("espressione", ["(-8)**0.5", "((-1)**0.5)//1", "((-1)**0.5)%2"])
def test_calcola_rifiuta_risultati_non_reali(espressione):
    # La radice di un numero negativo darebbe un numero complesso: non è un risultato da calcolatrice.
    with pytest.raises(ErroreStrumento, match="non reale"):
        calcola(espressione)


@pytest.mark.parametrize("espressione", ["1e999", "1e999-1e999", "-1e999"])
def test_calcola_rifiuta_infinito_e_nan(espressione):
    # inf e nan non sono risultati: presentarli come successo sarebbe un «falso successo» (slide 31).
    with pytest.raises(ErroreStrumento, match="troppo grande|non valido"):
        calcola(espressione)
