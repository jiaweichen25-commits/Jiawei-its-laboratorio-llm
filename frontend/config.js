// Configurazione del front-end. È l'UNICO file che contiene l'indirizzo del back-end (slide 15, punto 4):
// per puntare a un altro back-end si cambia questa riga, senza toccare il codice.
// Allo step 9 il container sostituirà questo file con uno che usa il proxy ("/api").
window.CONFIGURAZIONE = {
  backendUrl: "http://localhost:8002",
};
