# Design Spec — Company Analyzer v2: Message Redesign

**Data:** 2026-05-29
**Progetto:** Insider Project / InsiderTracker
**Stato:** Approvato

---

## Obiettivo

Migliorare il secondo messaggio Telegram inviato dopo ogni segnale giornaliero:
- Mostrare la **lista individuale** degli acquisti significativi degli ultimi 12 mesi (con insider name, importo, risultato T+3/T+7/T+30 per ciascuno)
- Usare soglia **fissa** `MIN_SCORE = 5` (non più `today_score`) per trovare gli storici
- Mantenere le statistiche aggregate su 2 anni sotto la lista
- Ordinare per data più recente prima, troncare a 5 se troppi

---

## Formato messaggio

### Con storico disponibile

```
📊 ANALISI STORICA — $TICKER

📋 Acquisti significativi (ultimi 12 mesi):
• 15/03 — CEO J. Smith $250K → +5% / +18% / +22%
• 10/01 — CFO J. Doe $150K  → -2% / -3% / +8%
• 05/11 — CEO J. Smith $500K → +12% / +35% / +41%

📈 Performance media (N segnali, 2 anni):
• T+3:   +4.2%  (4/5 positivi)
• T+7:  +11.8%  (5/5 positivi) ← migliore
• T+30:  +8.1%  (4/5 positivi)

🎯 Raccomandazione: COMPRA
• Entry: $3.21 • TP: $3.59 • SL: $2.95 • Holding: ~7gg
```

**Note formato lista:**
- Se T+N non disponibile (titolo troppo recente): mostra `—` al posto del %
- Formato importo: `$250K` se < $1M, `$1.2M` se ≥ $1M
- Nome insider: cognome + iniziale nome (es. "J. Smith") per compattezza
- Max 5 acquisti mostrati (i più recenti), se ce ne sono di più aggiunge `… e altri N`
- Segno `+` o `-` esplicito su ogni percentuale

### Senza storico

```
📊 ANALISI STORICA — $TICKER

📋 Acquisti significativi (ultimi 12 mesi): nessuno trovato

🎯 Raccomandazione: N/D — nessun dato storico
```

---

## Architettura — Modifiche a `company_analyzer.py`

### Nuovo dataclass: `SignalEvent`

```python
@dataclass
class SignalEvent:
    trade_date: date
    ticker: str
    score: int
    insiders: List[Tuple[str, str, float]]  # (name, title, value_usd)
    t3_pct: Optional[float] = None
    t7_pct: Optional[float] = None
    t30_pct: Optional[float] = None
```

### Modifica `score_and_filter(transactions, min_score) → List[SignalEvent]`

- Stessa logica di grouping per `trade_date`
- Restituisce `List[SignalEvent]` invece di `List[Tuple[date, str, int]]`
- Ogni `SignalEvent` include la lista degli insider che hanno comprato quel giorno

### Modifica `backtest(signal_events) → Dict[int, BacktestResult]`

- Accetta `List[SignalEvent]` invece di `List[Tuple[date, str, int]]`
- **Popola `t3_pct`, `t7_pct`, `t30_pct` su ogni `SignalEvent`** (mutazione in-place)
- Restituisce le statistiche aggregate `Dict[int, BacktestResult]` come prima

### Modifica `build_message(...)`

Nuova signature:
```python
def build_message(
    ticker: str,
    entry_price: float,
    signal_events: List[SignalEvent],     # sostituisce signal_count
    stats: Dict[int, BacktestResult],
    rec: Recommendation,
    today_score: int,
) -> str:
```

- Filtra `signal_events` a ultimi 12 mesi per la lista (`COMPANY_DISPLAY_LOOKBACK_DAYS = 365`)
- Ordina per `trade_date` decrescente (più recente prima)
- Tronca a `MAX_DISPLAY_PURCHASES = 5`
- Usa le statistiche aggregate per la sezione `📈`

### Modifica `analyze(ticker, cik, today_score, entry_price) → str`

- Usa `config.MIN_SCORE` invece di `today_score` per `score_and_filter`
- Passa `signal_events` a `build_message`

---

## Modifiche a `config.py`

```python
COMPANY_DISPLAY_LOOKBACK_DAYS = 365   # finestra di display lista acquisti (12 mesi)
MAX_DISPLAY_PURCHASES = 5             # max righe nella lista individuale
```

---

## Helper privato: `_format_purchase_row(event, idx)`

```python
def _format_purchase_row(event: SignalEvent) -> str:
    """Formatta una riga della lista acquisti per Telegram."""
    # Es: "• 15/03 — CEO J. Smith $250K → +5% / +18% / +22%"
```

- Formato data: `DD/MM`
- Formato importo: `$250K` / `$1.2M`
- Formato nome: iniziale nome + cognome
- Formato pct: `+X.X%` se disponibile, `—` se None

---

## Invarianti rispetto alla v1

- `fetch_company_history()` — invariato
- `_price_on_or_after()` — invariato
- `generate_recommendation()` — invariato
- `BacktestResult`, `Recommendation` dataclasses — invariati
- `notifier.send_analysis()` — invariato
- `insider_tracker.py` — invariato (la firma di `analyze()` non cambia)

---

## Modifiche ai test

**`tests/test_company_analyzer.py`**:
- Aggiornare test di `score_and_filter` per il nuovo tipo di ritorno `List[SignalEvent]`
- Aggiornare test di `backtest` per accettare `List[SignalEvent]`
- Aggiornare test di `build_message` per la nuova signature
- Aggiornare test di `analyze` per verificare che usi `MIN_SCORE`
- Aggiungere test per `_format_purchase_row`
- Aggiungere test per troncamento a 5 e ordinamento per data

---

## Fuori scope

- Portfolio simulator (trattato separatamente)
- Filtro per singolo insider (es. solo CEO)
- Grafici o visualizzazioni

---

*Spec approvata il 2026-05-29*
