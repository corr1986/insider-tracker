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
                continue
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

    def signed(v: Optional[float]) -> str:
        if v is None:
            return "—"
        sign = "+" if v >= 0 else ""
        return f"{sign}${abs(v):,.0f}"

    github_url = "https://github.com/corr1986/insider-tracker/blob/main/Portfolio%20Simulato.md"

    lines = [
        "# Portfolio Simulato — Insider Tracker",
        f"*Aggiornato: {now_str} — [📊 Vedi su GitHub]({github_url})*",
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
    import os
    logging.basicConfig(level=logging.WARNING)
    # On GitHub Actions use a relative path; locally use config.PORTFOLIO_MD
    md_override = os.environ.get("PORTFOLIO_MD_PATH")
    md_path = Path(md_override) if md_override else None
    update(md_path=md_path)
