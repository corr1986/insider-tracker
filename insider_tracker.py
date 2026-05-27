"""
Orchestration entry point for InsiderTracker.

Fetches insider transactions from SEC EDGAR, scores them, and sends the
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

from dotenv import load_dotenv

import config
from scraper import fetch_all_edgar_transactions
from scorer import score_all, TickerSignal
from notifier import send_signal, send_error

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
    """Fetch transactions from SEC EDGAR with 3-attempt retry.

    Retries up to 3 times with exponential backoff (1s, 2s) on failure.
    Raises RuntimeError if all attempts fail.
    Returns deduplicated list of InsiderTransaction objects.
    """
    for attempt in range(3):
        try:
            return fetch_all_edgar_transactions(
                config.MIN_TRANSACTION_VALUE, config.LOOKBACK_CALENDAR_DAYS
            )
        except RuntimeError as exc:
            if attempt == 2:
                raise
            logger.warning("EDGAR fetch attempt %d failed: %s", attempt + 1, exc)
            time.sleep(2 ** attempt)
    return []  # unreachable — satisfies type checkers


def main() -> None:
    """Main orchestration loop: fetch, score, pick top signal, send to Telegram.

    Reads TELEGRAM_TOKEN and TELEGRAM_CHAT_ID from environment (via .env).
    On fatal errors, sends an error alert to Telegram and logs to errors.log.
    """
    load_dotenv()

    try:
        token = os.environ["TELEGRAM_TOKEN"].strip()
        chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
        last_seen = load_last_seen()
        transactions = _fetch_all()
        signals = score_all(transactions)
        top = pick_top_signal(signals, last_seen)
        sent = send_signal(top, token, chat_id)
        if sent and top is not None:
            mark_sent(top.ticker, last_seen)
            save_last_seen(last_seen)
    except KeyError as exc:
        logger.error("Missing environment variable: %s — check .env file", exc)
    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        # best-effort Telegram alert (may fail if token/chat_id are missing)
        try:
            send_error(str(exc), os.environ.get("TELEGRAM_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip())
        except Exception:
            pass


if __name__ == "__main__":
    main()
