# Design Spec — Company Analyzer & Performance Tracker

**Data:** 2026-05-29
**Progetto:** Insider Project / InsiderTracker
**Stato:** Approvato

---

## Obiettivo

Aggiungere un secondo messaggio Telegram inviato subito dopo il segnale giornaliero. Il messaggio analizza lo storico degli acquisti insider per l'azienda specifica segnalata oggi, calcola come si è comportato il titolo dopo ogni acquisto passato, e fornisce una raccomandazione operativa (compra/N/D) con entry, TP, SL e holding period consigliato.

---

## Architettura

```
insider_tracker.py
  ↓ dopo send_signal()
  ↓ chiama company_analyzer.analyze(ticker, cik, today_score, entry_price)
  ↓ chiama notifier.send_analysis(message)   ← secondo messaggio Telegram

company_analyzer.py (nuovo modulo)
  - fetch_company_history()    → EDGAR EFTS: tutti i Form 4 (code=P) ultimi 2 anni per CIK
  - score_and_filter()         → riusa scorer.py, tiene solo score ≥ today_score
  - backtest()                 → yfinance: prezzo a T+3, T+7, T+30 per ogni acquisto storico
  - generate_recommendation()  → calcola TP, SL, holding period ottimale
  - build_message()            → formatta il messaggio Telegram
```

Il modulo riutilizza `scraper.py` e `scorer.py` esistenti senza duplicare logica.
`notifier.py` riceve una nuova funzione `send_analysis(message: str)`.
`insider_tracker.py` aggiunge 2-3 righe dopo `send_signal()`.

---

## Nuovo file: `company_analyzer.py`

### `fetch_company_history(cik, lookback_days=730)`
- Query EDGAR EFTS per tutti i Form 4 del CIK emittente negli ultimi `lookback_days` giorni
- Filtra code=`P`, valore ≥ $50K
- Restituisce lista di `InsiderTransaction` (riutilizza il tipo già definito in `scraper.py`)

### `score_and_filter(transactions, min_score)`
- Raggruppa le transazioni per data di filing (come fa `scorer.py`)
- Calcola score per ogni gruppo usando la logica esistente di `scorer.py`
- Tiene solo i gruppi con score ≥ `min_score`
- Restituisce lista di `(filing_date, ticker, score)`

### `backtest(filtered_signals)`
- Per ogni segnale storico, usa `yfinance` per recuperare:
  - Prezzo di chiusura al giorno del filing (`entry_price`)
  - Prezzo a T+3, T+7, T+30 giorni di borsa (skippa weekend/festivi automaticamente via yfinance)
- Calcola `pct = (price_at_T - entry_price) / entry_price * 100`
- Restituisce dict con statistiche: `{t3: {avg, positives, total}, t7: {...}, t30: {...}}`

### `generate_recommendation(stats, entry_price)`
- Individua il T migliore: quello con il più alto % positivi (tie-break: avg return)
- Se 0 segnali storici trovati → restituisce `None` (nessuna raccomandazione)
- Se trovati ≥ 1 segnale:
  - `action = "COMPRA"` se avg_return al T migliore > 0, altrimenti `"ATTENZIONE"`
  - `tp = entry_price × (1 + avg_return_at_best_T / 100)` arrotondato a 2 decimali
  - `sl = entry_price × 0.92` (fisso -8%)
  - `holding_period = best_T` (3, 7, o 30 giorni)

### `build_message(ticker, stats, recommendation, today_score)`
- Formatta il secondo messaggio Telegram (vedi sezione Formato Messaggi)

---

## Formato messaggi Telegram

### Con storico disponibile

```
📊 ANALISI STORICA — $TICKER

🔍 Acquisti passati con score ≥ X: N trovati

📈 Performance media post-acquisto:
• a 3 giorni:  +4.2%  (2/3 positivi)
• a 7 giorni:  +11.8% (3/3 positivi) ← migliore
• a 30 giorni: +8.1%  (2/3 positivi)

🎯 Raccomandazione: COMPRA
• Entry: $3.21
• TP: $3.59  (+12%, basato su media 7gg)
• SL: $2.95  (-8%)
• Holding: ~7 giorni
```

### Senza storico (primo acquisto rilevante)

```
📊 ANALISI STORICA — $TICKER

🔍 Acquisti passati con score ≥ X: nessuno trovato
→ Primo acquisto rilevante per questa azienda

🎯 Raccomandazione: N/D — nessun dato storico
```

---

## Modifiche ai file esistenti

### `scraper.py`
- Aggiunge campo `cik: str` a `InsiderTransaction` (il CIK dell'emittente, già disponibile nel parsing EFTS — è l'ultimo elemento dell'array `ciks`)
- Nessuna modifica alla logica di parsing, solo campo in più nel dataclass

### `notifier.py`
- Aggiunge `send_analysis(message: str) -> None`
- Stessa logica di `send_signal`: chiama Telegram Bot API, gestisce errori

### `insider_tracker.py`
- Dopo `send_signal(signal)`, aggiunge:
  ```python
  cik = signal.transactions[0].cik  # CIK disponibile da InsiderTransaction
  entry_price = get_current_price(signal.ticker)  # via yfinance
  analysis_msg = company_analyzer.analyze(
      signal.ticker, cik, signal.score, entry_price
  )
  notifier.send_analysis(analysis_msg)
  ```

### `config.py`
- Aggiunge costanti:
  - `COMPANY_HISTORY_LOOKBACK_DAYS = 730` (2 anni)
  - `SL_PERCENT = 0.08` (8% stop loss fisso)

---

## Dipendenze

- `yfinance` — aggiunta a `requirements.txt`
- Nessuna API key necessaria

---

## Gestione errori

- Se EDGAR non risponde per il fetch storico → invia il messaggio "nessun dato" (opzione B)
- Se `yfinance` non trova prezzi storici per un dato giorno → skippa quella data nel calcolo
- Se il secondo messaggio Telegram fallisce → logga l'errore, non blocca il run principale

---

## Testing

- `tests/test_company_analyzer.py` — mock EDGAR + mock yfinance
- Test chiave:
  - `test_no_history_returns_nd_message` — CIK senza acquisti precedenti
  - `test_backtest_computes_correct_pct` — calcolo % ritorno corretto
  - `test_best_t_selection` — scelta del T migliore
  - `test_recommendation_buy_vs_caution` — action COMPRA vs ATTENZIONE
  - `test_sl_tp_calculation` — valori TP/SL corretti
  - `test_build_message_format` — output Telegram corretto

---

## Fuori scope (da fare separatamente)

- Portfolio simulator (tracking posizioni aperte, P&L)
- Outcome tracker delle nostre stesse segnalazioni passate
- Notifiche quando T+3/T+7/T+30 matura su segnali inviati

---

*Spec approvata il 2026-05-29*
