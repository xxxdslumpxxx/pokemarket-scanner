---
title: PokéMarket Scanner
emoji: 🃏
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# PokéMarket Scanner (Mobile Webapp + `reverse-api-engineer`)

Webapp mobile-first (PWA) per scattare una foto dal cellulare a una carta Pokémon e ottenere subito tutte le informazioni e i prezzi da **Cardmarket.com** (**Valore più basso**, **Valore medio / Price Trend**, **Valore più alto**, medie 1/7/30 giorni, Reverse Holo e link diretto).

## Funzionalità
- **Riconoscimento locale RapidOCR (ONNX) + OpenCV** — zero API key, ritaglio automatico della carta, lettura nome + codici in basso a sinistra + riconoscimento dei set con solo simbolo tramite confronto visivo.
- **Prezzi Cardmarket** allineati al **Price Trend**, con supporto opzionale al client live generato con [`kalil0321/reverse-api-engineer`](https://github.com/kalil0321/reverse-api-engineer).
- **Salvataggio locale permanente sul telefono (IndexedDB)** con la tua foto + prezzi.
