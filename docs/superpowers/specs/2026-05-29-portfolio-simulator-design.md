# Design Spec — Portfolio Simulato InsiderTracker

**Data:** 2026-05-29
**Progetto:** Insider Project / InsiderTracker
**Stato:** Approvato

---

## Obiettivo

Simulare un portfolio paper trading da $20,000 USD che acquista automaticamente i segnali insider giornalieri sopra score ≥ 8, li mantiene per 7 giorni di calendario, e li vende all'apertura del mercato US il 7° giorno. Aggiorna un file markdown in Obsidian ogni ora con i prezzi correnti, P&L realizzato/non realizzato e storico trade.

---

## Regole operative

| Parametro | Valore |
|---|---|
| Capitale iniziale | $20,000 USD |
| Score minimo per entrare | ≥ 8 |
| Sizing per score | 🟡 Buono (8–10) → $500 / 🟢 Ottimo (11–13) → $1,000 / 🔥 Eccellente (14+) → $2,000 |
| Prezzo di entrata | Prezzo di apertura US del giorno del segnale |
| Holding period | 7 giorni di calendario |
| Prezzo di uscita | Prezzo di apertura US del 7° giorno |
| Valuta | USD |
| Max posizioni contemporanee | 5 (Mon–Fri, una per giorno) |

---

## Architettura

```
insider_tracker.py (08:00 IT)
  └── dopo send_signal() con score ≥ 8
      └── portfolio_tracker.open_position(ticker, score, signal_date)

portfolio_tracker.py update (16:00 IT + ogni ora 09:00–23:00 IT)
  ├── Per ogni posizione senza entry_price:
  │     se mercato US già aperto oggi → registra prezzo di apertura
  ├── Per ogni posizione con exit_date_target ≤ oggi:
  │     chiude al prezzo di apertura odierno (o ultimo disponibile)
  ├── Per tutte le posizioni aperte:
  │     aggiorna current_price via yfinance
  └── Genera Portfolio Simulato.md in Obsidian
```

---

## File di dati: `portfolio.json`

```json
{
  "capital_initial": 20000.0,
  "cash": 19000.0,
  "positions": [
    {
      "ticker": "NAKA",
      "score": 17,
      "signal_date": "2026-05-29",
      "entry_price": null,
      "shares": null,
      "invested": 2000.0,
      "exit_date_target": "2026-06-05",
      "current_price": null,
      "unrealized_pnl": null
    }
  ],
  "closed": [
    {
      "ticker": "PSEC",
      "score": 6,
      "signal_date": "2026-05-27",
      "entry_price": 5.21,
      "shares": 96.0,
      "invested": 500.0,
      "exit_price": 5.38,
      "exit_date": "2026-06-03",
      "pnl": 16.32,
      "pnl_pct": 3.26
    }
  ]
}
```

**Note:**
- `entry_price = null` fino alle 16:00 IT del giorno del segnale
- `shares = invested / entry_price` (calcolato quando entry_price viene registrato)
- `exit_date_target = signal_date + 7 giorni di calendario`
- La chiusura usa il prezzo di apertura del giorno target (o il primo giorno disponibile se festivo)

---

## Markdown: `Insider Project/Portfolio Simulato.md`

```markdown
# Portfolio Simulato — Insider Tracker
*Aggiornato: 29/05/2026 22:15 (Bali)*

## Riepilogo
| Voce | Valore |
|---|---|
| Capitale iniziale | $20,000 |
| Cash disponibile | $18,000 |
| Valore posizioni | $2,087 |
| **Equity totale** | **$20,087** |
| P&L non realizzato | +$87 (+0.4%) |
| P&L realizzato | +$0 |
| Trade chiusi | 0 (0W / 0L) |
| Win Rate | — |

## Posizioni aperte
| Ticker | Score | Label | Entry | Prezzo | Investito | P&L | Scadenza |
|---|---|---|---|---|---|---|---|
| NAKA | 17 | 🔥 | $5.42 | $5.60 | $2,000 | +$66 (+3.3%) | 05/06 |
| MIMI | 11 | 🟢 | — | — | $1,000 | — | — |

## Storico trade chiusi
| Data | Ticker | Score | Entry | Uscita | Investito | P&L | % |
|---|---|---|---|---|---|---|---|
| 03/06 | PSEC | 6 | $5.21 | $5.38 | $500 | +$16 | +3.3% |
```

**Nota:** le righe con `entry_price = null` mostrano `—` in attesa del prezzo di apertura US.

---

## Nuovo file: `portfolio_tracker.py`

### `position_size(score: int) -> float`
Restituisce l'importo da investire in base allo score:
- score 8–10 → 500.0
- score 11–13 → 1000.0
- score ≥ 14 → 2000.0
- score < 8 → 0.0 (non investire)

### `open_position(ticker, score, signal_date)`
- Se `position_size(score) == 0` → esce senza fare nulla
- Carica `portfolio.json`, aggiunge la nuova posizione, salva
- `exit_date_target = signal_date + timedelta(days=7)`
- `invested = position_size(score)`, `cash -= invested`

### `get_open_price(ticker, target_date) -> Optional[float]`
- `yf.Ticker(ticker).history(start=target_date, end=target_date + 1 day, interval="1d")`
- Restituisce il prezzo di apertura (`Open`) se disponibile, altrimenti None

### `get_current_price(ticker) -> Optional[float]`
- `yf.Ticker(ticker).history(period="1d", interval="1d")["Close"].iloc[-1]`

### `update()`
Eseguito alle 16:00 IT e ogni ora:
1. Carica `portfolio.json`
2. Per ogni posizione con `entry_price == null`: prova a recuperare il prezzo di apertura di `signal_date` → se trovato, setta `entry_price`, `shares = invested / entry_price`
3. Per ogni posizione con `exit_date_target <= oggi`: recupera prezzo apertura di `exit_date_target`, chiude la posizione (sposta in `closed`, aggiorna `cash`, calcola `pnl`)
4. Per ogni posizione aperta: aggiorna `current_price` e `unrealized_pnl`
5. Salva `portfolio.json`
6. Chiama `generate_markdown()`

### `generate_markdown()`
Genera `Insider Project/Portfolio Simulato.md` con i dati attuali.

---

## Modifiche a `insider_tracker.py`

Dopo `send_signal()` con segnale presente, aggiunge:
```python
if sent and top is not None and top.score >= config.PORTFOLIO_MIN_SCORE:
    portfolio_tracker.open_position(top.ticker, top.score, date.today())
```

---

## Nuove costanti `config.py`

```python
PORTFOLIO_MIN_SCORE = 8
PORTFOLIO_CAPITAL = 20_000.0
PORTFOLIO_FILE = Path("portfolio.json")
PORTFOLIO_MD = Path(r"C:\Users\corr8\Desktop\obsidian-vault\Insider Project\Portfolio Simulato.md")
```

---

## Task Scheduler

| Job | Comando | Orario |
|---|---|---|
| InsiderTracker (esistente) | `python insider_tracker.py` | Lun–Ven 08:00 IT |
| PortfolioUpdate | `python portfolio_tracker.py` | Ogni ora 09:00–23:00 IT lun–ven (il run delle 16:00 è il primo dopo l'apertura US alle 15:30 IT) |

---

## Gestione errori

- Se yfinance non trova il prezzo di apertura il giorno stesso → riprova al prossimo run orario
- Se la posizione non ha entry_price dopo 2 giorni → logga warning, usa prezzo di chiusura disponibile
- Se la scrittura del markdown fallisce → logga errore, non interrompe il run

---

## Testing

- `tests/test_portfolio_tracker.py`
- Test chiave:
  - `test_position_size_by_score` — sizing corretto per ogni fascia
  - `test_open_position_adds_to_json` — la posizione viene registrata correttamente
  - `test_open_position_ignores_low_score` — score < 8 non apre posizione
  - `test_update_fills_entry_price` — l'apertura US viene registrata
  - `test_update_closes_expired_position` — posizione scaduta viene chiusa
  - `test_update_calculates_pnl` — P&L corretto
  - `test_generate_markdown_format` — output markdown corretto

---

## Fuori scope

- Notifiche Telegram sull'apertura/chiusura posizioni
- Gestione commissioni/slippage
- Grafici e visualizzazioni

---

*Spec approvata il 2026-05-29*
