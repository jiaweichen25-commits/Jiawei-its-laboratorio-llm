// Chiamate al back-end. È l'unico file che parla con la rete: la pagina (app.js) usa solo queste funzioni.
//
// È scritto a partire dal documento OpenAPI del back-end (/openapi.json), che fa da contratto (slide 15):
// un test (tests/test_frontend.py) controlla che ogni percorso qui sotto esista davvero nel back-end.

// I percorsi del back-end, tutti e soli quelli usati. {chat_id} viene sostituito da percorso().
export const PERCORSI = {
  stato: "/stato",
  chat: "/chat",
  unaChat: "/chat/{chat_id}",
  messaggi: "/chat/{chat_id}/messaggi",
  messaggiStream: "/chat/{chat_id}/messaggi/stream",
};

/** Errore con un messaggio pronto da mostrare all'utente. `codice` è lo stato HTTP (0 = nessuna risposta). */
export class ErroreApi extends Error {
  constructor(messaggio, codice = 0) {
    super(messaggio);
    this.name = "ErroreApi";
    this.codice = codice;
  }
}

function percorso(modello, chatId) {
  // encodeURIComponent: l'identificativo finisce nell'indirizzo, quindi va «messo in sicurezza».
  return modello.replace("{chat_id}", encodeURIComponent(chatId));
}

/** Il messaggio di errore del back-end: FastAPI lo mette in `detail` (testo, oppure elenco per i 422). */
async function messaggioDiErrore(risposta) {
  try {
    const { detail } = await risposta.json();
    if (Array.isArray(detail)) return detail.map((voce) => voce.msg).join("; ");
    if (typeof detail === "string" && detail) return detail;
  } catch {
    // corpo non JSON: si usa il messaggio generico qui sotto
  }
  return `Il back-end ha risposto con un errore (${risposta.status}).`;
}

/**
 * Legge un flusso Server-Sent Events e restituisce gli eventi uno alla volta: { tipo, dati }.
 *
 * Formato sulla rete:   event: testo
 *                       data: {"testo": "Sono "}
 *                       (riga vuota = fine dell'evento)
 *
 * La rete consegna i byte a pezzi di lunghezza qualsiasi: un evento, o perfino una lettera accentata,
 * può arrivare spezzato tra due pezzi. Per questo si accumula il testo e si emettono solo gli eventi completi.
 */
export async function* leggiSse(corpo) {
  const lettore = corpo.getReader();
  const decodifica = new TextDecoder(); // con { stream: true } ricompone i caratteri spezzati tra due pezzi
  let accumulo = "";
  try {
    while (true) {
      const { done, value } = await lettore.read();
      if (done) break;
      accumulo += decodifica.decode(value, { stream: true }).replaceAll("\r\n", "\n");
      let fine;
      while ((fine = accumulo.indexOf("\n\n")) !== -1) {
        const blocco = accumulo.slice(0, fine);
        accumulo = accumulo.slice(fine + 2);
        let tipo = null;
        let dati = null;
        for (const riga of blocco.split("\n")) {
          if (riga.startsWith("event:")) tipo = riga.slice(6).trim();
          else if (riga.startsWith("data:")) dati = riga.slice(5).trim();
        }
        if (tipo !== null && dati !== null) yield { tipo, dati: JSON.parse(dati) };
      }
    }
  } finally {
    lettore.releaseLock();
  }
}

/**
 * Crea l'oggetto con le operazioni del back-end.
 * `baseUrl` arriva da config.js; `fetchImpl` si sostituisce nei test con un fetch finto.
 */
export function creaApi(baseUrl, fetchImpl = (...argomenti) => globalThis.fetch(...argomenti)) {
  const base = baseUrl.replace(/\/+$/, "");

  /** Una richiesta; restituisce la Response se il codice è 2xx, altrimenti lancia ErroreApi. */
  async function richiesta(metodo, indirizzo, corpo) {
    const opzioni = { method: metodo };
    if (corpo !== undefined) {
      opzioni.headers = { "Content-Type": "application/json" };
      opzioni.body = JSON.stringify(corpo);
    }
    let risposta;
    try {
      risposta = await fetchImpl(base + indirizzo, opzioni);
    } catch {
      // fetch fallisce solo se non arriva nessuna risposta: back-end spento, rete assente, CORS non configurato.
      throw new ErroreApi(`Back-end non raggiungibile su ${base}. Controlla che sia avviato.`, 0);
    }
    if (!risposta.ok) throw new ErroreApi(await messaggioDiErrore(risposta), risposta.status);
    return risposta;
  }

  async function json(metodo, indirizzo, corpo) {
    const risposta = await richiesta(metodo, indirizzo, corpo);
    return risposta.status === 204 ? null : risposta.json();
  }

  return {
    /** GET /stato → { pronto, problemi }. Non lancia: serve proprio a dire che cosa non va. */
    async stato() {
      let risposta;
      try {
        risposta = await fetchImpl(base + PERCORSI.stato, { method: "GET" });
      } catch {
        return { pronto: false, problemi: [`Back-end non raggiungibile su ${base}`] };
      }
      try {
        const valori = await risposta.json();
        const problemi = Object.entries(valori).filter(([, valore]) => valore !== "ok").map(([nome, valore]) => `${nome}: ${valore}`);
        return { pronto: problemi.length === 0, problemi };
      } catch {
        return { pronto: false, problemi: [`risposta inattesa dal back-end (${risposta.status})`] };
      }
    },

    elencoChat: () => json("GET", PERCORSI.chat),
    creaChat: () => json("POST", PERCORSI.chat),
    leggiChat: (chatId) => json("GET", percorso(PERCORSI.unaChat, chatId)),
    eliminaChat: (chatId) => json("DELETE", percorso(PERCORSI.unaChat, chatId)),

    /** Invio senza streaming: la risposta arriva tutta insieme. */
    inviaMessaggio: (chatId, testo) => json("POST", percorso(PERCORSI.messaggi, chatId), { testo }),

    /**
     * Invio in streaming (slide 18). `suEvento(tipo, dati)` viene chiamata per testo, strumento,
     * revisione e riassunto mentre arrivano. Restituisce { domanda, risposta, chat } dell'evento «fine».
     * L'evento «errore» e un flusso che si chiude prima della fine diventano un ErroreApi.
     */
    async inviaMessaggioStream(chatId, testo, suEvento) {
      const risposta = await richiesta("POST", percorso(PERCORSI.messaggiStream, chatId), { testo });
      for await (const { tipo, dati } of leggiSse(risposta.body)) {
        if (tipo === "fine") return dati;
        if (tipo === "errore") throw new ErroreApi(dati.detail ?? "Errore durante la risposta.", dati.codice ?? 500);
        suEvento(tipo, dati);
      }
      throw new ErroreApi("La risposta si è interrotta prima della fine: il messaggio non è stato salvato.", 0);
    },
  };
}
