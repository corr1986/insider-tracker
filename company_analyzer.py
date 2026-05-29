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

# ── EDGAR constants ────────────────────────────────────────────────────────

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

    if len(filings) == 200:
        logger.warning(
            "EDGAR returned max 200 results for %s (CIK %s) — "
            "oldest filings may be missing",
            ticker, cik,
        )

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
            try:
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
            except KeyError as exc:
                logger.debug("Skipping malformed transaction dict: missing key %s", exc)
                continue

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

    Note: groups by ``trade_date`` (execution date), not ``filing_date``. Same-day
    buys by multiple insiders form a single identifiable cluster event — this is the
    correct basis for backtesting.
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
