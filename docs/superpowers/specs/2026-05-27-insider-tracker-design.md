# Insider Tracker — Design Spec
**Data:** 2026-05-27  
**Stato:** Approvato  

---

## Obiettivo

Script Python autonomo che ogni mattina alle 8:00 (ora italiana) analizza gli acquisti insider recenti su OpenInsider, calcola uno score per ogni ticker e invia via Telegram il miglior segnale del giorno. Progetto separato dallo Stock Market Bot, in ottica puramente speculativa.

---

## Scope

- Mercato: **USA** (dati SEC Form 4 via OpenInsider)
- Output: **top 1 ticker** al giorno
- Automazione: **Windows Task Scheduler** (nessun daemon)
- Notifiche: **Telegram** (stessi credential del bot)

---

## Struttura Progetto

```
C:\Users\corr8\Desktop\InsiderTracker\
├── insider_tracker.py   ← entry point principale
├── scraper.py           ← fetch + parsing OpenInsider
├── scorer.py            ← algoritmo di scoring
├── notifier.py          ← invio Telegram
├── config.py            ← soglie, impostazioni
├── .env                 ← TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
├── last_seen.json       ← ticker già inviati (anti-duplicate)
├── run_insider.bat      ← lancio manuale
├── errors.log           ← log errori
└── venv/
```

---

## Flusso Principale

1. Task Scheduler lancia `insider_tracker.py` alle **8:00 IT** (CEST, UTC+2)
2. `scraper.py` fa fetch di 3 URL OpenInsider:
   - `/latest-cluster-buys` — ultimi cluster buy
   - `/latest-ceo-cfo-purchases-25k` — acquisti CEO/CFO ≥$25K
   - `/screener?s=0&o=&pl=50000&fd=3&td=&xp=1&vl=50000` — qualsiasi officer ≥$50K (parametri verificati durante implementazione)
3. Dati uniti e deduplicati per ticker (finestra: **3 giorni lavorativi**)
4. `scorer.py` calcola punteggio per ogni ticker
5. Top 1 ticker (score ≥ soglia minima) → `notifier.py` → Telegram
6. Aggiornamento `last_seen.json`
7. Script termina

---

## Sistema di Scoring

| Fattore | Condizione | Punti |
|---|---|---|
| Ruolo insider | CEO | +4 |
| | CFO | +3 |
| | Director / altri officer | +1 |
| Dimensione acquisto | $50K – $100K | +1 |
| | $100K – $500K | +2 |
| | $500K+ | +4 |
| Cluster buy | 2 insider negli ultimi 3 giorni lavorativi | +3 |
| | 3+ insider negli ultimi 3 giorni lavorativi | +6 |
| Cluster size totale | Totale cluster >$500K | +3 |

- **Score massimo teorico:** ~20 punti
- **Soglia minima per invio:** 5 punti — sotto questa soglia il messaggio è "Nessun segnale oggi"
- **Finestra temporale:** ultimi 3 giorni lavorativi

---

## Formato Messaggio Telegram

### Caso normale (segnale trovato):
```
🔍 INSIDER TRACKER — 27/05/2026

📌 $AAPL — Apple Inc.
👤 Tim Cook (CEO) → $2.500.000
👤 Luca Maestri (CFO) → $800.000
👤 Jeff Williams (COO) → $120.000

📊 Score: 17 pt
• CEO buy ✅ +4
• CFO buy ✅ +3
• Importo $500K+ ✅ +4
• Cluster 3 insider ✅ +6

🔗 openinsider.com/AAPL
```

### Nessun segnale:
```
🔍 INSIDER TRACKER — 27/05/2026
😴 Nessun segnale insider oggi.
```

---

## Gestione Errori

| Scenario | Comportamento |
|---|---|
| OpenInsider non risponde | 3 retry con backoff esponenziale, poi Telegram: "⚠️ Errore scraping OpenInsider" |
| Nessun ticker sopra soglia | Messaggio "Nessun segnale oggi" |
| Telegram non raggiungibile | Log su `errors.log` |
| Ticker già inviato oggi | Controllo `last_seen.json`, skip silenzioso |
| PC spento alle 8:00 | Nessun recupero (non critico, è solo un briefing) |

---

## Dipendenze Python

- `requests` — HTTP fetch
- `beautifulsoup4` — parsing HTML OpenInsider
- `python-dotenv` — lettura `.env`
- `python-telegram-bot` (o `requests` diretto) — invio Telegram

---

## Task Scheduler

- **Trigger:** Daily, 08:00 ora italiana (CEST)
- **Azione:** `C:\Users\corr8\Desktop\InsiderTracker\run_insider.bat`
- **Fuso orario:** impostare il task con fuso orario Europe/Rome

---

## Decisioni di Design

- **Separato dal bot:** cartella, venv e credenziali indipendenti (ma stesso Telegram)
- **Nessun daemon:** il Task Scheduler è sufficiente per un'esecuzione giornaliera
- **Scraping e non API:** OpenInsider è gratuito e ha URL stabili usati da anni
- **Top 1 solo:** riduce il rumore, forza a scegliere il segnale migliore
- **Finestra 3gg:** cattura filing in ritardo e transazioni del weekend
