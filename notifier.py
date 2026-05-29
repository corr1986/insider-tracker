"""
Notifier module for InsiderTracker.

Formats TickerSignal objects as Telegram messages and sends them via the
Telegram Bot API. Provides helpers for signal messages, analysis messages,
and error alerts.
"""

import logging
from datetime import date
from typing import Optional

import requests

from scorer import TickerSignal

logger = logging.getLogger(__name__)


def _signal_label(score: int) -> str:
    """Return a short quality label for a given score.

    Thresholds:
      5–7  → 🔴 Debole
      8–10 → 🟡 Buono
      11–13→ 🟢 Ottimo
      14+  → 🔥 Eccellente
    """
    if score >= 14:
        return "🔥 Eccellente"
    if score >= 11:
        return "🟢 Ottimo"
    if score >= 8:
        return "🟡 Buono"
    return "🔴 Debole"


def _format_message(signal: TickerSignal) -> str:
    """Format a TickerSignal as a human-readable Telegram message string.

    Includes the ticker, company name, each insider name and value,
    the total score, the score breakdown lines, and a link to OpenInsider.
    """
    today = date.today().strftime("%d/%m/%Y")
    lines = [f"🔍 INSIDER TRACKER — {today}", ""]
    lines.append(f"📌 ${signal.ticker} — {signal.company}")
    for tx in signal.transactions:
        lines.append(f"👤 {tx.insider_name} ({tx.title}) → ${tx.value:,.0f}")
    lines.append("")
    lines.append(f"📊 Score: {signal.score} pt — {_signal_label(signal.score)}")
    lines.extend(signal.score_breakdown)
    lines.append("")
    lines.append(f"🔗 openinsider.com/{signal.ticker}")
    return "\n".join(lines)


def _no_signal_message() -> str:
    """Return a Telegram message string indicating no insider signals today."""
    today = date.today().strftime("%d/%m/%Y")
    return f"🔍 INSIDER TRACKER — {today}\n😴 Nessun segnale insider oggi."


def _error_message(error: str) -> str:
    """Format an error string as a Telegram alert message."""
    return f"⚠️ INSIDER TRACKER — Errore scraping OpenInsider:\n{error}"


def _send_telegram(text: str, token: str, chat_id: str) -> bool:
    """Send a text message to a Telegram chat via the Bot API.

    Returns True on success, False if a network or HTTP error occurs.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("Telegram send failed: %s", e)
        return False


def send_signal(signal: Optional[TickerSignal], token: str, chat_id: str) -> bool:
    """Send a TickerSignal message to Telegram, or a no-signal message if None.

    Returns True on success, False on network/HTTP error.
    """
    text = _format_message(signal) if signal is not None else _no_signal_message()
    return _send_telegram(text, token, chat_id)


def send_error(error: str, token: str, chat_id: str) -> bool:
    """Send an error alert to Telegram.

    Returns True on success, False on network/HTTP error.
    """
    return _send_telegram(_error_message(error), token, chat_id)


def send_analysis(message: str, token: str, chat_id: str) -> bool:
    """Send a pre-formatted company analysis message to Telegram.

    Returns True on success, False on network/HTTP error.
    """
    return _send_telegram(message, token, chat_id)
