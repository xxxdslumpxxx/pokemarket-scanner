# PokéMarket Scanner (Mobile Webapp + `reverse-api-engineer`)

Webapp mobile-first (PWA) per scattare una foto dal cellulare a una carta Pokémon e ottenere subito tutte le informazioni e i prezzi da **Cardmarket.com** (**Valore più basso**, **Valore medio / Trend**, **Valore più alto**, medie 1/7/30 giorni, Reverse Holo e link diretto).

## Funzionalità principali
- **Fotocamera Mobile-First** con cornice guida a proporzioni carta Pokémon (`63:88`) + fallback diretto alla fotocamera nativa dello smartphone (`<input capture="environment">`).
- **Riconoscimento Vision AI** (`backend/vision_service.py`): legge nome, numero carta (`es. 199/165`), set, lingua, condizione stimata e olografia.
- **Integrazione [`kalil0321/reverse-api-engineer`](https://github.com/kalil0321/reverse-api-engineer)**:
  - Script guidato `scripts/capture_cardmarket.py` per catturare il traffico di `cardmarket.com` nel browser e generare il client API in `generated_client/cardmarket_client.py`.
  - Endpoint `POST /api/reverse-api/import-har` per importare file `.har` catturati.
  - Adapter integrato per i dati Cardmarket (via Pokémon TCG API v2 e TCGdex, con supporto anche a nomi italiani) attivo subito senza configurazioni extra.
- **Cronologia locale** sul cellulare (`localStorage`).

## Avvio rapido

1. **Configura la Vision API Key** (solo in locale nel file `.env`):
   Copia `.env.example` in `.env` e inserisci la tua `GEMINI_API_KEY` (oppure `OPENAI_API_KEY`).

2. **Avvia il server**:
   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
   ```

3. **Apri dal cellulare** (collegato allo stesso Wi-Fi):
   - Trova l'IP locale del tuo PC (`ipconfig`, es. `192.168.1.50`)
   - Apri `http://192.168.1.50:8000` sul browser dello smartphone.
   - *(Nota: su HTTP locale i browser mobili disattivano lo streaming `getUserMedia`, ma il bottone **Galleria / Foto** apre direttamente la fotocamera nativa del telefono! Per lo streaming live con cornice, esponi la porta 8000 in HTTPS tramite Cloudflare Tunnel / ngrok).*

4. **Genera il client live con `reverse-api-engineer`** (opzionale per avere le singole inserzioni live):
   ```powershell
   .\.venv\Scripts\python.exe scripts\capture_cardmarket.py
   ```
