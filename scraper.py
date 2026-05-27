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
    Returns 0.0 if the string contains no numeric content.
    """
    clean = re.sub(r"[^\d.]", "", value_str)
    return float(clean) if clean else 0.0


def _parse_date(date_str: str) -> Optional[date]:
    """Parse the first 10 characters of a date string in 'YYYY-MM-DD' format.

    Returns None if the string is missing or malformed.
    """
    try:
        return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return None


def parse_transactions(
    html: str, min_value: float, lookback_days: int
) -> List[InsiderTransaction]:
    """Parse an OpenInsider HTML page and return filtered InsiderTransaction list.

    Filters applied:
    - Only open-market purchases (Trade Type == 'P')
    - Trade date within the lookback window (today minus lookback_days)
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
        if len(cols) < 13:
            continue

        # Only include open-market purchases
        if cols[7] != "P":
            continue

        trade_date = _parse_date(cols[2])
        if trade_date is None or trade_date < cutoff:
            continue

        value = _parse_value(cols[12])
        if value < min_value:
            continue

        ticker = cols[3].upper().strip()
        company = cols[4].strip()
        if not ticker or not company:
            continue

        transactions.append(InsiderTransaction(
            ticker=ticker,
            company=company,
            insider_name=cols[5].strip(),
            title=cols[6].strip(),
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
    """Remove duplicate transactions.

    Two transactions are considered duplicates when they share the same
    ticker symbol, insider name, and trade date.  The first occurrence
    in the list is kept; subsequent duplicates are discarded.
    """
    seen: set = set()
    result: List[InsiderTransaction] = []
    for t in transactions:
        key = (t.ticker, t.insider_name, t.trade_date)
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result
