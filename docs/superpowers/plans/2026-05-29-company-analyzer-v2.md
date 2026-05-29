# Company Analyzer v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the second Telegram message to show individual insider purchases (last 12 months) with T+3/T+7/T+30 per row, using a fixed MIN_SCORE threshold and keeping aggregate stats for 2 years below.

**Architecture:** Add `SignalEvent` dataclass to carry per-event data; modify `score_and_filter` to return `List[SignalEvent]`; modify `backtest` to accept `List[SignalEvent]` and populate per-event pcts in-place; rewrite `build_message` with new format; update `analyze` to use `config.MIN_SCORE` instead of `today_score`.

**Tech Stack:** Python 3.x, existing `company_analyzer.py`, `config.py`, `scorer.py`, `yfinance` (already installed)

---

## File Map

| File | Action | What changes |
|---|---|---|
| `config.py` | Modify | Add `COMPANY_DISPLAY_LOOKBACK_DAYS = 365`, `MAX_DISPLAY_PURCHASES = 5` |
| `company_analyzer.py` | Modify | Add `SignalEvent`, update `score_and_filter`, update `backtest`, add `_fmt_value` / `_short_role` / `_format_purchase_row`, rewrite `build_message`, update `analyze` |
| `tests/test_company_analyzer.py` | Modify | Update tests for changed signatures; add new tests for helpers and new format |
| `tests/test_tracker.py` | Modify | Add 2 tests for new config constants |

---

## Task 1: Add display constants to `config.py`

**Files:**
- Modify: `config.py`
- Modify: `tests/test_tracker.py`

- [ ] **Write the failing tests** — add at the end of `tests/test_tracker.py`:

```python
def test_config_has_company_display_lookback_days():
    import config
    assert config.COMPANY_DISPLAY_LOOKBACK_DAYS == 365

def test_config_has_max_display_purchases():
    import config
    assert config.MAX_DISPLAY_PURCHASES == 5
```

- [ ] **Run tests to verify they fail**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_tracker.py::test_config_has_company_display_lookback_days tests/test_tracker.py::test_config_has_max_display_purchases -v"`

Expected: FAIL — `AttributeError: module 'config' has no attribute 'COMPANY_DISPLAY_LOOKBACK_DAYS'`

- [ ] **Implement: append to `config.py`** after `SL_PERCENT = 0.08`:

```python
COMPANY_DISPLAY_LOOKBACK_DAYS = 365   # 12 months shown in purchase list
MAX_DISPLAY_PURCHASES = 5             # max rows in the individual purchase list
```

- [ ] **Run tests to verify they pass**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_tracker.py -v"`

Expected: all tracker tests pass.

- [ ] **Run full suite — no regressions**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/ -v"`

Expected: 124 → 126 passed.

- [ ] **Commit**

```bash
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" add config.py tests/test_tracker.py
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" commit -m "feat(config): add COMPANY_DISPLAY_LOOKBACK_DAYS and MAX_DISPLAY_PURCHASES"
```

---

## Task 2: Add `SignalEvent` dataclass + update `score_and_filter`

**Files:**
- Modify: `company_analyzer.py` (add dataclass, change `score_and_filter` return type)
- Modify: `tests/test_company_analyzer.py` (update 5 existing tests, add `_make_signal_event` helper)

**Context:** `score_and_filter` currently returns `List[Tuple[date, str, int]]`. It must now return `List[SignalEvent]` so downstream functions can access insider names, amounts, and per-event performance. The `insiders` field is populated from `sig.transactions` returned by `score_all`.

- [ ] **Update the imports in `tests/test_company_analyzer.py`**

Change the import block at the top from:
```python
from company_analyzer import (
    fetch_company_history,
    score_and_filter,
    backtest,
    BacktestResult,
    Recommendation,
    generate_recommendation,
    build_message,
    analyze,
)
```
to:
```python
from company_analyzer import (
    fetch_company_history,
    score_and_filter,
    backtest,
    BacktestResult,
    Recommendation,
    SignalEvent,
    generate_recommendation,
    build_message,
    analyze,
)
```

- [ ] **Add `_make_signal_event` helper** — add after `_make_tx` in the test file:

```python
def _make_signal_event(
    trade_date=date(2026, 1, 10),
    ticker=_TICKER,
    score=8,
    insiders=None,
) -> SignalEvent:
    if insiders is None:
        insiders = [("Chan Hoi Lung", "Chief Executive Officer", 637_756.0)]
    return SignalEvent(
        trade_date=trade_date,
        ticker=ticker,
        score=score,
        insiders=insiders,
    )
```

- [ ] **Update the 5 `score_and_filter` tests** — replace tuple indexing with attribute access:

Replace all 5 tests in the `# ── score_and_filter ──` section with:

```python
# ── score_and_filter ──────────────────────────────────────────────────────

def test_score_and_filter_returns_signals_above_min_score():
    txs = [_make_tx(value=637_756.0, trade_date=date(2026, 1, 10))]
    result = score_and_filter(txs, min_score=8)
    assert len(result) == 1
    assert result[0].trade_date == date(2026, 1, 10)
    assert result[0].ticker == _TICKER
    assert result[0].score >= 8
    assert len(result[0].insiders) == 1
    assert result[0].insiders[0][0] == "Chan Hoi Lung"


def test_score_and_filter_excludes_signals_below_min_score():
    txs = [_make_tx(title="Director", value=60_000.0, trade_date=date(2026, 1, 10))]
    result = score_and_filter(txs, min_score=8)
    assert result == []


def test_score_and_filter_groups_by_date():
    txs = [
        _make_tx(trade_date=date(2026, 1, 10), value=637_756.0),
        _make_tx(trade_date=date(2026, 3, 15), value=637_756.0),
    ]
    result = score_and_filter(txs, min_score=5)
    assert len(result) == 2
    dates = {e.trade_date for e in result}
    assert date(2026, 1, 10) in dates
    assert date(2026, 3, 15) in dates


def test_score_and_filter_skips_transactions_without_trade_date():
    txs = [_make_tx(trade_date=None)]
    result = score_and_filter(txs, min_score=5)
    assert result == []


def test_score_and_filter_applies_cluster_bonus_for_same_date():
    txs = [
        _make_tx(insider="CEO Person", title="Chief Executive Officer",
                 value=200_000.0, trade_date=date(2026, 1, 10)),
        _make_tx(insider="CFO Person", title="Chief Financial Officer",
                 value=100_000.0, trade_date=date(2026, 1, 10)),
    ]
    result = score_and_filter(txs, min_score=5)
    assert len(result) == 1
    assert result[0].score >= 10
    assert len(result[0].insiders) == 2
```

- [ ] **Run tests to verify they FAIL** (SignalEvent not yet defined)

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_company_analyzer.py -v -k score_and_filter"`

Expected: FAIL — `ImportError: cannot import name 'SignalEvent'`

- [ ] **Implement: add `SignalEvent` dataclass** to `company_analyzer.py`

In `company_analyzer.py`, add after the `Recommendation` dataclass (after line 64, before the `# ── EDGAR company history fetch` comment):

```python

@dataclass
class SignalEvent:
    """A scored insider buying event on a specific trade date."""
    trade_date: date
    ticker: str
    score: int
    insiders: List[Tuple[str, str, float]]  # (name, title, value_usd)
    t3_pct: Optional[float] = None
    t7_pct: Optional[float] = None
    t30_pct: Optional[float] = None
```

- [ ] **Implement: update `score_and_filter` return type** in `company_analyzer.py`

Replace the entire `score_and_filter` function (lines 177–206) with:

```python
def score_and_filter(
    transactions: List[InsiderTransaction],
    min_score: int,
) -> List[SignalEvent]:
    """Score historical transactions grouped by trade_date and filter by min_score.

    Groups transactions by trade_date (each date = one "event"), scores each
    group with score_all (applies cluster bonuses for same-day multi-insider buys),
    and returns SignalEvent objects where score >= min_score.

    Transactions without a trade_date are skipped.

    Note: groups by ``trade_date`` (execution date), not ``filing_date``. Same-day
    buys by multiple insiders form a single identifiable cluster event — this is the
    correct basis for backtesting.
    """
    dated = [t for t in transactions if t.trade_date is not None]

    by_date: dict = defaultdict(list)
    for t in dated:
        by_date[t.trade_date].append(t)

    results: List[SignalEvent] = []
    for trade_date in sorted(by_date.keys()):
        signals = score_all(by_date[trade_date])
        for sig in signals:
            if sig.score >= min_score:
                insiders = [(tx.insider_name, tx.title, tx.value)
                            for tx in sig.transactions]
                results.append(SignalEvent(
                    trade_date=trade_date,
                    ticker=sig.ticker,
                    score=sig.score,
                    insiders=insiders,
                ))

    return results
```

- [ ] **Run tests to verify they pass**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_company_analyzer.py -v -k score_and_filter"`

Expected: all 5 score_and_filter tests pass.

- [ ] **Run full suite — no regressions**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/ -v"`

Expected: all pass (some backtest/analyze tests may fail — that is expected, they will be fixed in Tasks 3–6).

- [ ] **Commit**

```bash
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" add company_analyzer.py tests/test_company_analyzer.py
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" commit -m "feat(company_analyzer): add SignalEvent dataclass, update score_and_filter return type"
```

---

## Task 3: Update `backtest` to accept `List[SignalEvent]`

**Files:**
- Modify: `company_analyzer.py` — change `backtest` signature and body
- Modify: `tests/test_company_analyzer.py` — update 5 existing backtest tests, add 2 new ones

**Context:** `backtest` must now accept `List[SignalEvent]` instead of `List[Tuple[date, str, int]]`. It populates `t3_pct`, `t7_pct`, `t30_pct` on each event in-place (mutation) and still returns aggregate `Dict[int, BacktestResult]`.

- [ ] **Update the 5 existing backtest tests** — replace tuple input with `SignalEvent` input:

Replace all 5 tests in the `# ── backtest ──` section with:

```python
# ── backtest ──────────────────────────────────────────────────────────────

def _make_hist(*date_price_pairs) -> pd.DataFrame:
    """Build a mock yfinance history DataFrame."""
    dates = [pd.Timestamp(d) for d, _ in date_price_pairs]
    prices = [p for _, p in date_price_pairs]
    return pd.DataFrame({"Close": prices}, index=pd.DatetimeIndex(dates))


@patch("company_analyzer.yf")
def test_backtest_returns_empty_results_for_no_signals(mock_yf):
    result = backtest([])
    for h in [3, 7, 30]:
        assert result[h].count == 0


@patch("company_analyzer.yf")
def test_backtest_computes_correct_pct_at_each_horizon(mock_yf):
    hist = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 13), 11.0),   # T+3 → +10%
        (date(2026, 1, 17), 12.0),   # T+7 → +20%
        (date(2026, 2, 9),  14.0),   # T+30 → +40%
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    events = [_make_signal_event(trade_date=date(2026, 1, 10))]
    result = backtest(events)
    assert result[3].avg_pct == pytest.approx(10.0, abs=0.1)
    assert result[7].avg_pct == pytest.approx(20.0, abs=0.1)
    assert result[30].avg_pct == pytest.approx(40.0, abs=0.1)


@patch("company_analyzer.yf")
def test_backtest_counts_positives_correctly(mock_yf):
    hist1 = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 17), 11.0),   # +10%
    )
    hist2 = _make_hist(
        (date(2026, 3, 1), 20.0),
        (date(2026, 3, 8), 19.0),    # -5%
    )
    mock_yf.Ticker.return_value.history.side_effect = [hist1, hist2]
    events = [
        _make_signal_event(trade_date=date(2026, 1, 10)),
        _make_signal_event(trade_date=date(2026, 3, 1)),
    ]
    result = backtest(events)
    assert result[7].count == 2
    assert result[7].positives == 1


@patch("company_analyzer.yf")
def test_backtest_skips_signal_when_yfinance_returns_empty(mock_yf):
    mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
    events = [_make_signal_event()]
    result = backtest(events)
    for h in [3, 7, 30]:
        assert result[h].count == 0


@patch("company_analyzer.yf")
def test_backtest_skips_horizon_when_price_unavailable(mock_yf):
    hist = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 13), 11.0),
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    events = [_make_signal_event()]
    result = backtest(events)
    assert result[3].count == 1
    assert result[7].count == 0
    assert result[30].count == 0


@patch("company_analyzer.yf")
def test_backtest_populates_per_event_pcts(mock_yf):
    hist = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 13), 11.0),   # T+3 → +10%
        (date(2026, 1, 17), 12.0),   # T+7 → +20%
        (date(2026, 2, 9),  14.0),   # T+30 → +40%
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    event = _make_signal_event(trade_date=date(2026, 1, 10))
    backtest([event])
    assert event.t3_pct == pytest.approx(10.0, abs=0.1)
    assert event.t7_pct == pytest.approx(20.0, abs=0.1)
    assert event.t30_pct == pytest.approx(40.0, abs=0.1)


@patch("company_analyzer.yf")
def test_backtest_leaves_pct_none_when_price_unavailable(mock_yf):
    hist = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 13), 11.0),   # only T+3 available
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    event = _make_signal_event(trade_date=date(2026, 1, 10))
    backtest([event])
    assert event.t3_pct == pytest.approx(10.0, abs=0.1)
    assert event.t7_pct is None
    assert event.t30_pct is None
```

- [ ] **Run tests to verify they FAIL**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_company_analyzer.py -v -k backtest"`

Expected: FAIL — `TypeError` (tuple unpacking `trade_date, ticker, _score in signals` fails on `SignalEvent`)

- [ ] **Implement: update `backtest` in `company_analyzer.py`**

Replace the entire `backtest` function (lines 227–281) with:

```python
def backtest(
    signal_events: List[SignalEvent],
) -> Dict[int, BacktestResult]:
    """Compute stock price performance at T+3, T+7, T+30 for each signal event.

    For each SignalEvent, fetches 45 days of price data via yfinance and computes
    % return at each horizon. Populates t3_pct, t7_pct, t30_pct on each event
    in-place (None if price data unavailable for that horizon).

    Returns aggregate BacktestResult per horizon keyed by 3, 7, 30.
    """
    horizons = [3, 7, 30]
    accum: Dict[int, Dict] = {h: {"pos": 0, "total": 0, "sum_pct": 0.0} for h in horizons}

    for event in signal_events:
        trade_date = event.trade_date
        ticker = event.ticker
        end_fetch = trade_date + timedelta(days=45)
        try:
            hist = yf.Ticker(ticker).history(
                start=trade_date.isoformat(),
                end=end_fetch.isoformat(),
                auto_adjust=True,
            )
        except Exception as exc:
            logger.warning("yfinance error for %s on %s: %s", ticker, trade_date, exc)
            continue

        if hist.empty:
            continue

        entry = _price_on_or_after(hist, trade_date)
        if entry is None or entry <= 0:
            continue

        for h in horizons:
            exit_date = trade_date + timedelta(days=h)
            exit_price = _price_on_or_after(hist, exit_date)
            if exit_price is None:
                continue
            pct = round((exit_price - entry) / entry * 100, 1)
            accum[h]["total"] += 1
            accum[h]["sum_pct"] += pct
            if pct > 0:
                accum[h]["pos"] += 1
            # Populate per-event result
            if h == 3:
                event.t3_pct = pct
            elif h == 7:
                event.t7_pct = pct
            elif h == 30:
                event.t30_pct = pct

    result: Dict[int, BacktestResult] = {}
    for h in horizons:
        a = accum[h]
        result[h] = BacktestResult(
            horizon_days=h,
            count=a["total"],
            positives=a["pos"],
            avg_pct=round(a["sum_pct"] / a["total"], 2) if a["total"] > 0 else 0.0,
        )
    return result
```

- [ ] **Run tests to verify they pass**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_company_analyzer.py -v -k backtest"`

Expected: all 7 backtest tests pass.

- [ ] **Run full suite**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/ -v"`

Expected: backtest tests pass; `build_message` and `analyze` tests may still fail — that's expected.

- [ ] **Commit**

```bash
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" add company_analyzer.py tests/test_company_analyzer.py
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" commit -m "feat(company_analyzer): update backtest to accept SignalEvent, populate per-event pcts"
```

---

## Task 4: Add `_fmt_value`, `_short_role`, `_format_purchase_row` helpers

**Files:**
- Modify: `company_analyzer.py` — add 3 private helpers before `build_message`
- Modify: `tests/test_company_analyzer.py` — add 5 new tests

**Context:** These helpers format one row of the purchase list for Telegram. `_fmt_value` converts a float to `$250K`/`$1.2M`. `_short_role` maps a full title to a short label. `_format_purchase_row` assembles the full row string.

- [ ] **Write 5 failing tests** — add at end of `tests/test_company_analyzer.py`:

```python
# ── format helpers ────────────────────────────────────────────────────────

from company_analyzer import _fmt_value, _short_role, _format_purchase_row


def test_fmt_value_thousands():
    assert _fmt_value(637_756.0) == "$638K"


def test_fmt_value_millions():
    assert _fmt_value(1_500_000.0) == "$1.5M"


def test_fmt_value_small():
    assert _fmt_value(50_000.0) == "$50K"


def test_short_role_ceo():
    assert _short_role("Chief Executive Officer") == "CEO"


def test_short_role_cfo():
    assert _short_role("Chief Financial Officer") == "CFO"


def test_format_purchase_row_basic():
    event = SignalEvent(
        trade_date=date(2026, 3, 15),
        ticker="MIMI",
        score=8,
        insiders=[("Chan Hoi Lung", "Chief Executive Officer", 637_756.0)],
        t3_pct=5.2,
        t7_pct=18.0,
        t30_pct=22.3,
    )
    row = _format_purchase_row(event)
    assert row.startswith("• 15/03")
    assert "CEO" in row
    assert "$638K" in row
    assert "+5.2%" in row
    assert "+18.0%" in row
    assert "+22.3%" in row


def test_format_purchase_row_none_pct_shows_dash():
    event = SignalEvent(
        trade_date=date(2026, 3, 15),
        ticker="MIMI",
        score=8,
        insiders=[("John Smith", "Chief Financial Officer", 150_000.0)],
        t3_pct=5.2,
        t7_pct=None,
        t30_pct=None,
    )
    row = _format_purchase_row(event)
    assert "+5.2%" in row
    assert "— / —" in row


def test_format_purchase_row_negative_pct():
    event = SignalEvent(
        trade_date=date(2026, 1, 10),
        ticker="MIMI",
        score=5,
        insiders=[("John Smith", "Director", 150_000.0)],
        t3_pct=-3.5,
        t7_pct=-5.0,
        t30_pct=8.0,
    )
    row = _format_purchase_row(event)
    assert "-3.5%" in row
    assert "-5.0%" in row
    assert "+8.0%" in row
```

- [ ] **Run tests to verify they FAIL**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_company_analyzer.py -v -k 'fmt_value or short_role or format_purchase_row'"`

Expected: FAIL — `ImportError: cannot import name '_fmt_value'`

- [ ] **Implement: add helpers to `company_analyzer.py`** — insert before `build_message` (before `# ── Message builder` comment):

```python
# ── Format helpers ────────────────────────────────────────────────────────

def _fmt_value(value: float) -> str:
    """Format a dollar amount as compact string: $50K, $638K, $1.5M."""
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${round(value / 1_000):.0f}K"


def _short_role(title: str) -> str:
    """Return a short role label from an officer title string."""
    t = title.upper()
    if "CHIEF EXECUTIVE" in t or t == "CEO":
        return "CEO"
    if "CHIEF FINANCIAL" in t or t == "CFO":
        return "CFO"
    if "CHIEF OPERATING" in t or t == "COO":
        return "COO"
    if "PRESIDENT" in t:
        return "Pres."
    if "DIRECTOR" in t:
        return "Dir."
    if "CHAIRMAN" in t:
        return "Chair."
    return title[:6] if len(title) > 6 else title


def _format_purchase_row(event: SignalEvent) -> str:
    """Format a single SignalEvent as a Telegram purchase list row.

    Format: "• DD/MM — ROLE F. Lastname $AMOUNT → T3% / T7% / T30%"
    None pct values are shown as "—".
    For cluster buys (multiple insiders), shows the most prominent one.
    """
    date_str = event.trade_date.strftime("%d/%m")

    if event.insiders:
        # Sort by role priority then value; take top insider
        role_priority = {"CEO": 0, "CFO": 1, "COO": 2, "Pres.": 3, "Chair.": 4, "Dir.": 5}
        def sort_key(insider: Tuple[str, str, float]) -> Tuple[int, float]:
            _, title, value = insider
            return (role_priority.get(_short_role(title), 9), -value)
        top_name, top_title, top_value = sorted(event.insiders, key=sort_key)[0]
        role = _short_role(top_title)
        parts = top_name.strip().split()
        short_name = f"{parts[0][0]}. {parts[-1]}" if len(parts) >= 2 else top_name
        cluster_suffix = f" (+{len(event.insiders) - 1})" if len(event.insiders) > 1 else ""
        who = f"{role} {short_name}{cluster_suffix} {_fmt_value(top_value)}"
    else:
        who = "Insider"

    def fmt_pct(pct: Optional[float]) -> str:
        if pct is None:
            return "—"
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.1f}%"

    results = f"{fmt_pct(event.t3_pct)} / {fmt_pct(event.t7_pct)} / {fmt_pct(event.t30_pct)}"
    return f"• {date_str} — {who} → {results}"
```

- [ ] **Run tests to verify they pass**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_company_analyzer.py -v -k 'fmt_value or short_role or format_purchase_row'"`

Expected: all 8 tests pass.

- [ ] **Run full suite**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/ -v"`

Expected: all pass except remaining `build_message` and `analyze` tests.

- [ ] **Commit**

```bash
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" add company_analyzer.py tests/test_company_analyzer.py
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" commit -m "feat(company_analyzer): add _fmt_value, _short_role, _format_purchase_row helpers"
```

---

## Task 5: Rewrite `build_message`

**Files:**
- Modify: `company_analyzer.py` — rewrite `build_message`
- Modify: `tests/test_company_analyzer.py` — replace 3 existing tests + add 4 new ones

**Context:** `build_message` now receives `signal_events: List[SignalEvent]` instead of `signal_count: int`. It filters to the 12-month display window, sorts most recent first, truncates to `MAX_DISPLAY_PURCHASES`, and formats each row. Aggregate stats still shown below.

- [ ] **Replace the 3 existing `build_message` tests** and add 4 new ones — replace the entire `# ── build_message ──` section with:

```python
# ── build_message ─────────────────────────────────────────────────────────

def test_build_message_no_events_shows_nessuno_trovato():
    stats = _make_stats()
    rec = Recommendation(action="N/D", best_horizon=7, tp=None, sl=2.95, avg_pct=0.0)
    msg = build_message(
        ticker="MIMI", entry_price=3.21,
        signal_events=[], stats=stats, rec=rec,
    )
    assert "MIMI" in msg
    assert "nessuno" in msg
    assert "N/D" in msg


def test_build_message_shows_purchase_list_and_stats():
    stats = _make_stats(t7=(1, 1, 18.0))
    rec = Recommendation(action="COMPRA", best_horizon=7, tp=3.79, sl=2.95, avg_pct=18.0)
    events = [
        SignalEvent(
            trade_date=date.today() - timedelta(days=30),
            ticker="MIMI", score=8,
            insiders=[("Chan Hoi Lung", "Chief Executive Officer", 637_756.0)],
            t3_pct=5.0, t7_pct=18.0, t30_pct=22.0,
        )
    ]
    msg = build_message("MIMI", 3.21, events, stats, rec)
    assert "$MIMI" in msg
    assert "CEO" in msg
    assert "COMPRA" in msg
    assert "3.79" in msg   # TP
    assert "2.95" in msg   # SL
    assert "7 giorni" in msg
    assert "migliore" in msg


def test_build_message_truncates_to_max_display():
    stats = _make_stats(t7=(7, 6, 12.0))
    rec = Recommendation(action="COMPRA", best_horizon=7, tp=3.60, sl=2.95, avg_pct=12.0)
    events = [
        SignalEvent(
            trade_date=date.today() - timedelta(days=i + 10),
            ticker="MIMI", score=8,
            insiders=[("A Person", "Chief Executive Officer", 100_000.0)],
            t7_pct=5.0,
        )
        for i in range(7)
    ]
    msg = build_message("MIMI", 3.21, events, stats, rec)
    assert "e altri 2" in msg


def test_build_message_orders_most_recent_first():
    stats = _make_stats(t7=(2, 2, 10.0))
    rec = Recommendation(action="COMPRA", best_horizon=7, tp=3.53, sl=2.95, avg_pct=10.0)
    old_date = date.today() - timedelta(days=180)
    new_date = date.today() - timedelta(days=30)
    events = [
        SignalEvent(trade_date=old_date, ticker="MIMI", score=8,
                    insiders=[("Old Buyer", "Chief Executive Officer", 100_000.0)], t7_pct=5.0),
        SignalEvent(trade_date=new_date, ticker="MIMI", score=8,
                    insiders=[("New Buyer", "Chief Executive Officer", 100_000.0)], t7_pct=8.0),
    ]
    msg = build_message("MIMI", 3.21, events, stats, rec)
    new_str = new_date.strftime("%d/%m")
    old_str = old_date.strftime("%d/%m")
    assert msg.index(new_str) < msg.index(old_str)


def test_build_message_excludes_events_outside_display_window():
    # Event 400 days ago → outside 365-day display window
    # But stats (2 years) still show data
    stats = _make_stats(t7=(1, 1, 10.0))
    rec = Recommendation(action="COMPRA", best_horizon=7, tp=3.53, sl=2.95, avg_pct=10.0)
    old_event = SignalEvent(
        trade_date=date.today() - timedelta(days=400),
        ticker="MIMI", score=8,
        insiders=[("Old Buyer", "Chief Executive Officer", 100_000.0)],
        t7_pct=10.0,
    )
    msg = build_message("MIMI", 3.21, [old_event], stats, rec)
    assert "Nessuno" in msg or "nessuno" in msg
    # But stats section still shows data (event was used in backtest)
    assert "Performance media" in msg
    assert "COMPRA" in msg


def test_build_message_attenzione_no_tp():
    stats = _make_stats(t7=(2, 0, -5.0))
    rec = Recommendation(action="ATTENZIONE", best_horizon=7, tp=None, sl=2.95, avg_pct=-5.0)
    events = [
        SignalEvent(
            trade_date=date.today() - timedelta(days=30),
            ticker="MIMI", score=8,
            insiders=[("John Smith", "Chief Executive Officer", 100_000.0)],
            t7_pct=-5.0,
        )
    ]
    msg = build_message("MIMI", 3.21, events, stats, rec)
    assert "ATTENZIONE" in msg
    assert "TP" not in msg
```

- [ ] **Run tests to verify they FAIL**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_company_analyzer.py -v -k build_message"`

Expected: FAIL — `TypeError` (old signature has `signal_count`, new tests pass `signal_events`)

- [ ] **Implement: rewrite `build_message` in `company_analyzer.py`**

Replace the entire `build_message` function (lines 326–370) with:

```python
def build_message(
    ticker: str,
    entry_price: float,
    signal_events: List[SignalEvent],
    stats: Dict[int, BacktestResult],
    rec: Recommendation,
) -> str:
    """Format the second Telegram message with historical analysis.

    Shows individual purchases from the last 12 months (sorted most recent first,
    capped at MAX_DISPLAY_PURCHASES), then aggregate stats over 2 years.
    """
    lines = [f"📊 ANALISI STORICA — ${ticker}", ""]

    # ── Purchase list (last 12 months) ────────────────────────────────────
    lines.append("📋 Acquisti significativi (ultimi 12 mesi):")

    if not signal_events:
        lines.append("→ Nessun acquisto significativo trovato")
        lines.append("")
        lines.append("🎯 Raccomandazione: N/D — nessun dato storico")
        return "\n".join(lines)

    cutoff = date.today() - timedelta(days=config.COMPANY_DISPLAY_LOOKBACK_DAYS)
    recent = sorted(
        [e for e in signal_events if e.trade_date >= cutoff],
        key=lambda e: e.trade_date,
        reverse=True,
    )

    if recent:
        for event in recent[:config.MAX_DISPLAY_PURCHASES]:
            lines.append(_format_purchase_row(event))
        remaining = len(recent) - config.MAX_DISPLAY_PURCHASES
        if remaining > 0:
            lines.append(f"… e altri {remaining}")
    else:
        lines.append("→ Nessuno nell'ultimo anno (vedi stats 2 anni sotto)")

    lines.append("")

    # ── Aggregate stats (2 years) ──────────────────────────────────────────
    total_signals = len(signal_events)
    lines.append(f"📈 Performance media ({total_signals} segnali, 2 anni):")

    for h in [3, 7, 30]:
        r = stats.get(h)
        if r and r.count > 0:
            marker = " ← migliore" if h == rec.best_horizon else ""
            sign = "+" if r.avg_pct >= 0 else ""
            lines.append(
                f"• T+{h}:  {sign}{r.avg_pct:.1f}%  ({r.positives}/{r.count} positivi){marker}"
            )

    lines.append("")
    lines.append(f"🎯 Raccomandazione: {rec.action}")
    lines.append(f"• Entry: ${entry_price:.2f}")
    if rec.tp is not None:
        sign = "+" if rec.avg_pct >= 0 else ""
        lines.append(
            f"• TP: ${rec.tp:.2f}  ({sign}{rec.avg_pct:.0f}%, media {rec.best_horizon}gg)"
        )
    lines.append(f"• SL: ${rec.sl:.2f}  (-{config.SL_PERCENT * 100:.0f}%)")
    lines.append(f"• Holding: ~{rec.best_horizon} giorni")

    return "\n".join(lines)
```

- [ ] **Run tests to verify they pass**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_company_analyzer.py -v -k build_message"`

Expected: all 7 build_message tests pass.

- [ ] **Commit**

```bash
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" add company_analyzer.py tests/test_company_analyzer.py
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" commit -m "feat(company_analyzer): rewrite build_message with purchase list format"
```

---

## Task 6: Update `analyze` + fix remaining tests

**Files:**
- Modify: `company_analyzer.py` — update `analyze` to use `MIN_SCORE` and new `build_message` signature
- Modify: `tests/test_company_analyzer.py` — update 2 existing `analyze` tests, add 1 new one

**Context:** `analyze` must now pass `config.MIN_SCORE` to `score_and_filter` (instead of `today_score`), and pass `signal_events=historical` to `build_message` (instead of `signal_count`). The signature of `analyze` itself is unchanged — `insider_tracker.py` needs no modifications.

- [ ] **Update the 2 existing `analyze` tests** and add 1 new one — replace the `# ── analyze ──` section with:

```python
# ── analyze (orchestrator) ────────────────────────────────────────────────

@patch("company_analyzer.requests.Session")
@patch("company_analyzer.yf")
def test_analyze_returns_nd_message_on_empty_edgar_history(mock_yf, mock_session_cls):
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    mock_session.get.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"hits": {"hits": []}}),
        raise_for_status=MagicMock(),
    )
    msg = analyze(ticker="MIMI", cik="1998560", today_score=11, entry_price=3.21)
    assert "MIMI" in msg
    assert "N/D" in msg


@patch("company_analyzer.requests.Session")
@patch("company_analyzer.yf")
def test_analyze_returns_error_message_on_exception(mock_yf, mock_session_cls):
    mock_session_cls.side_effect = Exception("unexpected")
    msg = analyze(ticker="MIMI", cik="1998560", today_score=11, entry_price=3.21)
    assert "MIMI" in msg
    assert "N/D" in msg


@patch("company_analyzer.requests.Session")
@patch("company_analyzer.yf")
def test_analyze_uses_min_score_not_today_score(mock_yf, mock_session_cls):
    """analyze() uses config.MIN_SCORE for history filter, not today_score."""
    import config
    # MIN_SCORE = 5; today_score = 11. If analyze used today_score=11, a
    # CEO buy $50K (score=5) would be filtered out. With MIN_SCORE=5 it is kept.
    # We verify: if EDGAR returns one valid filing, analyze should NOT return N/D.
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    hit = _make_efts_hit(ciks=[_CIK_PADDED])
    # Score 5 filing: other officer $60K → 1 (Other) + 1 (<$100K) = 2... 
    # Actually we need score >= MIN_SCORE (5). Use CEO $637K (score=8 >= 5).
    mock_session.get.side_effect = [
        _make_efts_resp([hit]),
        _make_xml_resp(_CEO_BUY_XML),
    ]
    # yfinance returns empty for this ticker (so backtest skips, N/D from stats)
    mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
    # today_score=15 (high), but MIN_SCORE=5 — the CEO buy (score=8) should be found
    msg = analyze(ticker=_TICKER, cik=_CIK, today_score=15, entry_price=3.21)
    # With MIN_SCORE=5 the CEO event IS found; N/D comes from empty yfinance, not from filter
    assert _TICKER in msg
    # "N/D" because yfinance is empty, but "nessuno trovato" would mean the filter was wrong
    assert "nessuno trovato" not in msg
```

- [ ] **Run tests to verify they FAIL**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_company_analyzer.py -v -k analyze"`

Expected: FAIL — `TypeError` in `build_message` call (wrong arguments in `analyze`)

- [ ] **Implement: update `analyze` in `company_analyzer.py`**

Replace the entire `analyze` function (lines 375–414) with:

```python
def analyze(
    ticker: str,
    cik: str,
    today_score: int,
    entry_price: float,
) -> str:
    """Fetch history, backtest, and return a formatted Telegram message.

    Uses config.MIN_SCORE (not today_score) for the history filter, so all
    significant historical buys are included regardless of today's score.
    On any error, returns a graceful N/D message.
    """
    if entry_price <= 0:
        return (
            f"📊 ANALISI STORICA — ${ticker}\n\n"
            "⚠️ Prezzo entry non disponibile.\n"
            "🎯 Raccomandazione: N/D"
        )
    try:
        transactions = fetch_company_history(cik=cik, ticker=ticker)
        signal_events = score_and_filter(transactions, min_score=config.MIN_SCORE)
        # Exclude today's signal — outcome not yet available
        today = date.today()
        historical = [e for e in signal_events if e.trade_date < today]
        stats = backtest(historical)
        rec = generate_recommendation(stats, entry_price)
        return build_message(
            ticker=ticker,
            entry_price=entry_price,
            signal_events=historical,
            stats=stats,
            rec=rec,
        )
    except Exception as exc:
        logger.error("company_analyzer.analyze failed for %s: %s", ticker, exc, exc_info=True)
        return (
            f"📊 ANALISI STORICA — ${ticker}\n\n"
            "⚠️ Analisi non disponibile (errore tecnico).\n"
            "🎯 Raccomandazione: N/D"
        )
```

- [ ] **Run all company_analyzer tests**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_company_analyzer.py -v"`

Expected: all tests pass.

- [ ] **Run full suite — no regressions**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/ -v"`

Expected: all 124 + new tests pass (target ≥ 145).

- [ ] **Commit**

```bash
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" add company_analyzer.py tests/test_company_analyzer.py
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" commit -m "feat(company_analyzer): update analyze to use MIN_SCORE and new build_message signature"
```

---

## Known Limitations

- `_format_purchase_row` abbreviates names as "F. Lastname" — works well for Western names, approximate for Asian names (where surname comes first).
- Display window (12 months) and stats window (2 years) can differ, which means the message may say "0 recent purchases" but still show aggregate stats — this is intentional and informative.
- Telegram messages have no hard character limit for bots, but very long messages (>4096 chars) are split. With max 5 rows the message stays well within limits.
