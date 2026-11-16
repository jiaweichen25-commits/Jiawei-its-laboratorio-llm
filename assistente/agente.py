"""Lezione 6, step 6: l'agente separato dall'interfaccia, SENZA STATO.

Prima il terminale eseguiva il grafo e stampava mentre arrivavano i pezzi. Ora un turno è
una funzione: riceve cronologia e riassunto dal chiamante e restituisce un EsitoTurno con la
risposta, gli strumenti usati e la cronologia aggiornata (slide 13). Chi chiama, il servizio
HTTP e attraverso di lui la CLI o il back-end, decide che cosa farne e dove conservarla.

    cronologia (dal chiamante) → grafo (riassunto, router, modello ⇄ strumenti, revisore) → EsitoTurno
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from assistente.client_mcp import ClienteMCP, crea_strumenti_mcp, trasporto_stdio
from assistente.comandi import ErroreComando, valida_argomenti
from assistente.config import Configurazione, verifica_modello
from assistente.controllo import e_revisione
from assistente.grafo import LIMITE_PASSAGGI, OpzioniGrafo, costruisci_grafo
from assistente.modello import crea_modello
from assistente.preferenze import URI_PREFERENZE, carica_preferenze
from assistente.varianti import strumenti_per_variante

log = logging.getLogger("assistente.agente")


@dataclass
class EsitoTurno:
    """Tutto ciò che un turno restituisce al chiamante (è anche il corpo della risposta HTTP)."""

    risposta: str
    cronologia: list[dict]                                # solo messaggi da chat: {"ruolo", "testo"}
    riassunto: str = ""
    strumenti_usati: list[dict] = field(default_factory=list)  # {"nome", "argomenti", "risultato"}
    rifiutata: bool = False                               # step 1: domanda fuori ambito
    revisioni: list[str] = field(default_factory=list)    # step 2: motivi delle bocciature del revisore
    messaggi_riassunti: int = 0                           # step 3: messaggi sostituiti dal riassunto


# ---------------------------------------------------------------------- cronologia da e verso la chat

def da_cronologia(cronologia: list[dict]) -> list[BaseMessage]:
    """Dal formato della chat ({"ruolo", "testo"}) ai messaggi LangChain per il grafo."""
    return [HumanMessage(m["testo"]) if m["ruolo"] == "utente" else AIMessage(m["testo"]) for m in cronologia]


def a_cronologia(messaggi: list[BaseMessage]) -> list[dict]:
    """Dai messaggi del grafo a quelli che una chat mostra: domande dell'utente e risposte finali.

    Restano fuori le richieste di strumento, i risultati (ToolMessage), le indicazioni del
    revisore e le bozze che il revisore ha scartato (quelle seguite da un'indicazione).
    """
    chat = []
    for i, m in enumerate(messaggi):
        seguente = messaggi[i + 1] if i + 1 < len(messaggi) else None
        if isinstance(m, HumanMessage) and not e_revisione(m):
            chat.append({"ruolo": "utente", "testo": m.content})
        elif (
            isinstance(m, AIMessage)
            and not m.tool_calls
            and isinstance(m.content, str)
            and m.content.strip()
            and not (seguente is not None and e_revisione(seguente))
        ):
            chat.append({"ruolo": "assistente", "testo": m.content})
    return chat


# ---------------------------------------------------------------------- agente

class Agente:
    """Il grafo più ciò che serve per usarlo da un servizio: prompt MCP e controllo dello stato.

    `prompt_mcp` è il ClienteMCP (o un finto nei test); `controlla_modello` solleva un'eccezione
    se LM Studio o il modello non sono disponibili.
    """

    def __init__(self, grafo, prompt_mcp=None, controlla_modello: Callable[[], None] | None = None):
        self.grafo = grafo
        self.prompt_mcp = prompt_mcp
        self.controlla_modello = controlla_modello

    def prompts(self) -> list:
        return self.prompt_mcp.elenco_prompt() if self.prompt_mcp is not None else []

    def rispondi(
        self,
        cronologia: list[dict],
        riassunto: str = "",
        domanda: str | None = None,
        prompt: tuple[str, dict[str, str]] | None = None,
    ) -> EsitoTurno:
        """Esegue un turno. Gli errori (modello, MCP, troppi passaggi) risalgono al chiamante."""
        nuovi = [HumanMessage(domanda)] if prompt is None else self._messaggi_del_prompt(*prompt)
        stato_iniziale = {"messages": da_cronologia(cronologia) + nuovi, "riassunto": riassunto, "revisioni": 0}

        esito = EsitoTurno(risposta="", cronologia=[], riassunto=riassunto)
        chiamate = {}  # tool_call_id → richiesta del modello, per abbinarla al risultato
        finale = stato_iniziale
        # Si usa stream e non invoke: con la modalità «messages» il modello risponde a pezzi e il
        # timeout di 120 s vale tra un pezzo e l'altro, non sull'intera risposta (prova dello step 5).
        for modo, dati in self.grafo.stream(
            stato_iniziale, {"recursion_limit": LIMITE_PASSAGGI}, stream_mode=["messages", "updates", "values"]
        ):
            if modo == "values":
                finale = dati
            elif modo == "updates":
                self._registra(dati, chiamate, esito)

        esito.cronologia = a_cronologia(finale["messages"])
        esito.riassunto = finale.get("riassunto", riassunto) or ""
        ultimo = finale["messages"][-1]
        esito.risposta = ultimo.content if isinstance(ultimo, AIMessage) and isinstance(ultimo.content, str) else ""
        log.info(
            "turno: strumenti=%s rifiutata=%s revisioni=%d riassunti=%d",
            [s["nome"] for s in esito.strumenti_usati], esito.rifiutata, len(esito.revisioni), esito.messaggi_riassunti,
        )
        return esito

    def _messaggi_del_prompt(self, nome: str, argomenti: dict[str, str]) -> list[BaseMessage]:
        """Step 5: controllo degli argomenti nell'host, poi prompts/get al server."""
        if self.prompt_mcp is None:
            raise ErroreComando("Prompt MCP non disponibili in questo servizio.")
        catalogo = {p.name: p for p in self.prompt_mcp.elenco_prompt()}
        if nome not in catalogo:
            raise ErroreComando(f"Prompt sconosciuto: «{nome}». Elenco con GET /prompts.")
        valida_argomenti(catalogo[nome], argomenti)
        return self.prompt_mcp.ottieni_prompt(nome, argomenti)

    @staticmethod
    def _registra(aggiornamento: dict, chiamate: dict, esito: EsitoTurno) -> None:
        """Legge l'aggiornamento di un nodo e annota ciò che il chiamante deve sapere."""
        for nodo, valori in aggiornamento.items():
            messaggi = (valori or {}).get("messages", [])  # un nodo che non cambia nulla manda None
            if nodo == "modello":
                for chiamata in getattr(messaggi[-1], "tool_calls", []) if messaggi else []:
                    chiamate[chiamata["id"]] = chiamata
            elif nodo == "strumenti":
                for risultato in messaggi:
                    if isinstance(risultato, ToolMessage):
                        richiesta = chiamate.get(risultato.tool_call_id, {"name": risultato.name, "args": {}})
                        esito.strumenti_usati.append(
                            {"nome": richiesta["name"], "argomenti": richiesta["args"], "risultato": risultato.content}
                        )
            elif nodo == "revisore":
                esito.revisioni += [m.additional_kwargs.get("motivo", "") for m in messaggi]
            elif nodo == "riassunto":
                esito.messaggi_riassunti += len(messaggi)  # sono i RemoveMessage dei messaggi tolti
            elif nodo == "rifiuto":
                esito.rifiutata = True

    def stato(self) -> dict[str, str]:
        """Step 6, GET /stato: agente, server MCP e modello raggiungibili?"""
        stato = {"agente": "ok"}
        if self.prompt_mcp is None:
            stato["server_mcp"] = "non configurato"
        else:
            stato["server_mcp"] = "ok" if self.prompt_mcp.attivo() else "sessione con il server MCP non attiva"
        if self.controlla_modello is None:
            stato["modello"] = "non controllato"
        else:
            try:
                self.controlla_modello()
                stato["modello"] = "ok"
            except Exception as exc:
                stato["modello"] = str(exc)
        return stato


def crea_agente(cfg: Configurazione) -> tuple[Agente, ClienteMCP]:
    """Costruisce l'agente come faceva l'avvio della CLI nelle lezioni 4 e 5.

    Avvia il server MCP (sottoprocesso stdio), legge la resource delle preferenze, sceglie la
    variante dell'orologio e costruisce il grafo SENZA checkpointer: la memoria è del chiamante.
    Restituisce anche il ClienteMCP, che il servizio deve chiudere allo spegnimento.
    """
    cliente = ClienteMCP(trasporto_stdio())
    cliente.avvia()  # ErroreCollegamentoMCP se il server non parte
    try:
        preferenze = carica_preferenze(lambda: cliente.leggi_risorsa(URI_PREFERENZE), cfg.fuso_predefinito)
        log.info("preferenze: lingua=%s fuso=%s stile=%s", preferenze.lingua, preferenze.fuso_predefinito, preferenze.stile)
        strumenti = strumenti_per_variante(cfg.variante, crea_strumenti_mcp(cliente), cfg.orologio_api_url)
        log.info("variante orologio=%s, strumenti=%s", cfg.variante, [s.name for s in strumenti])
        grafo = costruisci_grafo(
            crea_modello(cfg),
            cfg.fuso_predefinito,
            strumenti=strumenti,
            opzioni=OpzioniGrafo(
                ambito=cfg.ambito,
                limite_revisioni=cfg.limite_revisioni,
                soglia_riassunto=cfg.soglia_riassunto,
                messaggi_da_conservare=cfg.messaggi_da_conservare,
            ),
            preferenze=preferenze,
        )
    except Exception:
        cliente.chiudi()
        raise
    return Agente(grafo, prompt_mcp=cliente, controlla_modello=lambda: verifica_modello(cfg)), cliente
