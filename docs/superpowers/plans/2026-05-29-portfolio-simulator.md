# Portfolio Simulator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a paper trading portfolio that automatically buys insider signals (score ≥ 8) with dynamic sizing ($500/$1000/$2000), holds 7 calendar days, and generates an hourly-updated Obsidian markdown with P&L tracking.

**Architecture:** New `portfolio_tracker.py` module handles all portfolio logic (open/close positions, price fetching, markdown generation). `insider_tracker.py` calls `open_position()` after each valid signal. A Task Scheduler job runs `portfolio_tracker.py` hourly to update prices and close expired positions.

**Tech Stack:** Python 3.x, `yfinance` (already installed), `json`, `pathlib`, existing `config.py`

---

## File Map

| File | Action | What changes |
|---|---|---|
| `config.py` | Modify | Add `PORTFOLIO_MIN_SCORE`, `PORTFOLIO_CAPITAL`, `PORTFOLIO_FILE`, `PORTFOLIO_MD` |
| `portfolio_tracker.py` | Create | Full portfolio module |
| `tests/test_portfolio_tracker.py` | Create | Full test suite |
| `insider_tracker.py` | Modify | Call `portfolio_tracker.open_position()` after signal |
| `tests/test_tracker.py` | Modify | 2 tests for new config constants |
| Task Scheduler | Configure | Hourly job for portfolio update |

---

## Task 1: Add constants to `config.py`

**Files:**
- Modify: `config.py`
- Modify: `tests/test_tracker.py`

- [ ] **Write 2 failing tests** — add at the end of `tests/test_tracker.py`:

```python
def test_config_has_portfolio_min_score():
    import config
    assert config.PORTFOLIO_MIN_SCORE == 8

def test_config_has_portfolio_capital():
    import config
    assert config.PORTFOLIO_CAPITAL == 20_000.0
```

- [ ] **Run to confirm RED**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_tracker.py::test_config_has_portfolio_min_score tests/test_tracker.py::test_config_has_portfolio_capital -v"`

Expected: FAIL — AttributeError

- [ ] **Add constants** — append to `config.py` after `MAX_DISPLAY_PURCHASES = 5`:

```python

# Portfolio simulator settings
PORTFOLIO_MIN_SCORE = 8
PORTFOLIO_CAPITAL = 20_000.0
PORTFOLIO_FILE = Path("portfolio.json")
PORTFOLIO_MD = Path(r"C:\Users\corr8\Desktop\obsidian-vault\Insider Project\Portfolio Simulato.md")
```

Also add `from pathlib import Path` at the top of `config.py` if not already present (check line 1 — it currently has no imports; add it as the first line).

- [ ] **Run to confirm GREEN**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_tracker.py -v"`

Expected: all pass (was 18, now 20).

- [ ] **Full suite**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/ -v"`

Expected: 139 → 141 passed.

- [ ] **Commit**

```bash
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" add config.py tests/test_tracker.py
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" commit -m "feat(config): add portfolio simulator constants"
```

---

## Task 2: `portfolio_tracker.py` — data layer

**Files:**
- Create: `portfolio_tracker.py`
- Create: `tests/test_portfolio_tracker.py`

**Context:** `position_size()` maps score to investment amount. `load_portfolio()` / `save_portfolio()` handle the JSON file. `open_position()` records a new position and deducts cash. All functions accept an optional `portfolio_file` path for testability.

- [ ] **Create `tests/test_portfolio_tracker.py`** with 6 failing tests:

```python
"""Tests for portfolio_tracker module."""

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from portfolio_tracker import (
    position_size,
    load_portfolio,
    save_portfolio,
    open_position,
)


def _default_portfolio(tmp_path) -> Path:
    """Write a default portfolio file and return its path."""
    f = tmp_path / "portfolio.json"
    data = {
        "capital_initial": 20000.0,
        "cash": 20000.0,
        "positions": [],
        "closed": [],
    }
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


# ── position_size ─────────────────────────────────────────────────────────

def test_position_size_buono():
    assert position_size(8) == 500.0
    assert position_size(10) == 500.0

def test_position_size_ottimo():
    assert position_size(11) == 1000.0
    assert position_size(13) == 1000.0

def test_position_size_eccellente():
    assert position_size(14) == 2000.0
    assert position_size(21) == 2000.0

def test_position_size_below_min_returns_zero():
    assert position_size(7) == 0.0
    assert position_size(0) == 0.0


# ── load / save ───────────────────────────────────────────────────────────

def test_load_portfolio_returns_default_when_file_missing(tmp_path):
    f = tmp_path / "portfolio.json"
    data = load_portfolio(f)
    assert data["cash"] == 20000.0
    assert data["positions"] == []
    assert data["closed"] == []


# ── open_position ─────────────────────────────────────────────────────────

def test_open_position_adds_position_and_deducts_cash(tmp_path):
    pf = _default_portfolio(tmp_path)
    open_position("NAKA", 17, date(2026, 5, 29), portfolio_file=pf)
    data = json.loads(pf.read_text())
    assert len(data["positions"]) == 1
    assert data["positions"][0]["ticker"] == "NAKA"
    assert data["positions"][0]["invested"] == 2000.0
    assert data["positions"][0]["entry_price"] is None
    assert data["positions"][0]["exit_date_target"] == "2026-06-05"
    assert data["cash"] == 18000.0


def test_open_position_ignores_low_score(tmp_path):
    pf = _default_portfolio(tmp_path)
    open_position("WEAK", 5, date(2026, 5, 29), portfolio_file=pf)
    data = json.loads(pf.read_text())
    assert data["positions"] == []
    assert data["cash"] == 20000.0
```

- [ ] **Run to confirm RED**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_portfolio_tracker.py -v"`

Expected: FAIL — `ModuleNotFoundError: No module named 'portfolio_tracker'`

- [ ] **Create `portfolio_tracker.py`** in the project root:

```python
"""
Portfolio Simulator for InsiderTracker.

Tracks a paper trading portfolio of $20,000 USD that buys insider signals
with score >= PORTFOLIO_MIN_SCORE, holds 7 calendar days, sells at market open.

Run as script (hourly Task Scheduler job) to update prices and close positions:
  python portfolio_tracker.py
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yfinance as yf

import config

logger = logging.getLogger(__name__)

_BALI_TZ = timezone(timedelta(hours=8))  # WITA = UTC+8


# ── Sizing ────────────────────────────────────────────────────────────────

def position_size(score: int) -> float:
    """Return investment amount in USD based on signal score.

    score 8–10  → $500  (Buono)
    score 11–13 → $1000 (Ottimo)
    score ≥ 14  → $2000 (Eccellente)
    score < 8   → $0    (do not invest)
    """
    if score >= 14:
        return 2000.0
    if score >= 11:
        return 1000.0
    if score >= 8:
        return 500.0
    return 0.0


# ── Data layer ────────────────────────────────────────────────────────────

def load_portfolio(portfolio_file: Optional[Path] = None) -> dict:
    """Load portfolio from JSON, or return default structure if file missing."""
    f = portfolio_file or config.PORTFOLIO_FILE
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {
        "capital_initial": config.PORTFOLIO_CAPITAL,
        "cash": config.PORTFOLIO_CAPITAL,
        "positions": [],
        "closed": [],
    }


def save_portfolio(data: dict, portfolio_file: Optional[Path] = None) -> None:
    """Persist portfolio data to JSON file."""
    f = portfolio_file or config.PORTFOLIO_FILE
    f.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def open_position(
    ticker: str,
    score: int,
    signal_date: date,
    portfolio_file: Optional[Path] = None,
) -> None:
    """Record a new position when a signal fires.

    Does nothing if score < PORTFOLIO_MIN_SCORE.
    entry_price is None until update() fills it after US market opens (15:30 IT).
    """
    size = position_size(score)
    if size == 0:
        return
    data = load_portfolio(portfolio_file)
    data["positions"].append({
        "ticker": ticker,
        "score": score,
        "signal_date": signal_date.isoformat(),
        "entry_price": None,
        "shares": None,
        "invested": size,
        "exit_date_target": (signal_date + timedelta(days=7)).isoformat(),
        "current_price": None,
        "unrealized_pnl": None,
    })
    data["cash"] = round(data["cash"] - size, 2)
    save_portfolio(data, portfolio_file)
```

- [ ] **Run to confirm GREEN**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_portfolio_tracker.py -v"`

Expected: all 8 tests pass.

- [ ] **Full suite**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/ -v"`

Expected: 141 → 149 passed.

- [ ] **Commit**

```bash
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" add portfolio_tracker.py tests/test_portfolio_tracker.py
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" commit -m "feat(portfolio): add data layer — position_size, load/save, open_position"
```

---

## Task 3: Price functions + `update()`

**Files:**
- Modify: `portfolio_tracker.py` — add `get_open_price()`, `get_current_price()`, `_score_label()`, `update()`
- Modify: `tests/test_portfolio_tracker.py` — add 6 tests

**Context:** `get_open_price()` fetches the US market opening price for a specific date. `update()` fills entry prices, closes expired positions, refreshes current prices. Both accept optional path params for testability.

- [ ] **Add 6 tests** to `tests/test_portfolio_tracker.py`:

First update the import at the top to include the new functions:
```python
from portfolio_tracker import (
    position_size,
    load_portfolio,
    save_portfolio,
    open_position,
    get_open_price,
    get_current_price,
    update,
)
```

Then add these tests at the end of the file:

```python
# ── get_open_price ────────────────────────────────────────────────────────

@patch("portfolio_tracker.yf")
def test_get_open_price_returns_open(mock_yf):
    import pandas as pd
    hist = pd.DataFrame(
        {"Open": [5.42], "Close": [5.60]},
        index=[pd.Timestamp("2026-05-29")]
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    price = get_open_price("NAKA", date(2026, 5, 29))
    assert price == pytest.approx(5.42)


@patch("portfolio_tracker.yf")
def test_get_open_price_returns_none_on_empty(mock_yf):
    import pandas as pd
    mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
    assert get_open_price("NAKA", date(2026, 5, 29)) is None


# ── update ────────────────────────────────────────────────────────────────

@patch("portfolio_tracker.get_current_price")
@patch("portfolio_tracker.get_open_price")
def test_update_fills_entry_price(mock_open, mock_curr, tmp_path):
    pf = tmp_path / "portfolio.json"
    data = {
        "capital_initial": 20000.0, "cash": 18000.0,
        "positions": [{
            "ticker": "NAKA", "score": 17,
            "signal_date": "2026-05-29",
            "entry_price": None, "shares": None,
            "invested": 2000.0, "exit_date_target": "2026-06-05",
            "current_price": None, "unrealized_pnl": None,
        }],
        "closed": [],
    }
    pf.write_text(json.dumps(data), encoding="utf-8")
    mock_open.return_value = 5.42
    mock_curr.return_value = 5.60
    update(portfolio_file=pf, md_path=tmp_path / "out.md")
    result = json.loads(pf.read_text())
    assert result["positions"][0]["entry_price"] == pytest.approx(5.42, abs=0.001)
    assert result["positions"][0]["shares"] == pytest.approx(2000.0 / 5.42, abs=0.01)


@patch("portfolio_tracker.get_current_price")
@patch("portfolio_tracker.get_open_price")
def test_update_closes_expired_position(mock_open, mock_curr, tmp_path):
    pf = tmp_path / "portfolio.json"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    data = {
        "capital_initial": 20000.0, "cash": 18000.0,
        "positions": [{
            "ticker": "NAKA", "score": 17,
            "signal_date": "2026-05-22",
            "entry_price": 5.42, "shares": 369.0,
            "invested": 2000.0,
            "exit_date_target": yesterday,
            "current_price": 5.60, "unrealized_pnl": 66.42,
        }],
        "closed": [],
    }
    pf.write_text(json.dumps(data), encoding="utf-8")
    mock_open.return_value = 5.80   # exit at open
    mock_curr.return_value = 5.80
    update(portfolio_file=pf, md_path=tmp_path / "out.md")
    result = json.loads(pf.read_text())
    assert result["positions"] == []
    assert len(result["closed"]) == 1
    assert result["closed"][0]["ticker"] == "NAKA"
    assert result["closed"][0]["pnl"] == pytest.approx((5.80 - 5.42) * 369.0, abs=0.01)
    assert result["cash"] > 18000.0  # cash returned + profit


@patch("portfolio_tracker.get_current_price")
@patch("portfolio_tracker.get_open_price")
def test_update_does_not_close_if_no_exit_price(mock_open, mock_curr, tmp_path):
    pf = tmp_path / "portfolio.json"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    data = {
        "capital_initial": 20000.0, "cash": 18000.0,
        "positions": [{
            "ticker": "NAKA", "score": 17,
            "signal_date": "2026-05-22", "entry_price": 5.42, "shares": 369.0,
            "invested": 2000.0, "exit_date_target": yesterday,
            "current_price": None, "unrealized_pnl": None,
        }],
        "closed": [],
    }
    pf.write_text(json.dumps(data), encoding="utf-8")
    mock_open.return_value = None
    mock_curr.return_value = None
    update(portfolio_file=pf, md_path=tmp_path / "out.md")
    result = json.loads(pf.read_text())
    # Can't close without price — position stays open
    assert len(result["positions"]) == 1
    assert result["closed"] == []
```

- [ ] **Run to confirm RED**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_portfolio_tracker.py -v -k 'open_price or update'"`

Expected: FAIL — ImportError (functions not yet defined)

- [ ] **Add functions to `portfolio_tracker.py`** — append after `open_position()`:

```python

# ── Price fetching ────────────────────────────────────────────────────────

def get_open_price(ticker: str, target_date: date) -> Optional[float]:
    """Return the US market opening price for ticker on target_date.

    Returns None if data not yet available (market not yet open)
    or if target_date is a non-trading day.
    """
    try:
        end = target_date + timedelta(days=1)
        hist = yf.Ticker(ticker).history(
            start=target_date.isoformat(),
            end=end.isoformat(),
            interval="1d",
            auto_adjust=True,
        )
        if not hist.empty and "Open" in hist.columns:
            return float(hist["Open"].iloc[0])
    except Exception as exc:
        logger.warning("yfinance open price error for %s on %s: %s", ticker, target_date, exc)
    return None


def get_current_price(ticker: str) -> Optional[float]:
    """Return the latest available closing price for ticker."""
    try:
        hist = yf.Ticker(ticker).history(period="1d", auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as exc:
        logger.warning("yfinance current price error for %s: %s", ticker, exc)
    return None


def _score_label(score: int) -> str:
    """Return emoji label for a score."""
    if score >= 14:
        return "🔥"
    if score >= 11:
        return "🟢"
    if score >= 8:
        return "🟡"
    return "🔴"


# ── Update (main job) ─────────────────────────────────────────────────────

def update(
    portfolio_file: Optional[Path] = None,
    md_path: Optional[Path] = None,
) -> None:
    """Fill entry prices, close expired positions, refresh P&L, regenerate markdown.

    Called hourly by Task Scheduler. First run after 15:30 IT fills entry prices.
    """
    data = load_portfolio(portfolio_file)
    today = date.today()
    still_open = []

    for pos in data["positions"]:
        ticker = pos["ticker"]
        signal_date = date.fromisoformat(pos["signal_date"])
        exit_target = date.fromisoformat(pos["exit_date_target"])

        # Fill entry price when US market has opened (after 15:30 IT)
        if pos["entry_price"] is None:
            open_px = get_open_price(ticker, signal_date)
            if open_px is not None:
                pos["entry_price"] = round(open_px, 4)
                pos["shares"] = round(pos["invested"] / open_px, 4)

        # Close expired positions (exit_date_target <= today)
        if exit_target <= today:
            exit_px = get_open_price(ticker, exit_target) or get_current_price(ticker)
            if exit_px is not None and pos["entry_price"] is not None:
                pnl = round((exit_px - pos["entry_price"]) * pos["shares"], 2)
                pnl_pct = round(
                    (exit_px - pos["entry_price"]) / pos["entry_price"] * 100, 2
                )
                data["closed"].append({
                    "ticker": ticker,
                    "score": pos["score"],
                    "signal_date": pos["signal_date"],
                    "entry_price": pos["entry_price"],
                    "shares": pos["shares"],
                    "invested": pos["invested"],
                    "exit_price": round(exit_px, 4),
                    "exit_date": today.isoformat(),
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                })
                data["cash"] = round(data["cash"] + pos["invested"] + pnl, 2)
                continue  # position closed, don't add to still_open
            else:
                still_open.append(pos)
                continue

        # Update current price + unrealized P&L
        curr = get_current_price(ticker)
        if curr is not None:
            pos["current_price"] = round(curr, 4)
            if pos["entry_price"] is not None and pos["shares"] is not None:
                pos["unrealized_pnl"] = round(
                    (curr - pos["entry_price"]) * pos["shares"], 2
                )
        still_open.append(pos)

    data["positions"] = still_open
    save_portfolio(data, portfolio_file)
    generate_markdown(data, md_path)
```

- [ ] **Confirm GREEN**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_portfolio_tracker.py -v"`

Expected: all tests pass (including new ones).

- [ ] **Full suite**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/ -v"`

Expected: all pass.

- [ ] **Commit**

```bash
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" add portfolio_tracker.py tests/test_portfolio_tracker.py
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" commit -m "feat(portfolio): add get_open_price, get_current_price, update"
```

---

## Task 4: `generate_markdown()`

**Files:**
- Modify: `portfolio_tracker.py` — add `generate_markdown()`
- Modify: `tests/test_portfolio_tracker.py` — add 4 tests

**Context:** Writes `Portfolio Simulato.md` to the Obsidian vault with summary table, open positions, and closed trade history. Accepts optional path for testability.

- [ ] **Add 4 tests** to `tests/test_portfolio_tracker.py`:

First update the import to add `generate_markdown`:
```python
from portfolio_tracker import (
    position_size, load_portfolio, save_portfolio, open_position,
    get_open_price, get_current_price, update, generate_markdown,
)
```

Then add tests at the end:

```python
# ── generate_markdown ─────────────────────────────────────────────────────

def test_generate_markdown_creates_file(tmp_path):
    data = {
        "capital_initial": 20000.0, "cash": 20000.0,
        "positions": [], "closed": [],
    }
    out = tmp_path / "Portfolio Simulato.md"
    generate_markdown(data, md_path=out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "Portfolio Simulato" in content
    assert "$20,000" in content


def test_generate_markdown_shows_open_position(tmp_path):
    data = {
        "capital_initial": 20000.0, "cash": 18000.0,
        "positions": [{
            "ticker": "NAKA", "score": 17,
            "signal_date": "2026-05-29",
            "entry_price": 5.42, "shares": 369.0,
            "invested": 2000.0, "exit_date_target": "2026-06-05",
            "current_price": 5.60, "unrealized_pnl": 66.42,
        }],
        "closed": [],
    }
    out = tmp_path / "out.md"
    generate_markdown(data, md_path=out)
    content = out.read_text(encoding="utf-8")
    assert "NAKA" in content
    assert "5.42" in content
    assert "5.60" in content
    assert "05/06" in content


def test_generate_markdown_shows_closed_trade(tmp_path):
    data = {
        "capital_initial": 20000.0, "cash": 20016.0,
        "positions": [],
        "closed": [{
            "ticker": "PSEC", "score": 6,
            "signal_date": "2026-05-27",
            "entry_price": 5.21, "shares": 96.0,
            "invested": 500.0, "exit_price": 5.38,
            "exit_date": "2026-06-03", "pnl": 16.32, "pnl_pct": 3.26,
        }],
    }
    out = tmp_path / "out.md"
    generate_markdown(data, md_path=out)
    content = out.read_text(encoding="utf-8")
    assert "PSEC" in content
    assert "5.21" in content
    assert "5.38" in content
    assert "+3.3%" in content or "+3.26%" in content or "3.3" in content


def test_generate_markdown_win_rate(tmp_path):
    data = {
        "capital_initial": 20000.0, "cash": 20000.0,
        "positions": [],
        "closed": [
            {"ticker": "A", "score": 8, "signal_date": "2026-05-20",
             "entry_price": 10.0, "shares": 50.0, "invested": 500.0,
             "exit_price": 11.0, "exit_date": "2026-05-27", "pnl": 50.0, "pnl_pct": 10.0},
            {"ticker": "B", "score": 8, "signal_date": "2026-05-21",
             "entry_price": 10.0, "shares": 50.0, "invested": 500.0,
             "exit_price": 9.5, "exit_date": "2026-05-28", "pnl": -25.0, "pnl_pct": -5.0},
        ],
    }
    out = tmp_path / "out.md"
    generate_markdown(data, md_path=out)
    content = out.read_text(encoding="utf-8")
    assert "50%" in content      # 1W / 2 = 50% win rate
    assert "1W / 1L" in content
```

- [ ] **Run to confirm RED**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_portfolio_tracker.py -v -k generate_markdown"`

Expected: FAIL — ImportError

- [ ] **Add `generate_markdown()` to `portfolio_tracker.py`** — append at the end (before `if __name__ == "__main__":`):

```python

# ── Markdown generation ───────────────────────────────────────────────────

def generate_markdown(
    data: Optional[dict] = None,
    md_path: Optional[Path] = None,
) -> None:
    """Write Portfolio Simulato.md with current portfolio state."""
    if data is None:
        data = load_portfolio()

    out = md_path or config.PORTFOLIO_MD
    now_str = datetime.now(_BALI_TZ).strftime("%d/%m/%Y %H:%M (Bali)")

    positions = data.get("positions", [])
    closed = data.get("closed", [])
    capital = data["capital_initial"]
    cash = data["cash"]

    position_value = sum(
        (p.get("current_price") or 0) * (p.get("shares") or 0) for p in positions
    )
    unrealized_total = sum(
        p["unrealized_pnl"] for p in positions if p.get("unrealized_pnl") is not None
    )
    realized_total = sum(c["pnl"] for c in closed)
    equity = round(cash + position_value, 2)

    wins = sum(1 for c in closed if c["pnl"] > 0)
    losses = sum(1 for c in closed if c["pnl"] <= 0)
    total_closed = len(closed)
    win_rate = f"{wins / total_closed * 100:.0f}%" if total_closed > 0 else "—"

    def signed(v, fmt=".0f"):
        if v is None:
            return "—"
        sign = "+" if v >= 0 else ""
        return f"{sign}${abs(v):{fmt}}"

    lines = [
        "# Portfolio Simulato — Insider Tracker",
        f"*Aggiornato: {now_str}*",
        "",
        "## Riepilogo",
        "| Voce | Valore |",
        "|---|---|",
        f"| Capitale iniziale | ${capital:,.0f} |",
        f"| Cash disponibile | ${cash:,.0f} |",
        f"| Valore posizioni | ${position_value:,.0f} |",
        f"| **Equity totale** | **${equity:,.0f}** |",
        f"| P&L non realizzato | {signed(unrealized_total)} |",
        f"| P&L realizzato | {signed(realized_total)} |",
        f"| Trade chiusi | {total_closed} ({wins}W / {losses}L) |",
        f"| Win Rate | {win_rate} |",
        "",
        "## Posizioni aperte",
    ]

    if not positions:
        lines.append("*Nessuna posizione aperta.*")
    else:
        lines.append("| Ticker | Score | Label | Entry | Prezzo | Investito | P&L | Scadenza |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for p in sorted(positions, key=lambda x: x["signal_date"], reverse=True):
            entry = f"${p['entry_price']:.2f}" if p["entry_price"] else "—"
            curr = f"${p['current_price']:.2f}" if p.get("current_price") else "—"
            upnl = p.get("unrealized_pnl")
            upnl_str = signed(upnl) if upnl is not None else "—"
            exit_dt = date.fromisoformat(p["exit_date_target"]).strftime("%d/%m")
            lines.append(
                f"| {p['ticker']} | {p['score']} | {_score_label(p['score'])} | "
                f"{entry} | {curr} | ${p['invested']:,.0f} | {upnl_str} | {exit_dt} |"
            )

    lines += ["", "## Storico trade chiusi"]

    if not closed:
        lines.append("*Nessun trade ancora chiuso.*")
    else:
        lines.append("| Data | Ticker | Score | Entry | Uscita | Investito | P&L | % |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for c in reversed(closed):
            exit_dt = date.fromisoformat(c["exit_date"]).strftime("%d/%m")
            sign_p = "+" if c["pnl"] >= 0 else ""
            sign_pct = "+" if c["pnl_pct"] >= 0 else ""
            lines.append(
                f"| {exit_dt} | {c['ticker']} | {c['score']} | "
                f"${c['entry_price']:.2f} | ${c['exit_price']:.2f} | "
                f"${c['invested']:,.0f} | {sign_p}${abs(c['pnl']):.0f} | "
                f"{sign_pct}{c['pnl_pct']:.1f}% |"
            )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    update()
```

- [ ] **Confirm GREEN**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_portfolio_tracker.py -v"`

Expected: all tests pass.

- [ ] **Full suite**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/ -v"`

Expected: all pass.

- [ ] **Commit**

```bash
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" add portfolio_tracker.py tests/test_portfolio_tracker.py
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" commit -m "feat(portfolio): add generate_markdown"
```

---

## Task 5: Integrate into `insider_tracker.py`

**Files:**
- Modify: `insider_tracker.py` — import `portfolio_tracker`, call `open_position()` after signal
- Modify: `tests/test_tracker.py` — add 2 tests

**Context:** `open_position()` is called inside the existing try/except block after `save_last_seen()`. If it fails, it logs the error but does not interrupt the main flow.

- [ ] **Add 1 failing test** to `tests/test_tracker.py`:

```python
@patch("insider_tracker.portfolio_tracker.open_position")
@patch("insider_tracker.company_analyzer.analyze", return_value="msg")
@patch("insider_tracker.send_analysis", return_value=True)
@patch("insider_tracker.get_current_price", return_value=5.0)
@patch("insider_tracker.send_signal", return_value=True)
@patch("insider_tracker.score_all")
@patch("insider_tracker._fetch_all", return_value=[])
@patch("insider_tracker.is_weekday", return_value=True)
@patch("insider_tracker.load_last_seen", return_value={})
@patch("insider_tracker.save_last_seen")
def test_main_calls_open_position_when_signal_sent(
    mock_save, mock_last_seen, mock_weekday, mock_fetch,
    mock_score, mock_send, mock_curr, mock_send_analysis,
    mock_analyze, mock_open_pos
):
    import config
    mock_score.return_value = [make_signal("NAKA", config.PORTFOLIO_MIN_SCORE + 1)]
    with patch.dict("os.environ", {"TELEGRAM_TOKEN": "T", "TELEGRAM_CHAT_ID": "C"}):
        from insider_tracker import main
        main()
    mock_open_pos.assert_called_once()
```

- [ ] **Run to confirm RED**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/test_tracker.py -v -k open_position"`

Expected: FAIL — `portfolio_tracker` not imported in insider_tracker

- [ ] **Add import and call to `insider_tracker.py`**

Add `import portfolio_tracker` after `import company_analyzer` (around line 25):
```python
import portfolio_tracker
```

In `main()`, after `save_last_seen(last_seen)` (line 139), add inside the existing `try` block:

Replace:
```python
            save_last_seen(last_seen)
            try:
                cik = top.transactions[0].cik if top.transactions else ""
```

With:
```python
            save_last_seen(last_seen)
            try:
                portfolio_tracker.open_position(top.ticker, top.score, date.today())
            except Exception as exc:
                logger.error("portfolio_tracker failed for %s: %s", top.ticker, exc, exc_info=True)
            try:
                cik = top.transactions[0].cik if top.transactions else ""
```

- [ ] **Confirm GREEN**

Run: `powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/ -v"`

Expected: all pass.

- [ ] **Commit**

```bash
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" add insider_tracker.py tests/test_tracker.py
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" commit -m "feat(tracker): call portfolio_tracker.open_position after each valid signal"
```

---

## Task 6: Initial `portfolio.json` + Task Scheduler

**Files:**
- Create: `portfolio.json`
- Configure: Task Scheduler (hourly job)

- [ ] **Create initial `portfolio.json`**

Run: `powershell -Command "Set-Content -Path 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\portfolio.json' -Value '{\"capital_initial\": 20000.0, \"cash\": 20000.0, \"positions\": [], \"closed\": []}' -Encoding UTF8"`

- [ ] **Test the script runs correctly**

Run: `powershell -Command "Set-Location 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker'; & '.\venv\Scripts\python.exe' portfolio_tracker.py"`

Expected: runs without errors, creates `Insider Project/Portfolio Simulato.md` in the Obsidian vault.

- [ ] **Configure Task Scheduler — hourly job**

Run (adjust `/RU` username if needed — same user as the existing InsiderTracker task):

```powershell
schtasks /Create /TN "InsiderTracker_PortfolioUpdate" /TR "\"C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe\" \"C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\portfolio_tracker.py\"" /SC HOURLY /MO 1 /D MON,TUE,WED,THU,FRI /F
```

Note: runs every 1 hour (`/MO 1`) on weekdays. Outside market hours yfinance returns last known prices — harmless.

- [ ] **Verify Task Scheduler entry**

Run: `schtasks /Query /TN "InsiderTracker_PortfolioUpdate" /FO LIST`

Expected: task listed, next run time shown.

- [ ] **Commit**

```bash
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" add portfolio.json
git -C "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker" commit -m "feat(portfolio): add initial portfolio.json"
```

---

## Verifica finale

Dopo tutti i task, esegui:

```powershell
powershell -Command "& 'C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker\venv\Scripts\python.exe' -m pytest tests/ -v"
```

Expected: tutti i test passano (≥ 155).

Verifica manuale: apri `C:\Users\corr8\Desktop\obsidian-vault\Insider Project\Portfolio Simulato.md` in Obsidian — deve mostrare il riepilogo con $20,000 e nessuna posizione aperta.
