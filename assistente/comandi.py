"""Lezione 6, step 5: comandi /prompts e /prompt del terminale (logica pura, senza server).

Un prompt MCP lo attiva l'UTENTE, in modo esplicito (slide 9 e 11). MCP però non definisce
un comando standard per farlo: la sintassi la decide la nostra CLI (slide 10):

    /prompts                                   elenca i prompt del server
    /prompt spiega argomento="MCP" livello=base   richiama un prompt con i suoi argomenti

Gli argomenti si controllano QUI, nell'host, sull'elenco ricevuto con prompts/list: un errore
blocca la richiesta prima di disturbare server e modello (slide 10, punto 4).
"""

import shlex


class ErroreComando(Exception):
    """Comando scritto male o argomenti non validi: si mostra all'utente, nessuna chiamata parte."""


def interpreta_prompt(riga: str) -> tuple[str, dict[str, str]]:
    """Da «/prompt nome a=1 b="x y"» a ("nome", {"a": "1", "b": "x y"}).

    shlex divide la riga come fa una shell: tiene insieme ciò che sta tra virgolette.
    """
    try:
        parti = shlex.split(riga)
    except ValueError:  # es. virgolette aperte e mai chiuse
        raise ErroreComando('Virgolette non chiuse: i valori con spazi vanno scritti come chiave="valore con spazi".') from None
    if len(parti) < 2:
        raise ErroreComando("Manca il nome del prompt. Uso: /prompt nome chiave=valore ... (elenco con /prompts)")

    nome, argomenti = parti[1], {}
    for parte in parti[2:]:
        chiave, uguale, valore = parte.partition("=")
        if not uguale or not chiave:
            raise ErroreComando(
                f"«{parte}» non è nella forma chiave=valore. "
                'I valori con spazi vanno tra virgolette: argomento="Model Context Protocol".'
            )
        if chiave in argomenti:
            raise ErroreComando(f"Argomento ripetuto: «{chiave}».")
        argomenti[chiave] = valore
    return nome, argomenti


def valida_argomenti(prompt, argomenti: dict[str, str]) -> None:
    """Controlla gli argomenti contro la dichiarazione del prompt ricevuta con prompts/list."""
    dichiarati = {a.name: a for a in (prompt.arguments or [])}
    sconosciuti = sorted(set(argomenti) - set(dichiarati))
    if sconosciuti:
        ammessi = ", ".join(dichiarati) or "nessuno"
        raise ErroreComando(
            f"Argomento sconosciuto per «{prompt.name}»: {', '.join(sconosciuti)}. Argomenti ammessi: {ammessi}."
        )
    mancanti = [nome for nome, a in dichiarati.items() if a.required and nome not in argomenti]
    if mancanti:
        raise ErroreComando(f"Manca l'argomento obbligatorio di «{prompt.name}»: {', '.join(mancanti)}.")


def formatta_elenco(prompts: list) -> str:
    """Testo per /prompts: nome, descrizione, argomenti e un esempio d'uso per ogni prompt."""
    if not prompts:
        return "Nessun prompt disponibile sul server MCP."
    blocchi = []
    for p in prompts:
        righe = [f"{p.name} — {p.description or '(senza descrizione)'}"]
        for a in p.arguments or []:
            tipo = "obbligatorio" if a.required else "facoltativo"
            righe.append(f"    {a.name} ({tipo}): {a.description or ''}".rstrip())
        esempio = " ".join(f'{a.name}="..."' for a in (p.arguments or []) if a.required)
        righe.append(f"    es.: /prompt {p.name} {esempio}".rstrip())
        blocchi.append("\n".join(righe))
    return "\n".join(blocchi)
