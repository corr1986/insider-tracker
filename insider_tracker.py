"""
Orchestration entry point for InsiderTracker.

Fetches insider transactions from OpenInsider, scores them, and sends the
top signal to Telegram (if any). Tracks which tickers were already sent today
to avoid duplicate alerts.
"""

import json
import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv

import config
from scraper import fetch_transactions, deduplicate
from scorer import score_all, TickerSignal
from notifier import send_signal, send_error

load_dotenv()

logging.basicConfig(
    filename="errors.log",
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

LAST_SEEN_FILE = Path("last_seen.json")


def load_last_seen() -> dict:
    """Load the last_seen dict from disk, or return an empty dict if absent."""
    if LAST_SEEN_FILE.exists():
        return json.loads(LAST_SEEN_FILE.read_text(encoding="utf-8"))
    return {}


def save_last_seen(last_seen: dict) -> None:
    """Persist the last_seen dict to disk as JSON."""
    LAST_SEEN_FILE.write_text(json.dumps(last_seen, indent=2), encoding="utf-8")


def already_sent_today(ticker: str, last_seen: dict) -> bool:
    """Return True if a signal for ticker was already sent today."""
    return last_seen.get(ticker) == str(date.today())


def mark_sent(ticker: str, last_seen: dict) -> None:
    """Record that a signal for ticker was sent today (mutates last_seen in-place)."""
    last_seen[ticker] = str(date.today())


def pick_top_signal(
    signals: List[TickerSignal], last_seen: dict
) -> Optional[TickerSignal]:
    """Return the highest-scoring eligible signal, or None.

    A signal is eligible if:
    - Its score is >= config.MIN_SCORE
    - It has not already been sent today (checked via last_seen)

    Signals are assumed to be pre-sorted descending by score (as returned by
    score_all). The first eligible signal is returned.
    """
    for signal in signals:
        if signal.score >= config.MIN_SCORE and not already_sent_today(signal.ticker, last_seen):
            return signal
    return None


def _fetch_all() -> list:
    """Fetch transactions from all configured URLs with 3-attempt retry.

    Each URL is retried up to 3 times with exponential backoff (1s, 2s).
    Raises requests.RequestException if all attempts fail for a URL.
    Returns deduplicated list of InsiderTransaction objects.
    """
    all_transactions = []
    for url in config.OPENINSIDER_URLS:
        for attempt in range(3):
            try:
                txs = fetch_transactions(
                    url, config.MIN_TRANSACTION_VALUE, config.LOOKBACK_CALENDAR_DAYS
                )
                all_transactions.extend(txs)
                break
            except requests.RequestException as exc:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
    return deduplicate(all_transactions)


def main() -> None:
    """Main orchestration loop: fetch, score, pick top signal, send to Telegram.

    Reads TELEGRAM_TOKEN and TELEGRAM_CHAT_ID from environment (via .env).
    On fatal errors, sends an error alert to Telegram and logs to errors.log.
    """
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    last_seen = load_last_seen()

    try:
        transactions = _fetch_all()
        signals = score_all(transactions)
        top = pick_top_signal(signals, last_seen)
        sent = send_signal(top, token, chat_id)
        if sent and top is not None:
            mark_sent(top.ticker, last_seen)
            save_last_seen(last_seen)
    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        send_error(str(exc), token, chat_id)


if __name__ == "__main__":
    main()
