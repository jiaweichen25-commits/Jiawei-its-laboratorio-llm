"""Logica di dominio condivisa da tutte le varianti: orologio, calcolatrice sicura, convertitore.

Perché un modulo separato (slide 3 e 17): la logica dell'orologio deve restare UNA sola, mentre
cambia soltanto il «percorso» con cui l'agente la raggiunge:

    variante locale   →  strumenti.py      chiama queste funzioni direttamente (stesso processo)
    variante FastAPI  →  servizio_api.py   le espone su HTTP, l'agente usa wrapper_http.py
    variante FastMCP  →  server_mcp.py     le espone con MCP, l'agente usa client_mcp.py

Qui non c'è nulla di LangChain, HTTP o MCP: solo Python puro, facile da testare.
In caso di problema le funzioni sollevano ErroreStrumento; ogni variante decide poi come
trasformarlo (testo «Errore: ...», risposta HTTP 400, oppure errore MCP con is_error=True).
"""

import ast  # «Abstract Syntax Tree»: trasforma il testo dell'espressione in un albero da ispezionare
import operator
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ErroreStrumento(ValueError):
    """Input non valido per uno strumento: il messaggio è pensato per essere letto dal modello."""


# =============================================================================
# Orologio
# =============================================================================

GIORNI = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")


def ora_utc() -> datetime:
    """L'istante attuale in UTC. Nei test si sostituisce con un istante fisso."""
    return datetime.now(timezone.utc)


def ora_nel_fuso(fuso: str, adesso: datetime) -> str:
    """Converte l'istante `adesso` nel fuso IANA indicato, es. «Asia/Tokyo».

    Risultato: «2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì» → data e ora ISO con l'offset,
    il nome del fuso e il giorno della settimana (il contratto della slide 17).
    """
    try:
        zona = ZoneInfo(fuso)  # cerca il fuso nel database IANA (pacchetto tzdata)
    except (ZoneInfoNotFoundError, ValueError):
        # ValueError arriva per nomi «strani» come "../etc": vanno rifiutati come gli altri.
        raise ErroreStrumento(f"fuso orario sconosciuto: «{fuso}»") from None
    ora_locale = adesso.astimezone(zona)
    return f"{ora_locale.isoformat(timespec='seconds')} ({fuso}), {GIORNI[ora_locale.weekday()]}"


# =============================================================================
# Calcolatrice sicura (slide 25: «espressioni aritmetiche senza eval»)
# =============================================================================
#
# Perché NON eval(): eval esegue qualunque codice Python. Se il modello (o l'utente) scrivesse
# «__import__('os').remove('file')», eval lo eseguirebbe davvero. Invece:
#   1. ast.parse trasforma il testo in un albero di nodi SENZA eseguirlo;
#   2. _valuta visita l'albero e accetta solo i tipi di nodo della «lista bianca» qui sotto;
#   3. qualsiasi altro nodo (nomi, chiamate, attributi, stringhe...) viene rifiutato esplicitamente.

LUNGHEZZA_MASSIMA = 200   # caratteri: un'espressione più lunga non è una richiesta ragionevole
ESPONENTE_MASSIMO = 1000  # 2**99999 bloccherebbe il programma per calcolare un numero enorme
RISULTATO_MASSIMO = 1e100

# Lista bianca: tipo di nodo dell'albero → funzione Python che esegue l'operazione.
OPERAZIONI_BINARIE = {
    ast.Add: operator.add,           # a + b
    ast.Sub: operator.sub,           # a - b
    ast.Mult: operator.mul,          # a * b
    ast.Div: operator.truediv,       # a / b
    ast.FloorDiv: operator.floordiv, # a // b
    ast.Mod: operator.mod,           # a % b
    ast.Pow: operator.pow,           # a ** b
}
OPERAZIONI_UNARIE = {
    ast.UAdd: operator.pos,  # +a
    ast.USub: operator.neg,  # -a
}


def _controlla_grandezza(numero: int | float) -> int | float:
    """Rifiuta risultati enormi: proteggono memoria e tempo di calcolo."""
    if abs(numero) > RISULTATO_MASSIMO:
        raise ErroreStrumento("risultato troppo grande")
    return numero


def _valuta(nodo: ast.AST) -> int | float:
    """Calcola il valore di un nodo dell'albero, accettando solo la lista bianca."""
    if isinstance(nodo, ast.Expression):  # radice dell'albero creata da mode="eval"
        return _valuta(nodo.body)

    if isinstance(nodo, ast.Constant):
        # type(...) e non isinstance: True è un int per Python, ma non è un numero per noi.
        if type(nodo.value) in (int, float):
            return nodo.value
        raise ErroreStrumento(f"operazione non consentita: valore {nodo.value!r} non numerico")

    if isinstance(nodo, ast.UnaryOp) and type(nodo.op) in OPERAZIONI_UNARIE:
        return OPERAZIONI_UNARIE[type(nodo.op)](_valuta(nodo.operand))

    if isinstance(nodo, ast.BinOp) and type(nodo.op) in OPERAZIONI_BINARIE:
        sinistra = _valuta(nodo.left)
        destra = _valuta(nodo.right)
        if isinstance(nodo.op, ast.Pow) and abs(destra) > ESPONENTE_MASSIMO:
            raise ErroreStrumento("risultato troppo grande: esponente oltre 1000")
        try:
            return _controlla_grandezza(OPERAZIONI_BINARIE[type(nodo.op)](sinistra, destra))
        except ZeroDivisionError:
            raise ErroreStrumento("divisione per zero") from None
        except OverflowError:  # es. 10.0**400 supera il massimo dei float
            raise ErroreStrumento("risultato troppo grande") from None

    # Tutto il resto: Name (x), Call (f()), Attribute (a.b), Compare (1<2), stringhe...
    raise ErroreStrumento(f"operazione non consentita: «{type(nodo).__name__}»")


def calcola(espressione: str) -> str:
    """Calcola un'espressione aritmetica, es. «(2+3)*4» → «(2+3)*4 = 20».

    Ammessi: numeri interi e decimali, + - * / // % ** e parentesi.
    """
    testo = espressione.strip()
    if not testo:
        raise ErroreStrumento("espressione vuota")
    if len(testo) > LUNGHEZZA_MASSIMA:
        raise ErroreStrumento(f"espressione troppo lunga (massimo {LUNGHEZZA_MASSIMA} caratteri)")
    try:
        albero = ast.parse(testo, mode="eval")  # mode="eval": una sola espressione, niente istruzioni
    except SyntaxError:
        raise ErroreStrumento(f"sintassi non valida: «{testo}»") from None
    risultato = _valuta(albero)
    # Gli interi si mostrano esatti; i decimali con 12 cifre significative (1/3 → 0.333333333333).
    mostrato = str(risultato) if isinstance(risultato, int) else format(risultato, ".12g")
    return f"{testo} = {mostrato}"


# =============================================================================
# Convertitore di unità (slide 25: «unità ammesse come elenco chiuso»)
# =============================================================================

# Elenco chiuso delle unità: diventa un «enum» nello schema JSON del tool MCP, quindi il modello
# vede in anticipo quali valori può usare e il server rifiuta tutto il resto.
Unita = Literal["mm", "cm", "m", "km", "in", "ft", "mi", "g", "kg", "lb", "oz", "C", "F", "K"]

# Per lunghezza e massa basta un fattore verso l'unità base (metro, grammo).
FATTORI = {
    "lunghezza": {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
                  "in": 0.0254, "ft": 0.3048, "mi": 1609.344},
    "massa": {"g": 1.0, "kg": 1000.0, "lb": 453.59237, "oz": 28.349523125},
}
# La temperatura NON è proporzionale (0 °C non è 0 K): serve una formula con offset.
VERSO_KELVIN = {
    "C": lambda v: v + 273.15,
    "F": lambda v: (v - 32) * 5 / 9 + 273.15,
    "K": lambda v: v,
}
DA_KELVIN = {
    "C": lambda k: k - 273.15,
    "F": lambda k: (k - 273.15) * 9 / 5 + 32,
    "K": lambda k: k,
}


def _categoria(unita: str) -> str:
    """Restituisce «lunghezza», «massa» o «temperatura»; errore per unità fuori elenco."""
    for nome, tabella in FATTORI.items():
        if unita in tabella:
            return nome
    if unita in VERSO_KELVIN:
        return "temperatura"
    ammesse = ", ".join([*FATTORI["lunghezza"], *FATTORI["massa"], *VERSO_KELVIN])
    raise ErroreStrumento(f"unità non ammessa: «{unita}». Unità ammesse: {ammesse}")


def converti(valore: float, da: str, a: str) -> str:
    """Converte `valore` dall'unità `da` all'unità `a`, es. (10, "km", "mi") → «10 km = 6.21371 mi»."""
    categoria_da, categoria_a = _categoria(da), _categoria(a)
    if categoria_da != categoria_a:
        # Slide 25: «errore per conversioni incompatibili» (non si convertono chili in metri).
        raise ErroreStrumento(
            f"conversione impossibile: «{da}» è {categoria_da}, «{a}» è {categoria_a}"
        )
    if categoria_da == "temperatura":
        risultato = DA_KELVIN[a](VERSO_KELVIN[da](valore))
    else:
        tabella = FATTORI[categoria_da]
        risultato = valore * tabella[da] / tabella[a]  # prima verso l'unità base, poi verso `a`
    # 6 cifre significative: abbastanza precise e senza code come 1.0000000000000002.
    return f"{format(valore, '.6g')} {da} = {format(risultato, '.6g')} {a}"
