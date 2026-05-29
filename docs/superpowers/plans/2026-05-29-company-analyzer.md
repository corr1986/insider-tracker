# Company Analyzer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After each daily signal, send a second Telegram message showing historical insider purchase performance for the specific company, with a COMPRA/ATTENZIONE/N/D recommendation, TP, SL, and holding period.

**Architecture:** New `company_analyzer.py` fetches historical Form 4 data from EDGAR EFTS for the signaled ticker, re-scores with existing `scorer.py`, backtests price returns at T+3/T+7/T+30 via `yfinance`, and generates a recommendation. `insider_tracker.py` calls it after `send_signal()` and sends the result via `notifier.send_analysis()`.

**Tech Stack:** Python 3.x, `yfinance>=0.2.50` (new), `requests`, `pandas` (pulled in by yfinance), existing `scraper.py` / `scorer.py` / `config.py`

---

## File Map

| File | Action | What changes |
|---|---|---|
| `scraper.py` | Modify | Add `cik: str = ""` to `InsiderTransaction`; populate in `fetch_all_edgar_transactions` |
| `config.py` | Modify | Add `COMPANY_HISTORY_LOOKBACK_DAYS = 730`, `SL_PERCENT = 0.08` |
| `notifier.py` | Modify | Add `send_analysis(message, token, chat_id) -> bool` |
| `company_analyzer.py` | Create | Full new module: history fetch, scoring, backtest, recommendation, message |
| `insider_tracker.py` | Modify | Add `get_current_price()`, call `analyze()` + `send_analysis()` after signal |
| `tests/test_company_analyzer.py` | Create | Full test suite for new module |
| `tests/test_tracker.py` | Modify | Add tests for `get_current_price()` and new integration path |
| `requirements.txt` | Modify | Add `yfinance>=0.2.50` |

---

## Task 1: Add `cik` field to `InsiderTransaction`

**Files:**
- Modify: `scraper.py`
- Modify: `tests/test_scraper.py`

**Context:** `InsiderTransaction` currently has 6 fields (ticker, company, insider_name, title, value, trade_date). We need to add `cik: str = ""` (7th, with default so existing tests are unaffected). The issuer CIK is already available in the EFTS response as `filing["ciks"][-1]` (EDGAR convention: last CIK = issuer). This CIK is needed by `company_analyzer` to query EDGAR for the company's history.

- [ ] **Write the failing test** in `tests/test_scraper.py`

Add at the end of the file:

```python
# ── cik field ─────────────────────────────────────────────────────────────

@patch("scraper.requests.Session")
def test_fetch_all_populates_cik_from_issuer(mock_session_cls):
    """InsiderTransaction.cik is populated from the last element in ciks (issuer)."""
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    efts_data = _make_efts_data(ciks=[_OWNER_CIK, _ISSUER_CIK])
    xml = _make_form4_xml(ticker="AAPL", shares="100", price="500.00")
    mock_session.get.side_effect = [
        _make_json_resp(efts_data),
        _make_xml_resp(xml),
    ]
    results = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)
    assert len(results) == 1
    assert results[0].cik == _ISSUER_CIK.lstrip("0")


def test_insider_transaction_cik_defaults_to_empty_string():
    """InsiderTransaction can be created without cik (backward-compatible)."""
    from datetime import date
    t = InsiderTransaction("AAPL", "Apple Inc", "Tim Cook", "CEO", 100_000, date(2026, 1, 1))
    assert t.cik == ""
```

- [ ] **Run test to verify it fails**

```
cd "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker"
venv\Scripts\activate && pytest tests/test_scraper.py::test_fetch_all_populates_cik_from_issuer tests/test_scraper.py::test_insider_transaction_cik_defaults_to_empty_string -v
```

Expected: `FAILED` — `InsiderTransaction.__init__() takes 7 positional arguments` or `AttributeError: cik`

- [ ] **Implement: add `cik` field to `InsiderTransaction` in `scraper.py`**

In `scraper.py`, change the dataclass from:
```python
@dataclass
class InsiderTransaction:
    """A single insider purchase transaction parsed from a Form 4 filing."""

    ticker: str
    company: str
    insider_name: str
    title: str
    value: float          # USD (shares × price per share)
    trade_date: Optional[date]
```
to:
```python
@dataclass
class InsiderTransaction:
    """A single insider purchase transaction parsed from a Form 4 filing."""

    ticker: str
    company: str
    insider_name: str
    title: str
    value: float          # USD (shares × price per share)
    trade_date: Optional[date]
    cik: str = ""         # issuer CIK (company whose securities are being reported)
```

- [ ] **Implement: populate `cik` in `fetch_all_edgar_transactions` in `scraper.py`**

Find the block inside `fetch_all_edgar_transactions` where `InsiderTransaction` is created (around line 352) and change:
```python
                all_txns.append(InsiderTransaction(
                    ticker=t["ticker"],
                    company=t["company"],
                    insider_name=t["insider_name"],
                    title=t["title"],
                    value=t["value"],
                    trade_date=t["trade_date"],
                ))
```
to:
```python
                all_txns.append(InsiderTransaction(
                    ticker=t["ticker"],
                    company=t["company"],
                    insider_name=t["insider_name"],
                    title=t["title"],
                    value=t["value"],
                    trade_date=t["trade_date"],
                    cik=filing["ciks"][-1].lstrip("0") if filing["ciks"] else "",
                ))
```

- [ ] **Run tests to verify they pass**

```
pytest tests/test_scraper.py -v
```

Expected: all scraper tests pass (existing tests unaffected because cik has a default).

- [ ] **Commit**

```
git add scraper.py tests/test_scraper.py
git commit -m "feat(scraper): add cik field to InsiderTransaction"
```

---

## Task 2: Add constants to `config.py`

**Files:**
- Modify: `config.py`

**Context:** `COMPANY_HISTORY_LOOKBACK_DAYS` controls how far back we scan EDGAR for historical buys (2 years = 730 days). `SL_PERCENT` is the fixed stop-loss percentage (8%) applied to every recommendation.

- [ ] **Write the failing test** — add to `tests/test_tracker.py` (uses config already):

```python
def test_config_has_company_history_lookback_days():
    import config
    assert config.COMPANY_HISTORY_LOOKBACK_DAYS == 730

def test_config_has_sl_percent():
    import config
    assert config.SL_PERCENT == 0.08
```

- [ ] **Run test to verify it fails**

```
pytest tests/test_tracker.py::test_config_has_company_history_lookback_days tests/test_tracker.py::test_config_has_sl_percent -v
```

Expected: `FAILED` — `AttributeError: module 'config' has no attribute 'COMPANY_HISTORY_LOOKBACK_DAYS'`

- [ ] **Implement: add constants at the bottom of `config.py`**

```python
# Company analyzer — historical backtest settings
COMPANY_HISTORY_LOOKBACK_DAYS = 730   # days to look back for historical insider buys
SL_PERCENT = 0.08                      # fixed stop-loss as a fraction (8%)
```

- [ ] **Run tests to verify they pass**

```
pytest tests/test_tracker.py -v
```

Expected: all tracker tests pass.

- [ ] **Commit**

```
git add config.py tests/test_tracker.py
git commit -m "feat(config): add COMPANY_HISTORY_LOOKBACK_DAYS and SL_PERCENT"
```

---

## Task 3: Add `send_analysis()` to `notifier.py`

**Files:**
- Modify: `notifier.py`
- Modify: `tests/test_notifier.py`

**Context:** The second Telegram message is a plain formatted string — no `TickerSignal` needed, just send it as-is via the existing `_send_telegram` helper.

- [ ] **Write the failing tests** — add to `tests/test_notifier.py`:

```python
from notifier import send_analysis

@patch("notifier.requests.post")
def test_send_analysis_calls_telegram_api(mock_post):
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())
    result = send_analysis("📊 test message", token="TOKEN", chat_id="CHAT")
    assert result is True
    assert "api.telegram.org" in mock_post.call_args[0][0]

@patch("notifier.requests.post")
def test_send_analysis_sends_correct_text(mock_post):
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())
    send_analysis("📊 ANALISI STORICA — $MIMI", token="TOKEN", chat_id="CHAT")
    payload = mock_post.call_args[1]["json"]
    assert payload["text"] == "📊 ANALISI STORICA — $MIMI"

@patch("notifier.requests.post")
def test_send_analysis_returns_false_on_network_error(mock_post):
    mock_post.side_effect = req.RequestException("connection failed")
    assert send_analysis("test", token="TOKEN", chat_id="CHAT") is False
```

- [ ] **Run tests to verify they fail**

```
pytest tests/test_notifier.py::test_send_analysis_calls_telegram_api tests/test_notifier.py::test_send_analysis_sends_correct_text tests/test_notifier.py::test_send_analysis_returns_false_on_network_error -v
```

Expected: `FAILED` — `ImportError: cannot import name 'send_analysis'`

- [ ] **Implement: add `send_analysis` at the end of `notifier.py`**

```python
def send_analysis(message: str, token: str, chat_id: str) -> bool:
    """Send a company analysis message to Telegram.

    Returns True on success, False on network/HTTP error.
    """
    return _send_telegram(message, token, chat_id)
```

- [ ] **Run tests to verify they pass**

```
pytest tests/test_notifier.py -v
```

Expected: all notifier tests pass.

- [ ] **Commit**

```
git add notifier.py tests/test_notifier.py
git commit -m "feat(notifier): add send_analysis function"
```

---

## Task 4: `company_analyzer.py` — module scaffold + `fetch_company_history()` + `score_and_filter()`

**Files:**
- Create: `company_analyzer.py`
- Create: `tests/test_company_analyzer.py`

**Context:** `fetch_company_history` queries EDGAR EFTS with `q=TICKER` (full-text search for the ticker symbol in Form 4 filings) and filters client-side by issuer CIK. It reuses `_xml_urls` and `_parse_form4_xml` from `scraper.py` (intentional package-internal reuse). `score_and_filter` groups transactions by trade_date and re-scores each date's cluster using existing `score_all` from `scorer.py`.

**Note on EDGAR query:** The `q="{ticker}"` parameter performs a quoted full-text search — it finds Form 4 filings whose XML mentions the ticker symbol. The CIK filter client-side removes false positives. Size is capped at 200 (sufficient for small/mid-cap companies over 2 years).

- [ ] **Write the failing tests** — create `tests/test_company_analyzer.py`:

```python
"""Tests for company_analyzer module."""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from scraper import InsiderTransaction
from company_analyzer import fetch_company_history, score_and_filter


# ── Shared helpers ────────────────────────────────────────────────────────

_TICKER = "MIMI"
_CIK = "1998560"
_CIK_PADDED = "0001998560"
_OTHER_CIK = "0000111111"


def _make_tx(
    ticker=_TICKER,
    insider="Chan Hoi Lung",
    title="Chief Executive Officer",
    value=637_756.0,
    trade_date=date(2026, 1, 10),
    cik=_CIK,
) -> InsiderTransaction:
    return InsiderTransaction(
        ticker=ticker,
        company="Mint Incorporation Limited",
        insider_name=insider,
        title=title,
        value=value,
        trade_date=trade_date,
        cik=cik,
    )


def _make_efts_hit(ciks, accession="0001234567-26-111111"):
    return {
        "_id": f"{accession}:form4.xml",
        "_source": {
            "adsh": accession,
            "ciks": ciks,
            "file_date": "2026-01-11",
        },
    }


def _make_efts_resp(hits):
    return MagicMock(
        status_code=200,
        json=MagicMock(return_value={"hits": {"hits": hits}}),
        raise_for_status=MagicMock(),
    )


def _make_xml_resp(xml_str):
    return MagicMock(
        status_code=200,
        content=xml_str.encode(),
        raise_for_status=MagicMock(),
    )


_CEO_BUY_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerCik>0001998560</issuerCik>
    <issuerName>Mint Incorporation Limited</issuerName>
    <issuerTradingSymbol>MIMI</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Chan Hoi Lung</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-01-10</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>211879</value></transactionShares>
        <transactionPricePerShare><value>3.01</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


# ── fetch_company_history ─────────────────────────────────────────────────

@patch("company_analyzer.requests.Session")
def test_fetch_company_history_returns_transactions_for_matching_cik(mock_session_cls):
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    hit = _make_efts_hit(ciks=[_CIK_PADDED])  # issuer = last CIK
    mock_session.get.side_effect = [
        _make_efts_resp([hit]),
        _make_xml_resp(_CEO_BUY_XML),
    ]
    results = fetch_company_history(cik=_CIK, ticker=_TICKER, lookback_days=730)
    assert len(results) == 1
    assert results[0].ticker == "MIMI"
    assert results[0].insider_name == "Chan Hoi Lung"


@patch("company_analyzer.requests.Session")
def test_fetch_company_history_filters_out_different_cik(mock_session_cls):
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    # Hit where issuer CIK does NOT match our target CIK
    hit = _make_efts_hit(ciks=[_OTHER_CIK])
    mock_session.get.side_effect = [_make_efts_resp([hit])]
    results = fetch_company_history(cik=_CIK, ticker=_TICKER, lookback_days=730)
    assert results == []


@patch("company_analyzer.requests.Session")
def test_fetch_company_history_returns_empty_on_edgar_error(mock_session_cls):
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    import requests as req
    mock_session.get.side_effect = req.RequestException("timeout")
    results = fetch_company_history(cik=_CIK, ticker=_TICKER, lookback_days=730)
    assert results == []


# ── score_and_filter ──────────────────────────────────────────────────────

def test_score_and_filter_returns_signals_above_min_score():
    # CEO buy $637K → score 4 (CEO) + 4 (≥$500K) = 8
    txs = [_make_tx(value=637_756.0, trade_date=date(2026, 1, 10))]
    result = score_and_filter(txs, min_score=8)
    assert len(result) == 1
    assert result[0][0] == date(2026, 1, 10)
    assert result[0][1] == _TICKER
    assert result[0][2] >= 8


def test_score_and_filter_excludes_signals_below_min_score():
    # Other officer buy $60K → score 1 (Other) + 1 (<$100K) = 2
    txs = [_make_tx(title="Director", value=60_000.0, trade_date=date(2026, 1, 10))]
    result = score_and_filter(txs, min_score=8)
    assert result == []


def test_score_and_filter_groups_by_date():
    # Two transactions on different dates — should produce 2 separate signals
    txs = [
        _make_tx(trade_date=date(2026, 1, 10), value=637_756.0),
        _make_tx(trade_date=date(2026, 3, 15), value=637_756.0),
    ]
    result = score_and_filter(txs, min_score=5)
    assert len(result) == 2
    dates = {r[0] for r in result}
    assert date(2026, 1, 10) in dates
    assert date(2026, 3, 15) in dates


def test_score_and_filter_skips_transactions_without_trade_date():
    txs = [_make_tx(trade_date=None)]
    result = score_and_filter(txs, min_score=5)
    assert result == []


def test_score_and_filter_applies_cluster_bonus_for_same_date():
    # Two different insiders on same date → cluster bonus → higher score
    txs = [
        _make_tx(insider="CEO Person", title="Chief Executive Officer",
                 value=200_000.0, trade_date=date(2026, 1, 10)),
        _make_tx(insider="CFO Person", title="Chief Financial Officer",
                 value=100_000.0, trade_date=date(2026, 1, 10)),
    ]
    result = score_and_filter(txs, min_score=5)
    assert len(result) == 1
    # Score: CEO+4 + CFO+3 + value≥$100K+2 + cluster2+3 = 12
    assert result[0][2] >= 10
```

- [ ] **Run tests to verify they fail**

```
pytest tests/test_company_analyzer.py -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'company_analyzer'`

- [ ] **Implement: create `company_analyzer.py` with module scaffold + the two functions**

Create `company_analyzer.py` in the project root:

```python
"""
Company Analyzer module for InsiderTracker.

For a given company (ticker + issuer CIK), fetches historical Form 4 insider
purchase filings from EDGAR, re-scores with existing scorer.py, and backtests
stock price performance at T+3, T+7, T+30 using yfinance.

Sends a second Telegram message with:
- Number of historical signals found with score >= today's
- Average % return at T+3, T+7, T+30
- Recommendation: COMPRA / ATTENZIONE / N/D with TP, SL, holding period
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import requests
import yfinance as yf

import config
from scraper import (
    InsiderTransaction,
    _parse_form4_xml,
    _xml_urls,
)
from scorer import score_all

logger = logging.getLogger(__name__)

# ── EDGAR constants (same as scraper — intentional duplication to avoid
#    importing private module-level names across modules) ─────────────────

_EDGAR_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_EDGAR_HEADERS = {
    "User-Agent": "InsiderTracker/1.0 corradocuri@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}
_REQUEST_DELAY = 0.12  # seconds between requests


# ── Data classes ──────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    """Performance statistics at a single time horizon."""
    horizon_days: int
    count: int
    positives: int
    avg_pct: float


@dataclass
class Recommendation:
    """Trading recommendation derived from backtest results."""
    action: str             # "COMPRA" | "ATTENZIONE" | "N/D"
    best_horizon: int       # 3, 7, or 30
    tp: Optional[float]     # take-profit price (None if N/D or ATTENZIONE)
    sl: float               # stop-loss price
    avg_pct: float          # average % return at best horizon


# ── EDGAR company history fetch ────────────────────────────────────────────

def fetch_company_history(
    cik: str,
    ticker: str,
    lookback_days: int = config.COMPANY_HISTORY_LOOKBACK_DAYS,
) -> List[InsiderTransaction]:
    """Fetch historical insider purchase transactions for a specific company.

    Queries EDGAR EFTS with q=TICKER (full-text search) over the lookback window,
    filters results to the target issuer CIK, fetches each matching Form 4 XML,
    and returns purchase transactions (code=P, value >= MIN_TRANSACTION_VALUE).

    Returns an empty list on any network error (caller handles gracefully).
    Limitation: EDGAR EFTS returns at most 200 results per query. Sufficient
    for small/mid-cap companies; may miss oldest filings for large caps.
    """
    end = date.today()
    start = end - timedelta(days=lookback_days)
    target_cik = cik.lstrip("0")

    session = requests.Session()
    session.headers.update(_EDGAR_HEADERS)

    params = {
        "forms": "4",
        "dateRange": "custom",
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
        "q": f'"{ticker}"',
        "from": "0",
        "size": "200",
    }

    try:
        resp = session.get(_EDGAR_EFTS_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("EDGAR company history fetch failed for %s: %s", ticker, exc)
        return []

    # Parse EFTS hits and filter by issuer CIK
    filings = []
    for hit in data.get("hits", {}).get("hits", []):
        _id = hit.get("_id", "")
        source = hit.get("_source", {})
        if ":" not in _id:
            continue
        _, doc_filename = _id.rsplit(":", 1)
        if not doc_filename.lower().endswith(".xml"):
            continue
        adsh = source.get("adsh", "").strip()
        hit_ciks = source.get("ciks", [])
        if not adsh or not hit_ciks:
            continue
        # issuer CIK = last element in ciks array (EDGAR Form 4 convention)
        if hit_ciks[-1].lstrip("0") != target_cik:
            continue
        filings.append({
            "adsh": adsh,
            "ciks": hit_ciks,
            "doc_filename": doc_filename,
        })

    # Fetch and parse each filing's XML
    transactions: List[InsiderTransaction] = []
    for filing in filings:
        time.sleep(_REQUEST_DELAY)
        xml_content = None
        for url in _xml_urls(filing["adsh"], filing["ciks"], filing["doc_filename"]):
            try:
                xml_resp = session.get(url, timeout=20)
                if xml_resp.status_code == 200:
                    xml_content = xml_resp.content
                    break
                if xml_resp.status_code == 404:
                    continue
            except requests.RequestException:
                continue

        if xml_content is None:
            continue

        for t in _parse_form4_xml(xml_content):
            if t["value"] >= config.MIN_TRANSACTION_VALUE:
                transactions.append(InsiderTransaction(
                    ticker=t["ticker"],
                    company=t["company"],
                    insider_name=t["insider_name"],
                    title=t["title"],
                    value=t["value"],
                    trade_date=t["trade_date"],
                    cik=cik,
                ))

    return transactions


# ── Scoring filter ────────────────────────────────────────────────────────

def score_and_filter(
    transactions: List[InsiderTransaction],
    min_score: int,
) -> List[Tuple[date, str, int]]:
    """Score historical transactions grouped by trade_date and filter by min_score.

    Groups transactions by trade_date (each date = one "event"), scores each
    group with score_all (applies cluster bonuses for same-day multi-insider buys),
    and returns (trade_date, ticker, score) tuples where score >= min_score.

    Transactions without a trade_date are skipped.
    """
    dated = [t for t in transactions if t.trade_date is not None]

    by_date: dict = defaultdict(list)
    for t in dated:
        by_date[t.trade_date].append(t)

    results: List[Tuple[date, str, int]] = []
    for trade_date in sorted(by_date.keys()):
        signals = score_all(by_date[trade_date])
        for sig in signals:
            if sig.score >= min_score:
                results.append((trade_date, sig.ticker, sig.score))

    return results
```

- [ ] **Run tests to verify they pass**

```
pytest tests/test_company_analyzer.py -v -k "fetch_company_history or score_and_filter"
```

Expected: all 8 tests pass.

- [ ] **Commit**

```
git add company_analyzer.py tests/test_company_analyzer.py
git commit -m "feat(company_analyzer): add fetch_company_history and score_and_filter"
```

---

## Task 5: `company_analyzer.py` — `backtest()` + `_price_on_or_after()`

**Files:**
- Modify: `company_analyzer.py`
- Modify: `tests/test_company_analyzer.py`

**Context:** For each historical signal `(trade_date, ticker, score)`, fetches 45 days of price data from yfinance in a single call and extracts closing prices at T+3, T+7, T+30. `_price_on_or_after` handles weekends/holidays by returning the first available trading day at or after the target date. Uses `ts.date() >= target` for timezone-safe comparison.

- [ ] **Write the failing tests** — add to `tests/test_company_analyzer.py`:

```python
import pandas as pd
from company_analyzer import backtest, BacktestResult


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
        (date(2026, 1, 10), 10.0),   # entry (T+0)
        (date(2026, 1, 13), 11.0),   # T+3
        (date(2026, 1, 17), 12.0),   # T+7
        (date(2026, 2, 9),  14.0),   # T+30
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    signals = [(date(2026, 1, 10), "MIMI", 8)]
    result = backtest(signals)
    assert result[3].avg_pct == pytest.approx(10.0, abs=0.1)   # +10%
    assert result[7].avg_pct == pytest.approx(20.0, abs=0.1)   # +20%
    assert result[30].avg_pct == pytest.approx(40.0, abs=0.1)  # +40%


@patch("company_analyzer.yf")
def test_backtest_counts_positives_correctly(mock_yf):
    # Two signals: one positive (+10%), one negative (−5%) at T+7
    hist1 = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 17), 11.0),   # +10%
    )
    hist2 = _make_hist(
        (date(2026, 3, 1), 20.0),
        (date(2026, 3, 8), 19.0),    # -5%
    )
    mock_yf.Ticker.return_value.history.side_effect = [hist1, hist2]
    signals = [
        (date(2026, 1, 10), "MIMI", 8),
        (date(2026, 3, 1),  "MIMI", 8),
    ]
    result = backtest(signals)
    assert result[7].count == 2
    assert result[7].positives == 1


@patch("company_analyzer.yf")
def test_backtest_skips_signal_when_yfinance_returns_empty(mock_yf):
    mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
    signals = [(date(2026, 1, 10), "MIMI", 8)]
    result = backtest(signals)
    for h in [3, 7, 30]:
        assert result[h].count == 0


@patch("company_analyzer.yf")
def test_backtest_skips_horizon_when_price_unavailable(mock_yf):
    # Only entry + T+3 available; T+7 and T+30 missing
    hist = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 13), 11.0),
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    signals = [(date(2026, 1, 10), "MIMI", 8)]
    result = backtest(signals)
    assert result[3].count == 1
    assert result[7].count == 0
    assert result[30].count == 0
```

- [ ] **Run tests to verify they fail**

```
pytest tests/test_company_analyzer.py -v -k "backtest"
```

Expected: `FAILED` — `ImportError: cannot import name 'backtest'`

- [ ] **Implement: add `_price_on_or_after` and `backtest` to `company_analyzer.py`**

Add after `score_and_filter`:

```python
# ── Price helper ──────────────────────────────────────────────────────────

def _price_on_or_after(hist: "pd.DataFrame", target: date) -> Optional[float]:
    """Return the first available Close price on or after target date.

    Uses ts.date() for timezone-safe comparison (works regardless of whether
    the yfinance index is timezone-aware or naive).
    """
    for ts in hist.index:
        if ts.date() >= target:
            return float(hist.loc[ts, "Close"])
    return None


# ── Backtest ──────────────────────────────────────────────────────────────

def backtest(
    signals: List[Tuple[date, str, int]],
) -> Dict[int, BacktestResult]:
    """Compute stock price performance at T+3, T+7, T+30 for each signal.

    For each historical signal, fetches 45 days of price data via yfinance
    (one API call per signal) and computes % return at each horizon.
    Signals with missing yfinance data are skipped entirely.
    Horizons where the exit price is unavailable are skipped per signal.

    Returns a dict keyed by horizon (3, 7, 30) → BacktestResult.
    """
    horizons = [3, 7, 30]
    accum: Dict[int, Dict] = {h: {"pos": 0, "total": 0, "sum_pct": 0.0} for h in horizons}

    for trade_date, ticker, _score in signals:
        end_fetch = trade_date + timedelta(days=45)
        try:
            hist = yf.Ticker(ticker).history(
                start=trade_date.isoformat(),
                end=end_fetch.isoformat(),
                auto_adjust=True,
            )
        except Exception as exc:
            logger.debug("yfinance error for %s on %s: %s", ticker, trade_date, exc)
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
            pct = (exit_price - entry) / entry * 100
            accum[h]["total"] += 1
            accum[h]["sum_pct"] += pct
            if pct > 0:
                accum[h]["pos"] += 1

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

```
pytest tests/test_company_analyzer.py -v -k "backtest"
```

Expected: all 5 backtest tests pass.

- [ ] **Commit**

```
git add company_analyzer.py tests/test_company_analyzer.py
git commit -m "feat(company_analyzer): add backtest and _price_on_or_after"
```

---

## Task 6: `company_analyzer.py` — `generate_recommendation()` + `build_message()` + `analyze()`

**Files:**
- Modify: `company_analyzer.py`
- Modify: `tests/test_company_analyzer.py`

**Context:** `generate_recommendation` picks the best horizon (highest success rate, tie-break: highest avg_pct) and computes TP/SL. `build_message` formats the Telegram string. `analyze` is the top-level orchestrator called from `insider_tracker.py`.

- [ ] **Write the failing tests** — add to `tests/test_company_analyzer.py`:

```python
from company_analyzer import (
    BacktestResult,
    Recommendation,
    generate_recommendation,
    build_message,
    analyze,
)


def _make_stats(t3=(0, 0, 0.0), t7=(3, 3, 15.0), t30=(2, 3, 8.0)):
    """Helper: build a stats dict from (count, positives, avg_pct) tuples."""
    c3, p3, a3 = t3
    c7, p7, a7 = t7
    c30, p30, a30 = t30
    return {
        3:  BacktestResult(horizon_days=3,  count=c3,  positives=p3,  avg_pct=a3),
        7:  BacktestResult(horizon_days=7,  count=c7,  positives=p7,  avg_pct=a7),
        30: BacktestResult(horizon_days=30, count=c30, positives=p30, avg_pct=a30),
    }


# ── generate_recommendation ───────────────────────────────────────────────

def test_generate_recommendation_returns_nd_when_no_data():
    stats = _make_stats(t3=(0, 0, 0.0), t7=(0, 0, 0.0), t30=(0, 0, 0.0))
    rec = generate_recommendation(stats, entry_price=3.21)
    assert rec.action == "N/D"
    assert rec.tp is None


def test_generate_recommendation_compra_on_positive_avg():
    stats = _make_stats(t7=(3, 3, 15.0))
    rec = generate_recommendation(stats, entry_price=10.0)
    assert rec.action == "COMPRA"
    assert rec.tp == pytest.approx(11.50, abs=0.01)  # 10.0 * 1.15


def test_generate_recommendation_attenzione_on_negative_avg():
    stats = _make_stats(t7=(3, 0, -5.0))
    rec = generate_recommendation(stats, entry_price=10.0)
    assert rec.action == "ATTENZIONE"
    assert rec.tp is None


def test_generate_recommendation_sl_calculation():
    import config
    stats = _make_stats(t7=(3, 3, 15.0))
    rec = generate_recommendation(stats, entry_price=10.0)
    assert rec.sl == pytest.approx(10.0 * (1 - config.SL_PERCENT), abs=0.01)


def test_generate_recommendation_selects_best_horizon_by_success_rate():
    # T+7: 3/3 (100%) avg +5%  — T+30: 2/3 (67%) avg +20%
    # T+7 wins because higher success rate
    stats = _make_stats(
        t3=(0, 0, 0.0),
        t7=(3, 3, 5.0),
        t30=(3, 2, 20.0),
    )
    rec = generate_recommendation(stats, entry_price=10.0)
    assert rec.best_horizon == 7


def test_generate_recommendation_tiebreaks_by_avg_pct():
    # T+7 and T+30 both 2/3 (67%) — T+30 wins on avg_pct
    stats = _make_stats(
        t3=(0, 0, 0.0),
        t7=(3, 2, 5.0),
        t30=(3, 2, 12.0),
    )
    rec = generate_recommendation(stats, entry_price=10.0)
    assert rec.best_horizon == 30


# ── build_message ─────────────────────────────────────────────────────────

def test_build_message_no_history_contains_nd():
    stats = _make_stats(t3=(0, 0, 0.0), t7=(0, 0, 0.0), t30=(0, 0, 0.0))
    rec = Recommendation(action="N/D", best_horizon=7, tp=None, sl=2.95, avg_pct=0.0)
    msg = build_message(ticker="MIMI", entry_price=3.21, stats=stats, rec=rec,
                        today_score=11, signal_count=0)
    assert "MIMI" in msg
    assert "nessuno trovato" in msg
    assert "N/D" in msg


def test_build_message_with_history_contains_key_fields():
    stats = _make_stats(t7=(3, 3, 15.0))
    rec = Recommendation(action="COMPRA", best_horizon=7, tp=3.69, sl=2.95, avg_pct=15.0)
    msg = build_message(ticker="MIMI", entry_price=3.21, stats=stats, rec=rec,
                        today_score=11, signal_count=3)
    assert "$MIMI" in msg
    assert "3 trovati" in msg
    assert "COMPRA" in msg
    assert "3.69" in msg   # TP
    assert "2.95" in msg   # SL
    assert "7 giorni" in msg


def test_build_message_marks_best_horizon():
    stats = _make_stats(t7=(3, 3, 15.0))
    rec = Recommendation(action="COMPRA", best_horizon=7, tp=3.69, sl=2.95, avg_pct=15.0)
    msg = build_message(ticker="MIMI", entry_price=3.21, stats=stats, rec=rec,
                        today_score=11, signal_count=3)
    assert "migliore" in msg


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
```

- [ ] **Run tests to verify they fail**

```
pytest tests/test_company_analyzer.py -v -k "recommendation or build_message or analyze"
```

Expected: `FAILED` — `ImportError: cannot import name 'generate_recommendation'`

- [ ] **Implement: add the three functions to `company_analyzer.py`**

Add after `backtest`:

```python
# ── Recommendation ────────────────────────────────────────────────────────

def generate_recommendation(
    stats: Dict[int, BacktestResult],
    entry_price: float,
) -> Recommendation:
    """Generate a trading recommendation from backtest results.

    Selects the best horizon by success rate (positives/count);
    tie-breaks on avg_pct. Returns N/D if no horizon has any data.
    """
    sl = round(entry_price * (1 - config.SL_PERCENT), 2)
    valid = {h: r for h, r in stats.items() if r.count > 0}

    if not valid:
        return Recommendation(action="N/D", best_horizon=7, tp=None,
                               sl=sl, avg_pct=0.0)

    best_h = max(
        valid.keys(),
        key=lambda h: (valid[h].positives / valid[h].count, valid[h].avg_pct),
    )
    best = valid[best_h]

    if best.avg_pct > 0:
        action = "COMPRA"
        tp = round(entry_price * (1 + best.avg_pct / 100), 2)
    else:
        action = "ATTENZIONE"
        tp = None

    return Recommendation(
        action=action,
        best_horizon=best_h,
        tp=tp,
        sl=sl,
        avg_pct=best.avg_pct,
    )


# ── Message builder ───────────────────────────────────────────────────────

def build_message(
    ticker: str,
    entry_price: float,
    stats: Dict[int, BacktestResult],
    rec: Recommendation,
    today_score: int,
    signal_count: int,
) -> str:
    """Format the second Telegram message with historical analysis."""
    lines = [f"📊 ANALISI STORICA — ${ticker}", ""]

    if signal_count == 0:
        lines.append(f"🔍 Acquisti passati con score ≥ {today_score}: nessuno trovato")
        lines.append("→ Primo acquisto rilevante per questa azienda")
        lines.append("")
        lines.append("🎯 Raccomandazione: N/D — nessun dato storico")
        return "\n".join(lines)

    lines.append(f"🔍 Acquisti passati con score ≥ {today_score}: {signal_count} trovati")
    lines.append("")
    lines.append("📈 Performance media post-acquisto:")

    for h in [3, 7, 30]:
        r = stats.get(h)
        if r and r.count > 0:
            marker = " ← migliore" if h == rec.best_horizon else ""
            sign = "+" if r.avg_pct >= 0 else ""
            lines.append(
                f"• a {h} giorni:  {sign}{r.avg_pct:.1f}%"
                f"  ({r.positives}/{r.count} positivi){marker}"
            )

    lines.append("")
    lines.append(f"🎯 Raccomandazione: {rec.action}")
    lines.append(f"• Entry: ${entry_price:.2f}")
    if rec.tp is not None:
        sign = "+" if rec.avg_pct >= 0 else ""
        lines.append(
            f"• TP: ${rec.tp:.2f}  ({sign}{rec.avg_pct:.0f}%,"
            f" basato su media {rec.best_horizon}gg)"
        )
    lines.append(f"• SL: ${rec.sl:.2f}  (-{config.SL_PERCENT * 100:.0f}%)")
    lines.append(f"• Holding: ~{rec.best_horizon} giorni")

    return "\n".join(lines)


# ── Top-level orchestrator ────────────────────────────────────────────────

def analyze(
    ticker: str,
    cik: str,
    today_score: int,
    entry_price: float,
) -> str:
    """Fetch history, backtest, and return a formatted Telegram message.

    On any error, returns a message indicating no data is available.
    """
    if entry_price <= 0:
        return (
            f"📊 ANALISI STORICA — ${ticker}\n\n"
            "⚠️ Prezzo entry non disponibile.\n"
            "🎯 Raccomandazione: N/D"
        )
    try:
        transactions = fetch_company_history(cik=cik, ticker=ticker)
        filtered = score_and_filter(transactions, min_score=today_score)
        # Exclude today's signal — outcome not yet available
        today = date.today()
        historical = [(d, t, s) for d, t, s in filtered if d < today]
        stats = backtest(historical)
        rec = generate_recommendation(stats, entry_price)
        return build_message(
            ticker=ticker,
            entry_price=entry_price,
            stats=stats,
            rec=rec,
            today_score=today_score,
            signal_count=len(historical),
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

```
pytest tests/test_company_analyzer.py -v
```

Expected: all tests pass.

- [ ] **Commit**

```
git add company_analyzer.py tests/test_company_analyzer.py
git commit -m "feat(company_analyzer): add generate_recommendation, build_message, analyze"
```

---

## Task 7: `insider_tracker.py` — Integration

**Files:**
- Modify: `insider_tracker.py`
- Modify: `tests/test_tracker.py`

**Context:** After a signal is successfully sent, fetch the current price via yfinance, call `company_analyzer.analyze()`, and send the result with `notifier.send_analysis()`. Wrap in try/except so a failure in the analysis never breaks the main signal flow. Only call analysis when `top is not None` (don't analyze on "no signal today" days).

- [ ] **Write the failing tests** — add at the top of `tests/test_tracker.py` the new imports:

```python
import pytest
import pandas as pd
from insider_tracker import get_current_price
```

Then add the tests at the bottom of the file:

```python
# ── get_current_price ─────────────────────────────────────────────────────

@patch("insider_tracker.yf")
def test_get_current_price_returns_close_price(mock_yf):
    mock_df = pd.DataFrame(
        {"Close": [3.21]},
        index=[pd.Timestamp("2026-05-28")]
    )
    mock_yf.Ticker.return_value.history.return_value = mock_df
    price = get_current_price("MIMI")
    assert price == pytest.approx(3.21)


@patch("insider_tracker.yf")
def test_get_current_price_returns_zero_on_empty_history(mock_yf):
    mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
    assert get_current_price("MIMI") == 0.0


@patch("insider_tracker.yf")
def test_get_current_price_returns_zero_on_exception(mock_yf):
    mock_yf.Ticker.return_value.history.side_effect = Exception("network error")
    assert get_current_price("MIMI") == 0.0
```

- [ ] **Run tests to verify they fail**

```
pytest tests/test_tracker.py::test_get_current_price_returns_close_price tests/test_tracker.py::test_get_current_price_returns_zero_on_empty_history tests/test_tracker.py::test_get_current_price_returns_zero_on_exception -v
```

Expected: `FAILED` — `ImportError: cannot import name 'get_current_price'`

- [ ] **Implement: add imports and `get_current_price()` to `insider_tracker.py`**

Add imports at the top (after existing imports):
```python
import yfinance as yf
import company_analyzer
from notifier import send_signal, send_error, send_analysis
```

Add the function after `_fetch_all`:
```python
def get_current_price(ticker: str) -> float:
    """Fetch the most recent closing price via yfinance.

    Returns 0.0 if the ticker has no data or yfinance raises an exception.
    """
    try:
        hist = yf.Ticker(ticker).history(period="1d", auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 0.0
```

- [ ] **Implement: call `analyze()` + `send_analysis()` after signal in `main()`**

In `main()`, replace:
```python
        sent = send_signal(top, token, chat_id)
        if sent and top is not None:
            mark_sent(top.ticker, last_seen)
            save_last_seen(last_seen)
```
with:
```python
        sent = send_signal(top, token, chat_id)
        if sent and top is not None:
            mark_sent(top.ticker, last_seen)
            save_last_seen(last_seen)
            try:
                cik = top.transactions[0].cik if top.transactions else ""
                entry_price = get_current_price(top.ticker)
                analysis = company_analyzer.analyze(
                    ticker=top.ticker,
                    cik=cik,
                    today_score=top.score,
                    entry_price=entry_price,
                )
                send_analysis(analysis, token, chat_id)
            except Exception as exc:
                logger.error("company_analyzer failed for %s: %s", top.ticker, exc, exc_info=True)
```

- [ ] **Run all tests**

```
pytest tests/ -v
```

Expected: all tests pass (no regressions).

- [ ] **Commit**

```
git add insider_tracker.py tests/test_tracker.py
git commit -m "feat(tracker): integrate company_analyzer — send analysis after each signal"
```

---

## Task 8: Install `yfinance` + full verification

**Files:**
- Modify: `requirements.txt`

- [ ] **Add yfinance to `requirements.txt`**

Append to `requirements.txt`:
```
yfinance>=0.2.50
```

- [ ] **Install in venv**

```
cd "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker"
venv\Scripts\activate && pip install yfinance>=0.2.50
```

Expected output includes: `Successfully installed yfinance-X.X.X`

- [ ] **Run complete test suite**

```
pytest tests/ -v
```

Expected: all tests pass. Count should be 90 (existing) + new tests ≥ 110 total.

- [ ] **Smoke test: run main once manually**

```
python insider_tracker.py
```

Check `run.log` for output. Verify:
- No Python exceptions
- If a signal fires, two Telegram messages are received: signal + analysis
- If weekend or no signal, only the "nessun segnale" message (no analysis)

- [ ] **Commit**

```
git add requirements.txt
git commit -m "feat: add yfinance dependency for company price history"
```

---

## Known Limitations

- EDGAR EFTS returns at most 200 Form 4 filings per query. Sufficient for small/mid-cap targets; would miss oldest filings for high-volume large caps.
- `SL_PERCENT` (8%) is a fixed value, not derived from historical volatility. Suitable for the current speculative strategy.
- yfinance may return empty data for very newly listed stocks or tickers with limited history. Handled gracefully (N/D recommendation).
- Historical backtest uses `trade_date` (the actual buy date) as entry point, not the filing date (when it became public). Filing date is typically 1-2 business days later. This is a known approximation.
