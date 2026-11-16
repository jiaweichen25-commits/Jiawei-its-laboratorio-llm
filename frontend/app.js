// Logica della pagina (lezione 6, step 8). Parla con il back-end solo attraverso api.js.
//
// Schema: un oggetto `stato` contiene tutto ciò che la pagina mostra; ogni azione lo modifica e poi
// richiama le funzioni `disegna...`, che ricostruiscono la parte di pagina corrispondente.
// Il testo (titoli, risposte del modello) entra sempre con textContent, mai come HTML.

import { creaApi } from "./api.js";

const api = creaApi(window.CONFIGURAZIONE.backendUrl);

const TITOLO_INIZIALE = "Nuova chat";
const ESEMPI = ["Che ore sono a Tokyo?", "Quanto fa (17 + 25) * 3?", "Converti 10 km in miglia."];

const el = {
  elenco: document.querySelector("#elenco-chat"),
  elencoVuoto: document.querySelector("#elenco-vuoto"),
  nuovaChat: document.querySelector("#nuova-chat"),
  statoServizi: document.querySelector("#stato-servizi"),
  titolo: document.querySelector("#titolo-chat"),
  messaggi: document.querySelector("#messaggi"),
  errore: document.querySelector("#errore"),
  erroreTesto: document.querySelector("#errore-testo"),
  erroreChiudi: document.querySelector("#errore-chiudi"),
  modulo: document.querySelector("#modulo"),
  testo: document.querySelector("#testo"),
  invia: document.querySelector("#invia"),
};

const stato = {
  chat: [],            // elenco delle chat, come arriva da GET /chat
  elencoLetto: false,  // l'elenco è stato letto almeno una volta (se no, non si può dire «nessuna chat»)
  attiva: null,        // id della chat mostrata; null = nessuna (verrà creata al primo invio)
  messaggi: [],        // messaggi salvati della chat attiva
  caricamento: false,  // si sta leggendo la chat attiva dal back-end
  invio: null,         // turno in corso: { chatId, domanda, bozza, strumenti, note, inizio }
  conferma: null,      // id della chat per cui si sta chiedendo «Elimina?»
};

let aperture = 0;      // numero progressivo delle aperture: serve a scartare le risposte arrivate in ritardo
let bozza = null;      // elementi della risposta in arrivo, da aggiornare senza ridisegnare tutto

// ---------------------------------------------------------------- piccoli aiuti

/** Crea un elemento con classe e testo (sempre testo semplice). */
function crea(tag, classe, testo) {
  const elemento = document.createElement(tag);
  if (classe) elemento.className = classe;
  if (testo !== undefined) elemento.textContent = testo;
  return elemento;
}

function formattaData(iso) {
  return new Date(iso).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function formattaStrumento({ nome, argomenti, risultato }) {
  const lista = Object.entries(argomenti ?? {})
    .map(([chiave, valore]) => (typeof valore === "string" ? `${chiave}="${valore}"` : `${chiave}=${JSON.stringify(valore)}`))
    .join(", ");
  return `strumento: ${nome}(${lista}) → ${risultato}`;
}

function mostraErrore(messaggio) {
  el.erroreTesto.textContent = messaggio;
  el.errore.hidden = false;
}

function nascondiErrore() {
  el.errore.hidden = true;
}

function scorriInFondo() {
  el.messaggi.scrollTop = el.messaggi.scrollHeight;
}

// ---------------------------------------------------------------- disegno

function disegnaElenco() {
  el.elenco.replaceChildren();
  el.elencoVuoto.hidden = stato.chat.length > 0 || !stato.elencoLetto;
  for (const chat of stato.chat) {
    const voce = crea("li", "voce-chat" + (chat.id === stato.attiva ? " attiva" : ""));

    const apri = crea("button", "apri");
    apri.type = "button";
    apri.append(crea("span", "titolo", chat.titolo), crea("span", "data", formattaData(chat.aggiornata_il)));
    if (chat.id === stato.attiva) apri.setAttribute("aria-current", "true");
    apri.addEventListener("click", () => apriChat(chat.id));

    // Eliminazione in due passi dentro la pagina (niente finestre di conferma del browser).
    const azioni = crea("div", "azioni");
    if (stato.conferma === chat.id) {
      const si = crea("button", "pulsante piccolo pericolo", "Elimina");
      si.type = "button";
      si.addEventListener("click", () => eliminaChat(chat.id));
      const no = crea("button", "pulsante piccolo", "Annulla");
      no.type = "button";
      no.addEventListener("click", () => { stato.conferma = null; disegnaElenco(); });
      azioni.append(si, no);
    } else {
      const elimina = crea("button", "pulsante piccolo", "×");
      elimina.type = "button";
      elimina.title = "Elimina la chat";
      elimina.setAttribute("aria-label", `Elimina la chat «${chat.titolo}»`);
      elimina.disabled = stato.invio?.chatId === chat.id; // non si elimina una chat che sta aspettando la risposta
      elimina.addEventListener("click", () => { stato.conferma = chat.id; disegnaElenco(); });
      azioni.append(elimina);
    }

    voce.append(apri, azioni);
    el.elenco.append(voce);
  }
}

function creaMessaggio(messaggio) {
  const riquadro = crea("article", `messaggio ${messaggio.ruolo}`);
  riquadro.append(crea("p", "testo", messaggio.testo));
  for (const strumento of messaggio.strumenti ?? []) riquadro.append(crea("p", "strumento", formattaStrumento(strumento)));
  return riquadro;
}

function disegnaVuoto() {
  const vuoto = crea("div", "vuoto");
  vuoto.append(crea("p", "", "Scrivi una domanda qui sotto per cominciare. Per esempio:"));
  const esempi = crea("div", "esempi");
  for (const esempio of ESEMPI) {
    const pulsante = crea("button", "pulsante", esempio);
    pulsante.type = "button";
    pulsante.disabled = stato.invio !== null;
    pulsante.addEventListener("click", () => { el.testo.value = esempio; el.testo.focus(); });
    esempi.append(pulsante);
  }
  vuoto.append(esempi);
  return vuoto;
}

function disegnaMessaggi() {
  const attiva = stato.chat.find((chat) => chat.id === stato.attiva);
  el.titolo.textContent = attiva?.titolo ?? TITOLO_INIZIALE;
  el.messaggi.replaceChildren();
  bozza = null;

  const inCorso = stato.invio !== null && stato.invio.chatId === stato.attiva;
  if (stato.caricamento) {
    el.messaggi.append(crea("p", "vuoto", "Carico la chat…"));
  } else if (stato.messaggi.length === 0 && !inCorso) {
    el.messaggi.append(disegnaVuoto());
  }
  for (const messaggio of stato.messaggi) el.messaggi.append(creaMessaggio(messaggio));

  if (inCorso) {
    // La domanda appena inviata e la risposta in arrivo: non sono ancora salvate nel back-end.
    el.messaggi.append(creaMessaggio({ ruolo: "utente", testo: stato.invio.domanda }));
    const riquadro = crea("article", "messaggio assistente");
    bozza = { strumenti: crea("div"), note: crea("div"), testo: crea("p", "testo"), attesa: crea("p", "attesa") };
    riquadro.append(bozza.strumenti, bozza.note, bozza.testo, bozza.attesa);
    el.messaggi.append(riquadro);
    aggiornaBozza();
  }
  scorriInFondo();
}

/** Aggiorna solo la risposta in arrivo: chiamata a ogni evento dello streaming e a ogni secondo. */
function aggiornaBozza() {
  if (bozza === null || stato.invio === null) return;
  const { strumenti, note, bozza: testo, inizio } = stato.invio;
  bozza.strumenti.replaceChildren(...strumenti.map((strumento) => crea("p", "strumento", formattaStrumento(strumento))));
  bozza.note.replaceChildren(...note.map((nota) => crea("p", "annotazione", nota)));
  bozza.testo.textContent = testo;
  bozza.testo.hidden = testo === "";
  const secondi = Math.floor((Date.now() - inizio) / 1000);
  bozza.attesa.textContent = `${testo === "" ? "L'agente sta rispondendo" : "L'agente sta scrivendo"} · ${secondi} s`;
}

function aggiornaModulo() {
  const occupato = stato.invio !== null;
  el.testo.disabled = occupato;
  el.invia.disabled = occupato;
  el.invia.textContent = occupato ? "In attesa…" : "Invia";
}

function disegnaTutto() {
  disegnaElenco();
  disegnaMessaggi();
  aggiornaModulo();
}

// ---------------------------------------------------------------- azioni

async function aggiornaStatoServizi() {
  const { pronto, problemi } = await api.stato();
  el.statoServizi.textContent = pronto ? "Servizi attivi" : problemi.join(" · ");
  el.statoServizi.className = "stato-servizi " + (pronto ? "ok" : "ko");
  // Se all'apertura il back-end era spento, appena torna si carica l'elenco senza ricaricare la pagina.
  if (pronto && !stato.elencoLetto && stato.invio === null) caricaElenco();
}

async function caricaElenco() {
  try {
    stato.chat = await api.elencoChat();
  } catch (errore) {
    mostraErrore(errore.message);
    return;
  }
  stato.elencoLetto = true;
  nascondiErrore();
  if (stato.chat.length > 0 && stato.attiva === null) await apriChat(stato.chat[0].id);
  else disegnaTutto();
}

async function apriChat(chatId) {
  const apertura = ++aperture;
  nascondiErrore();
  stato.conferma = null;
  stato.attiva = chatId;
  stato.messaggi = [];
  stato.caricamento = true;
  disegnaTutto();
  try {
    const chat = await api.leggiChat(chatId);
    if (apertura !== aperture) return; // nel frattempo è stata aperta un'altra chat
    stato.messaggi = chat.messaggi;
  } catch (errore) {
    if (apertura !== aperture) return;
    mostraErrore(errore.message);
    if (errore.codice === 404) {
      stato.chat = stato.chat.filter((chat) => chat.id !== chatId);
      stato.attiva = null;
    }
  }
  stato.caricamento = false;
  disegnaTutto();
}

async function nuovaChat() {
  nascondiErrore();
  // Se la chat aperta è già vuota non ne serve un'altra.
  const attiva = stato.chat.find((chat) => chat.id === stato.attiva);
  if (!attiva || attiva.numero_messaggi > 0) {
    try {
      const chat = await api.creaChat();
      aperture++;
      stato.chat.unshift(chat);
      stato.attiva = chat.id;
      stato.messaggi = [];
      stato.caricamento = false;
    } catch (errore) {
      mostraErrore(errore.message);
    }
  }
  disegnaTutto();
  el.testo.focus();
}

async function eliminaChat(chatId) {
  nascondiErrore();
  stato.conferma = null;
  try {
    await api.eliminaChat(chatId);
  } catch (errore) {
    if (errore.codice !== 404) { // 404: era già stata eliminata, il risultato è lo stesso
      mostraErrore(errore.message);
      disegnaElenco();
      return;
    }
  }
  stato.chat = stato.chat.filter((chat) => chat.id !== chatId);
  if (stato.attiva !== chatId) {
    disegnaElenco();
  } else if (stato.chat.length > 0) {
    await apriChat(stato.chat[0].id);
  } else {
    aperture++;
    stato.attiva = null;
    stato.messaggi = [];
    disegnaTutto();
  }
}

/** Eventi dello streaming (slide 18): arrivano mentre l'agente lavora. */
function suEvento(tipo, dati) {
  const invio = stato.invio;
  if (invio === null) return;
  if (tipo === "testo") {
    invio.bozza += dati.testo;
  } else if (tipo === "strumento") {
    // Lo strumento chiude la bozza corrente: il testo scritto prima non fa parte della risposta finale.
    invio.strumenti.push(dati);
    invio.bozza = "";
  } else if (tipo === "revisione") {
    // Scelta documentata nel README: la bozza si mostra subito e, se il revisore la boccia, viene tolta.
    invio.note.push(`Il revisore ha chiesto una correzione: ${dati.motivo}`);
    invio.bozza = "";
  } else if (tipo === "riassunto") {
    invio.note.push(`Per fare spazio, ${dati.messaggi_riassunti} messaggi vecchi sono stati riassunti.`);
  }
  aggiornaBozza();
  scorriInFondo();
}

async function invia(testo) {
  nascondiErrore();
  let chatId = stato.attiva;
  if (chatId === null) {
    // Prima domanda senza una chat aperta: la si crea adesso.
    try {
      const chat = await api.creaChat();
      stato.chat.unshift(chat);
      stato.attiva = chatId = chat.id;
      stato.messaggi = [];
    } catch (errore) {
      mostraErrore(errore.message);
      return;
    }
  }

  stato.invio = { chatId, domanda: testo, bozza: "", strumenti: [], note: [], inizio: Date.now() };
  el.testo.value = "";
  disegnaTutto();

  try {
    const scambio = await api.inviaMessaggioStream(chatId, testo, suEvento);
    stato.invio = null;
    stato.chat = [scambio.chat, ...stato.chat.filter((chat) => chat.id !== chatId)]; // la chat aggiornata sale in cima
    const giaPresente = stato.messaggi.some((messaggio) => messaggio.id === scambio.risposta.id);
    if (stato.attiva === chatId && !stato.caricamento && !giaPresente) stato.messaggi.push(scambio.domanda, scambio.risposta);
  } catch (errore) {
    // Nulla è stato salvato: si toglie la bozza, si mostra il motivo e la domanda torna nella casella.
    stato.invio = null;
    mostraErrore(errore.message);
    if (stato.attiva === chatId && el.testo.value === "") el.testo.value = testo;
    aggiornaStatoServizi();
  }
  disegnaTutto();
  el.testo.focus();
}

// ---------------------------------------------------------------- collegamento alla pagina

el.modulo.addEventListener("submit", (evento) => {
  evento.preventDefault();
  const testo = el.testo.value.trim();
  if (testo !== "" && stato.invio === null) invia(testo);
});

el.testo.addEventListener("keydown", (evento) => {
  // Invio manda la domanda, Maiusc+Invio va a capo. isComposing: non interferire con la scrittura in cinese o giapponese.
  if (evento.key === "Enter" && !evento.shiftKey && !evento.isComposing) {
    evento.preventDefault();
    el.modulo.requestSubmit();
  }
});

el.nuovaChat.addEventListener("click", nuovaChat);
el.erroreChiudi.addEventListener("click", nascondiErrore);

setInterval(aggiornaBozza, 1000);            // fa avanzare i secondi di attesa
setInterval(aggiornaStatoServizi, 30000);    // ricontrolla i servizi ogni mezzo minuto

disegnaTutto();
aggiornaStatoServizi();
caricaElenco();
