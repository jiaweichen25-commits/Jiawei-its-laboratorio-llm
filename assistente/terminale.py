"""Interfaccia da terminale. Dalla lezione 6, step 6, è un CLIENT del servizio dell'agente.

Il terminale non esegue più il grafo: manda ogni domanda al servizio (POST /conversazione)
e mostra l'esito. La memoria della sessione (cronologia e riassunto) la tiene qui, perché
il servizio è senza stato: a ogni turno la invia e la sostituisce con quella restituita.
"""

import logging
import sys

from assistente.cliente_agente import ErroreServizio
from assistente.comandi import ErroreComando, formatta_elenco, interpreta_prompt, valida_argomenti

log = logging.getLogger("assistente.terminale")


def formatta_traccia(nome: str, args: dict, risultato: str) -> str:
    argomenti = ", ".join(
        f'{chiave}="{valore}"' if isinstance(valore, str) else f"{chiave}={valore!r}"
        for chiave, valore in args.items()
    )
    return f"[strumento] {nome}({argomenti}) → {risultato}"


def _prompt_da_comando(riga: str, servizio) -> dict:
    """Step 5: «/prompt nome a=b» → {"nome", "argomenti"}, controllato sull'elenco del servizio.

    Il controllo si fa qui, prima di inviare: un errore non costa una chiamata al modello.
    Il servizio lo ripete comunque, perché anche altri client (il back-end) lo useranno.
    """
    nome, argomenti = interpreta_prompt(riga)
    catalogo = {p.name: p for p in servizio.prompts()}
    if nome not in catalogo:
        raise ErroreComando(f"Prompt sconosciuto: «{nome}». Elenco con /prompts.")
    valida_argomenti(catalogo[nome], argomenti)
    return {"nome": nome, "argomenti": argomenti}


def _mostra(esito: dict, scrivi) -> None:
    """Stampa l'esito di un turno: prima le tracce (riassunto, strumenti, revisore), poi la risposta."""
    if esito.get("messaggi_riassunti"):
        scrivi(f"[riassunto] cronologia compressa: {esito['messaggi_riassunti']} messaggi sostituiti")
    for s in esito.get("strumenti_usati", []):
        scrivi(formatta_traccia(s["nome"], s["argomenti"], s["risultato"]))
    for motivo in esito.get("revisioni", []):
        scrivi(f"[revisore] non coerente: {motivo}")
    scrivi(esito["risposta"])


def conversa(servizio, leggi=input, out=sys.stdout) -> None:
    """Ciclo della sessione. `servizio` è un ClienteAgente (nei test un finto con gli stessi metodi)."""

    def scrivi(testo: str) -> None:
        out.write(testo + "\n")
        out.flush()

    cronologia: list[dict] = []
    riassunto = ""
    try:
        while True:
            try:
                riga = leggi("Tu> ").strip()
            except EOFError:
                scrivi("")
                return
            if riga.lower() == "esci":
                return
            if not riga:
                continue

            domanda, prompt = riga, None
            if riga.startswith("/"):
                nome_comando = riga.split(maxsplit=1)[0].lower()
                try:
                    if nome_comando == "/prompts":
                        scrivi(formatta_elenco(servizio.prompts()))
                        continue
                    if nome_comando != "/prompt":
                        scrivi(f"Comando sconosciuto: {nome_comando}. Comandi disponibili: /prompts, /prompt, esci.")
                        continue
                    domanda, prompt = None, _prompt_da_comando(riga, servizio)
                except (ErroreComando, ErroreServizio) as exc:
                    scrivi(str(exc))
                    continue

            scrivi("[agente] in attesa della risposta...")
            try:
                esito = servizio.conversazione(cronologia, riassunto, domanda=domanda, prompt=prompt)
            except ErroreServizio as exc:
                # La cronologia resta quella di prima: il turno fallito non lascia tracce.
                log.error("turno fallito: %s", exc)
                scrivi(str(exc))
                continue
            cronologia, riassunto = esito["cronologia"], esito["riassunto"]
            _mostra(esito, scrivi)
    except KeyboardInterrupt:
        scrivi("")
