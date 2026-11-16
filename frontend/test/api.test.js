// Test di api.js con il test runner integrato di Node, dalla cartella frontend/:  node --test
// Il back-end è finto: una funzione al posto di fetch che registra le richieste e risponde.

import assert from "node:assert/strict";
import { test } from "node:test";

import { ErroreApi, PERCORSI, creaApi, leggiSse } from "../api.js";

const BASE = "http://backend.test";

/** Un flusso di byte fatto con i pezzi indicati, come quello che il browser riceve dalla rete. */
function flusso(...pezzi) {
  const codifica = new TextEncoder();
  return new ReadableStream({
    start(controllo) {
      for (const pezzo of pezzi) controllo.enqueue(typeof pezzo === "string" ? codifica.encode(pezzo) : pezzo);
      controllo.close();
    },
  });
}

function sse(tipo, dati) {
  return `event: ${tipo}\ndata: ${JSON.stringify(dati)}\n\n`;
}

/** fetch finto: `risposte` è una lista di Response (o di errori da lanciare), consumata in ordine. */
function fetchFinto(...risposte) {
  const richieste = [];
  const finto = async (url, opzioni = {}) => {
    richieste.push({ url, metodo: opzioni.method ?? "GET", corpo: opzioni.body ? JSON.parse(opzioni.body) : undefined });
    const prossima = risposte.shift();
    if (prossima instanceof Error) throw prossima;
    return prossima;
  };
  return { finto, richieste };
}

function json(corpo, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { "content-type": "application/json" } });
}

async function raccogli(generatore) {
  const eventi = [];
  for await (const evento of generatore) eventi.push(evento);
  return eventi;
}

// ---------------------------------------------------------------- leggiSse

test("leggiSse: eventi completi", async () => {
  const eventi = await raccogli(leggiSse(flusso(sse("testo", { testo: "Sono " }) + sse("fine", { ok: true }))));

  assert.deepEqual(eventi, [
    { tipo: "testo", dati: { testo: "Sono " } },
    { tipo: "fine", dati: { ok: true } },
  ]);
});

test("leggiSse: un evento spezzato tra due pacchetti di rete", async () => {
  const intero = sse("testo", { testo: "le dieci" }) + sse("fine", {});
  const meta = Math.floor(intero.length / 3);

  const eventi = await raccogli(leggiSse(flusso(intero.slice(0, meta), intero.slice(meta, meta * 2), intero.slice(meta * 2))));

  assert.deepEqual(eventi.map((e) => e.tipo), ["testo", "fine"]);
  assert.equal(eventi[0].dati.testo, "le dieci");
});

test("leggiSse: una lettera accentata spezzata a metà dei suoi byte", async () => {
  const byte = new TextEncoder().encode(sse("testo", { testo: "perché" }));
  const taglio = byte.indexOf(0xc3) + 1; // «é» in UTF-8 occupa due byte: si taglia tra i due

  const eventi = await raccogli(leggiSse(flusso(byte.slice(0, taglio), byte.slice(taglio))));

  assert.equal(eventi[0].dati.testo, "perché");
});

test("leggiSse: accetta anche i fine riga \\r\\n", async () => {
  const eventi = await raccogli(leggiSse(flusso('event: testo\r\ndata: {"testo":"a"}\r\n\r\n')));

  assert.deepEqual(eventi, [{ tipo: "testo", dati: { testo: "a" } }]);
});

// ---------------------------------------------------------------- operazioni semplici

test("elencoChat, creaChat, leggiChat, eliminaChat: indirizzi e metodi", async () => {
  const { finto, richieste } = fetchFinto(json([]), json({ id: "a b" }, 201), json({ id: "a b", messaggi: [] }),
    new Response(null, { status: 204 }));
  const api = creaApi(BASE + "/", finto);

  assert.deepEqual(await api.elencoChat(), []);
  assert.equal((await api.creaChat()).id, "a b");
  await api.leggiChat("a b");
  assert.equal(await api.eliminaChat("a b"), null);

  assert.deepEqual(richieste.map((r) => `${r.metodo} ${r.url}`), [
    `GET ${BASE}/chat`, `POST ${BASE}/chat`, `GET ${BASE}/chat/a%20b`, `DELETE ${BASE}/chat/a%20b`,
  ]);
});

test("errore del back-end: il messaggio è il suo detail", async () => {
  const { finto } = fetchFinto(json({ detail: "Chat non trovata." }, 404));

  await assert.rejects(creaApi(BASE, finto).leggiChat("x"), (errore) => {
    assert.ok(errore instanceof ErroreApi);
    assert.equal(errore.message, "Chat non trovata.");
    assert.equal(errore.codice, 404);
    return true;
  });
});

test("errore di validazione 422: i messaggi dell'elenco vengono uniti", async () => {
  const { finto } = fetchFinto(json({ detail: [{ msg: "il testo non può essere vuoto" }] }, 422));

  await assert.rejects(creaApi(BASE, finto).inviaMessaggio("x", " "), /il testo non può essere vuoto/);
});

test("back-end spento: messaggio comprensibile con l'indirizzo", async () => {
  const { finto } = fetchFinto(new TypeError("Failed to fetch"));

  await assert.rejects(creaApi(BASE, finto).elencoChat(), (errore) => {
    assert.match(errore.message, /Back-end non raggiungibile/);
    assert.match(errore.message, /backend\.test/);
    assert.equal(errore.codice, 0);
    return true;
  });
});

test("stato: un 503 non è un'eccezione, dice che cosa manca", async () => {
  const { finto } = fetchFinto(json({ backend: "ok", database: "ok", agente: "modello: LM Studio non raggiungibile" }, 503),
    json({ backend: "ok", database: "ok", agente: "ok" }), new TypeError("Failed to fetch"));
  const api = creaApi(BASE, finto);

  assert.deepEqual(await api.stato(), { pronto: false, problemi: ["agente: modello: LM Studio non raggiungibile"] });
  assert.deepEqual(await api.stato(), { pronto: true, problemi: [] });
  const spento = await api.stato();
  assert.equal(spento.pronto, false);
  assert.match(spento.problemi[0], /Back-end non raggiungibile/);
});

// ---------------------------------------------------------------- invio in streaming

test("inviaMessaggioStream: richiesta, eventi in ordine e risultato finale", async () => {
  const scambio = { domanda: { testo: "d" }, risposta: { testo: "Sono le 10" }, chat: { id: "c1" } };
  const corpo = flusso(sse("strumento", { nome: "orologio" }), sse("testo", { testo: "Sono " }), sse("testo", { testo: "le 10" }),
    sse("fine", scambio));
  const { finto, richieste } = fetchFinto(new Response(corpo, { status: 200, headers: { "content-type": "text/event-stream" } }));
  const visti = [];

  const risultato = await creaApi(BASE, finto).inviaMessaggioStream("c1", "d", (tipo, dati) => visti.push([tipo, dati]));

  assert.deepEqual(richieste, [{ url: `${BASE}/chat/c1/messaggi/stream`, metodo: "POST", corpo: { testo: "d" } }]);
  assert.deepEqual(visti, [["strumento", { nome: "orologio" }], ["testo", { testo: "Sono " }], ["testo", { testo: "le 10" }]]);
  assert.deepEqual(risultato, scambio);
});

test("inviaMessaggioStream: l'evento errore diventa un'eccezione con il suo detail", async () => {
  const corpo = flusso(sse("testo", { testo: "Sto" }), sse("errore", { codice: 502, detail: "L'agente ha risposto con un errore." }));
  const { finto } = fetchFinto(new Response(corpo, { status: 200 }));

  await assert.rejects(creaApi(BASE, finto).inviaMessaggioStream("c1", "d", () => {}), (errore) => {
    assert.equal(errore.message, "L'agente ha risposto con un errore.");
    assert.equal(errore.codice, 502);
    return true;
  });
});

test("inviaMessaggioStream: errore prima del flusso (503) come nelle altre chiamate", async () => {
  const { finto } = fetchFinto(json({ detail: "Agente non raggiungibile: il messaggio non è stato salvato, riprova." }, 503));

  await assert.rejects(creaApi(BASE, finto).inviaMessaggioStream("c1", "d", () => {}), /Agente non raggiungibile/);
});

test("inviaMessaggioStream: flusso chiuso senza l'evento fine", async () => {
  const { finto } = fetchFinto(new Response(flusso(sse("testo", { testo: "Sto" })), { status: 200 }));

  await assert.rejects(creaApi(BASE, finto).inviaMessaggioStream("c1", "d", () => {}), /interrott/);
});

test("PERCORSI: il contratto con il back-end è in un solo oggetto", () => {
  assert.deepEqual(Object.values(PERCORSI).sort(), [
    "/chat", "/chat/{chat_id}", "/chat/{chat_id}/messaggi", "/chat/{chat_id}/messaggi/stream", "/stato",
  ]);
});
