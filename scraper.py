"""
Scraper module for InsiderTracker.

Fetches and parses insider transaction tables from OpenInsider HTML pages,
filtering by purchase type, minimum value, and recency.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional
import re
import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class InsiderTransaction:
    """Represents a single insider purchase transaction."""

    ticker: str
    company: str
    insider_name: str
    title: str
    value: float
    trade_date: Optional[date]


def _parse_value(value_str: str) -> float:
    """Parse a dollar-formatted string like '$1,234,567' into a float.

    Strips all non-numeric characters except the decimal point.
    Returns 0.0 if the string contains no numeric content or is malformed
    (e.g. multiple decimal points, unparseable after cleaning).
    """
    clean = re.sub(r"[^\d.]", "", value_str)
    if not clean or clean.count(".") > 1:
        logger.warning("Could not parse value: %r", value_str)
        return 0.0
    try:
        return float(clean)
    except ValueError:
        logger.warning("Could not parse value: %r", value_str)
        return 0.0


def _parse_date(date_str: str) -> Optional[date]:
    """Parse the first 10 characters of a date string in 'YYYY-MM-DD' format.

    Returns None if the string is missing or malformed.
    """
    try:
        return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return None


# OpenInsider tinytable column indices (verified against live HTML — see docs/plans)
_COL_FILING_DATE = 1
_COL_TRADE_DATE = 2
_COL_TICKER = 3
_COL_COMPANY = 4
_COL_INSIDER_NAME = 5
_COL_TITLE = 6
_COL_TRADE_TYPE = 7
_COL_VALUE = 12
_MIN_COLS = 13


def parse_transactions(
    html: str, min_value: float, lookback_days: int
) -> List[InsiderTransaction]:
    """Parse an OpenInsider HTML page and return filtered InsiderTransaction list.

    Filters applied:
    - Only open-market purchases (Trade Type == 'P')
    - Trade date must be >= today - lookback_days (inclusive)
    - Transaction value >= min_value

    Column indices (verified against the live OpenInsider 'tinytable' layout):
    - 0: X
    - 1: Filing Date
    - 2: Trade Date
    - 3: Ticker
    - 4: Company
    - 5: Insider Name
    - 6: Title
    - 7: Trade Type  (P = purchase, S = sale)
    - 8: Price
    - 9: Qty
    - 10: Owned
    - 11: DeltaOwn
    - 12: Value

    Uses html.parser (Python built-in) intentionally — no lxml dependency
    required for this project's scraping requirements.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "tinytable"})
    if not table:
        return []

    tbody = table.find("tbody")
    if not tbody:
        return []

    cutoff = date.today() - timedelta(days=lookback_days)
    transactions: List[InsiderTransaction] = []

    for row in tbody.find_all("tr"):
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) < _MIN_COLS:
            continue

        # Only include open-market purchases
        if cols[_COL_TRADE_TYPE] != "P":
            continue

        trade_date = _parse_date(cols[_COL_TRADE_DATE])
        if trade_date is None or trade_date < cutoff:
            continue

        value = _parse_value(cols[_COL_VALUE])
        if value < min_value:
            continue

        ticker = cols[_COL_TICKER].upper().strip()
        company = cols[_COL_COMPANY].strip()
        if not ticker or not company:
            continue

        transactions.append(InsiderTransaction(
            ticker=ticker,
            company=company,
            insider_name=cols[_COL_INSIDER_NAME].strip(),
            title=cols[_COL_TITLE].strip(),
            value=value,
            trade_date=trade_date,
        ))

    return transactions


def fetch_transactions(
    url: str, min_value: float, lookback_days: int
) -> List[InsiderTransaction]:
    """Fetch a live OpenInsider URL and return filtered InsiderTransaction list.

    Raises requests.HTTPError on non-2xx responses.
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; InsiderTracker/1.0)"}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return parse_transactions(response.text, min_value, lookback_days)


def deduplicate(transactions: List[InsiderTransaction]) -> List[InsiderTransaction]:
    """Remove duplicate transactions (same ticker + insider name + trade date).

    Transactions with trade_date=None are always kept (not deduplicated).
    The first occurrence in the list is kept; subsequent duplicates are discarded.
    """
    seen: set = set()
    result: List[InsiderTransaction] = []
    for t in transactions:
        if t.trade_date is None:
            result.append(t)
            continue
        key = (t.ticker, t.insider_name, t.trade_date)
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result
