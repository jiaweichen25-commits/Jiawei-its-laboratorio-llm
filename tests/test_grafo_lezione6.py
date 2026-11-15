"""Lezione 6: i nodi nuovi del grafo (router, rifiuto, revisore, riassunto) con il modello finto.

Il modello finto è uno solo e consuma le risposte in ordine: prima quella del router,
poi quella dell'agente, e così via, nello stesso ordine in cui i nodi vengono eseguiti.
"""

import json
import logging
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from langgraph.checkpoint.memory import InMemorySaver

from assistente.grafo import LIMITE_PASSAGGI, OpzioniGrafo, costruisci_grafo, risposta_rifiuto
from assistente.strumenti import crea_orologio
from tests.modello_finto import ModelloFinto

ISTANTE = datetime(2026, 10, 26, 15, 42, 10, tzinfo=timezone.utc)
ORA_TOKYO = "2026-10-27T00:42:10+09:00 (Asia/Tokyo), martedì"


def router(categoria, motivo="m"):
    """Risposta JSON che il nodo router si aspetta dal modello."""
    return AIMessage(json.dumps({"categoria": categoria, "motivo": motivo}))


def esegui(opzioni, *risposte, domanda="Che ore sono a Tokyo?"):
    modello = ModelloFinto(risposte=list(risposte))
    grafo = costruisci_grafo(modello, "Europe/Rome", strumenti=[crea_orologio(lambda: ISTANTE)], opzioni=opzioni)
    stato = grafo.invoke({"messages": [HumanMessage(domanda)]}, {"recursion_limit": LIMITE_PASSAGGI})
    return modello, stato


# ---------------------------------------------------------------- step 1: router

SOLO_ROUTER = OpzioniGrafo(ambito="data e ora")


def test_router_in_ambito_passa_all_agente(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    _, stato = esegui(SOLO_ROUTER, router("conversazione"), AIMessage("Ciao!"))

    assert stato["messages"][-1].content == "Ciao!"
    assert "router: categoria=conversazione motivo=m" in caplog.text
    assert "modello: inizio chiamata" in caplog.text


def test_router_fuori_ambito_rifiuta_senza_agente(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    modello, stato = esegui(SOLO_ROUTER, router("fuori_ambito"), domanda="Dammi una ricetta")

    assert stato["messages"][-1].content == risposta_rifiuto("data e ora")
    assert len(modello.ricevuti) == 1  # solo la chiamata del router: l'agente non è stato eseguito
    assert "modello: inizio chiamata" not in caplog.text
    assert "router: categoria=fuori_ambito" in caplog.text


def test_router_output_non_valido_lascia_passare(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    _, stato = esegui(SOLO_ROUTER, AIMessage("boh"), AIMessage("Ciao!"))

    assert stato["messages"][-1].content == "Ciao!"
    assert "WARNING" in caplog.text


def test_router_non_vede_gli_strumenti():
    modello, _ = esegui(SOLO_ROUTER, router("conversazione"), AIMessage("Ciao!"))

    assert "orologio" not in modello.ricevuti[0][0].content


def test_la_decisione_del_router_non_entra_nella_cronologia():
    _, stato = esegui(SOLO_ROUTER, router("conversazione"), AIMessage("Ciao!"))

    assert [type(m) for m in stato["messages"]] == [HumanMessage, AIMessage]


def test_senza_opzioni_il_grafo_e_quello_della_lezione_5():
    grafo = costruisci_grafo(ModelloFinto(risposte=[]), "Europe/Rome")

    assert set(grafo.get_graph().nodes) == {"__start__", "modello", "strumenti", "__end__"}


# ---------------------------------------------------------------- step 2: revisore

SOLO_REVISORE = OpzioniGrafo(limite_revisioni=2)


def revisore(coerente, motivo="m"):
    """Risposta JSON che il nodo revisore si aspetta dal modello."""
    return AIMessage(json.dumps({"coerente": coerente, "motivo": motivo}))


def chiamata(fuso, id="c1"):
    return AIMessage("", tool_calls=[{"name": "orologio", "args": {"fuso": fuso}, "id": id}])


def test_revisore_approva_al_primo_passaggio(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    modello, stato = esegui(SOLO_REVISORE, AIMessage("Sono le 10."), revisore(True))

    assert [type(m) for m in stato["messages"]] == [HumanMessage, AIMessage]
    assert stato["messages"][-1].content == "Sono le 10."
    assert "revisore: coerente" in caplog.text
    assert modello.risposte == []


def test_revisore_boccia_poi_approva(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    _, stato = esegui(
        SOLO_REVISORE,
        AIMessage("Sono le 10."), revisore(False, "manca il calcolo"),
        AIMessage("Sono le 10 e fa 96."), revisore(True),
    )

    messaggi = stato["messages"]
    assert messaggi[-1].content == "Sono le 10 e fa 96."
    assert messaggi[2].content.startswith("[Revisione]") and "manca il calcolo" in messaggi[2].content
    assert stato["revisioni"] == 1
    assert "revisore: non coerente (revisione 1 di 2) motivo=manca il calcolo" in caplog.text


def test_l_agente_riceve_l_indicazione_del_revisore():
    modello, _ = esegui(
        SOLO_REVISORE, AIMessage("Sono le 10."), revisore(False, "manca il calcolo"), AIMessage("ok"), revisore(True)
    )

    # ricevuti: [0] agente, [1] revisore, [2] agente dopo la bocciatura
    assert "manca il calcolo" in modello.ricevuti[2][-1].content


def test_revisore_che_rifiuta_sempre_si_ferma_al_limite(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    modello, stato = esegui(
        SOLO_REVISORE,
        AIMessage("bozza1"), revisore(False), AIMessage("bozza2"), revisore(False), AIMessage("bozza3"), revisore(False),
    )

    assert stato["messages"][-1].content == "bozza3"
    assert stato["revisioni"] == 2
    assert "limite di revisioni raggiunto" in caplog.text
    assert modello.risposte == []  # tre bozze e tre giudizi: nessuna chiamata oltre il limite


def test_dopo_la_bocciatura_l_agente_puo_usare_uno_strumento():
    _, stato = esegui(
        SOLO_REVISORE,
        AIMessage("Non so."), revisore(False, "non dice l'ora"),
        chiamata("Asia/Tokyo"), AIMessage("Sono le 00:42"), revisore(True),
    )

    assert any(isinstance(m, ToolMessage) and m.content == ORA_TOKYO for m in stato["messages"])
    assert stato["messages"][-1].content == "Sono le 00:42"
    assert stato["revisioni"] == 1


def test_il_revisore_riceve_domanda_risultati_e_risposta():
    modello, _ = esegui(SOLO_REVISORE, chiamata("Asia/Tokyo"), AIMessage("Sono le 00:42"), revisore(True))

    richiesta = modello.ricevuti[-1][1].content
    assert "Che ore sono a Tokyo?" in richiesta
    assert ORA_TOKYO in richiesta
    assert "Sono le 00:42" in richiesta


def test_revisore_output_non_valido_approva(caplog):
    caplog.set_level(logging.INFO, logger="assistente")

    _, stato = esegui(SOLO_REVISORE, AIMessage("Sono le 10."), AIMessage("boh"))

    assert stato["messages"][-1].content == "Sono le 10."
    assert "WARNING" in caplog.text


def test_router_e_revisore_insieme():
    opzioni = OpzioniGrafo(ambito="data e ora", limite_revisioni=2)

    modello, stato = esegui(opzioni, router("conversazione"), AIMessage("Sono le 10."), revisore(True))
    assert stato["messages"][-1].content == "Sono le 10." and modello.risposte == []

    modello, stato = esegui(opzioni, router("fuori_ambito"))
    assert stato["messages"][-1].content == risposta_rifiuto("data e ora")
    assert len(modello.ricevuti) == 1  # fuori ambito: né agente né revisore


# ---------------------------------------------------------------- step 3: riassunto

SOLO_RIASSUNTO = OpzioniGrafo(soglia_riassunto=4, messaggi_da_conservare=2)


def sessione(opzioni, *risposte):
    """Grafo con memoria, per più turni di seguito nella stessa sessione."""
    modello = ModelloFinto(risposte=list(risposte))
    grafo = costruisci_grafo(
        modello, "Europe/Rome", strumenti=[crea_orologio(lambda: ISTANTE)],
        checkpointer=InMemorySaver(), opzioni=opzioni,
    )
    config = {"configurable": {"thread_id": "t"}, "recursion_limit": LIMITE_PASSAGGI}

    def turno(domanda):
        return grafo.invoke({"messages": [HumanMessage(domanda)], "revisioni": 0}, config)

    return modello, turno


def test_sotto_soglia_non_chiama_il_modello_per_riassumere(caplog):
    caplog.set_level(logging.INFO, logger="assistente")
    modello, turno = sessione(OpzioniGrafo(soglia_riassunto=12), AIMessage("Piacere."), AIMessage("Jiawei."))

    turno("Mi chiamo Jiawei")
    stato = turno("Come mi chiamo?")

    assert len(modello.ricevuti) == 2  # una chiamata per turno: solo l'agente
    assert len(stato["messages"]) == 4 and not stato.get("riassunto")
    assert "riassunto:" not in caplog.text


def test_sopra_soglia_comprime(caplog):
    caplog.set_level(logging.INFO, logger="assistente")
    modello, turno = sessione(
        SOLO_RIASSUNTO,
        AIMessage("Piacere, Jiawei."), AIMessage("Sono le 10."),
        AIMessage("L'utente si chiama Jiawei."),  # risposta del modello al nodo riassunto, al terzo turno
        AIMessage("Ti chiami Jiawei."),
    )

    turno("Mi chiamo Jiawei")
    turno("Che ore sono?")
    stato = turno("Come mi chiamo?")  # 5 messaggi > soglia 4: il primo scambio viene riassunto

    assert "riassunto: messaggi prima=5 dopo=3" in caplog.text
    assert stato["riassunto"] == "L'utente si chiama Jiawei."
    assert [m.content for m in stato["messages"]] == [
        "Che ore sono?", "Sono le 10.", "Come mi chiamo?", "Ti chiami Jiawei.",
    ]
    sistema_agente = modello.ricevuti[-1][0]
    assert "Riassunto della conversazione finora: L'utente si chiama Jiawei." in sistema_agente.content
    assert [m.content for m in modello.ricevuti[-1][1:]] == ["Che ore sono?", "Sono le 10.", "Come mi chiamo?"]


def test_il_riassunto_viene_sostituito_non_accumulato():
    modello, turno = sessione(
        SOLO_RIASSUNTO,
        AIMessage("r1"), AIMessage("r2"),
        AIMessage("riassunto uno"), AIMessage("r3"),
        AIMessage("riassunto due"), AIMessage("r4"),
    )

    for domanda in ("d1", "d2", "d3"):
        turno(domanda)
    stato = turno("d4")

    assert stato["riassunto"] == "riassunto due"
    # Alla seconda compressione il modello riceve il riassunto precedente, da fondere con i messaggi nuovi.
    assert "riassunto uno" in modello.ricevuti[-2][1].content


def test_riassunto_vuoto_non_toglie_messaggi(caplog):
    caplog.set_level(logging.INFO, logger="assistente")
    _, turno = sessione(SOLO_RIASSUNTO, AIMessage("r1"), AIMessage("r2"), AIMessage("  "), AIMessage("r3"))

    turno("d1")
    turno("d2")
    stato = turno("d3")

    assert len(stato["messages"]) == 6 and not stato.get("riassunto")
    assert "WARNING" in caplog.text


def test_il_taglio_non_separa_richiesta_e_toolmessage():
    _, turno = sessione(
        SOLO_RIASSUNTO,
        AIMessage("r1"),
        chiamata("Asia/Tokyo"), AIMessage("Sono le 00:42"),
        AIMessage("riassunto"), AIMessage("r3"),
    )

    turno("d1")
    turno("Che ore sono a Tokyo?")
    messaggi = turno("d3")["messages"]  # 7 messaggi: il taglio «ultimi 2» cadrebbe in mezzo al turno con lo strumento

    richieste = {c["id"] for m in messaggi if isinstance(m, AIMessage) for c in m.tool_calls}
    risultati = {m.tool_call_id for m in messaggi if isinstance(m, ToolMessage)}
    assert richieste == risultati
    assert isinstance(messaggi[0], HumanMessage)


def test_turno_unico_senza_punto_di_taglio_non_riassume():
    # Primo turno con tre strumenti: 8 messaggi e una sola domanda. Al secondo turno la cronologia
    # supera la soglia, ma l'unico punto di taglio possibile lascerebbe fuori troppo poco: non si riassume.
    risposte = [chiamata("Asia/Tokyo", id=f"c{i}") for i in range(3)] + [AIMessage("Fatto."), AIMessage("r2")]
    modello, turno = sessione(SOLO_RIASSUNTO, *risposte)

    turno("Che ore sono a Tokyo? Controlla tre volte.")
    stato = turno("d2")

    assert len(stato["messages"]) == 10 and not stato.get("riassunto")
    assert modello.risposte == []


def test_tre_nodi_insieme_nell_ordine_riassunto_router_agente_revisore():
    opzioni = OpzioniGrafo(ambito="data e ora", limite_revisioni=2, soglia_riassunto=4, messaggi_da_conservare=2)
    modello, turno = sessione(
        opzioni,
        router("conversazione"), AIMessage("r1"), revisore(True),
        router("conversazione"), AIMessage("r2"), revisore(True),
        AIMessage("L'utente si chiama Jiawei."), router("conversazione"), AIMessage("Ti chiami Jiawei."), revisore(True),
    )

    turno("Mi chiamo Jiawei")
    turno("d2")
    stato = turno("Come mi chiamo?")

    assert stato["messages"][-1].content == "Ti chiami Jiawei." and modello.risposte == []
    assert stato["riassunto"] == "L'utente si chiama Jiawei."
    # Il router del terzo turno riceve il riassunto: senza, non saprebbe più di che cosa si parlava.
    assert "L'utente si chiama Jiawei." in modello.ricevuti[-3][1].content


def test_il_riassunto_sta_in_cima_al_messaggio_di_sistema():
    # Prova reale fallita: con il riassunto in coda alle istruzioni il modello locale lo ignorava.
    # Slide 7: il contesto preparato dall'host va «meglio in cima» al prompt di sistema.
    from assistente.grafo import messaggio_sistema

    testo = messaggio_sistema("Europe/Rome", "L'utente si chiama Jiawei.").content

    assert testo.index("L'utente si chiama Jiawei.") < testo.index("Rispondi in italiano.")
    assert "usa" in testo[: testo.index("Rispondi in italiano.")].lower()  # istruzione esplicita a usarlo


def test_senza_riassunto_il_messaggio_di_sistema_non_cambia():
    from assistente.grafo import messaggio_sistema

    assert messaggio_sistema("Europe/Rome").content.startswith("Rispondi in italiano.")


def test_l_agente_e_invitato_a_rispondere_dal_riassunto():
    from assistente.grafo import messaggio_sistema

    testo = messaggio_sistema("Europe/Rome", "L'utente si chiama Jiawei.").content

    assert "detto prima" in testo
