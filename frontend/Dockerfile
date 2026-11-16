# Immagine del front-end (lezione 6, step 9): nginx che serve la pagina e fa da proxy verso il back-end.
#   docker compose build frontend
FROM nginx:1.28-alpine

# Configurazione del server: file statici + proxy di /api/ (vedi docker/nginx.conf).
COPY frontend/docker/nginx.conf /etc/nginx/conf.d/default.conf

# I file della pagina. I test (frontend/test) e package.json non servono nell'immagine.
COPY frontend/index.html frontend/stile.css frontend/api.js frontend/app.js /usr/share/nginx/html/

# Nel container l'indirizzo del back-end è il proxy: questo file prende il posto di frontend/config.js.
COPY frontend/docker/config.js /usr/share/nginx/html/config.js
