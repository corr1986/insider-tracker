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


# ── Price helper ──────────────────────────────────────────────────────────

def _price_on_or_after(hist: "pd.DataFrame", target: date) -> Optional[float]:
    """Return the first available Close price on or after target date.

    Uses ts.date() for timezone-safe comparison (works regardless of whether
    the yfinance index is timezone-aware or naive).
    Assumes hist.index is sorted ascending (yfinance always returns sorted data,
    so sort_index() is intentionally omitted for performance).
    """
    for ts in hist.index:
        if ts.date() >= target:
            return float(hist.loc[ts, "Close"])
    return None


# ── Backtest ──────────────────────────────────────────────────────────────

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
    Excludes today's signals (outcome not yet available).
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
