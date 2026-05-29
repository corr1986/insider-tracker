"""
Scraper module for InsiderTracker.

Fetches and parses SEC Form 4 insider purchase data from EDGAR.
Data source: https://www.sec.gov (official US government — globally accessible)

Data flow:
  1. EDGAR EFTS full-text search  → list of Form 4 filings with metadata
  2. Direct XML fetch              → Form 4 raw XML per filing
  3. Form 4 XML parsing            → InsiderTransaction objects (purchases only)

EDGAR EFTS (https://efts.sec.gov/LATEST/search-index) supports date-range queries
for all Form 4 filings. The ``_id`` field encodes the XML document path:
  ``{accession_no}:{xml_filename}``

The XML URL is built directly:
  ``/Archives/edgar/data/{issuer_cik}/{acc_nodashes}/{xml_filename}``

where ``issuer_cik`` = last element in the ``ciks`` array (EDGAR convention for Form 4).
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

# ── EDGAR endpoints ───────────────────────────────────────────────────────

_EDGAR_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

# EDGAR requires a User-Agent header with contact info (policy: <10 req/s)
_EDGAR_HEADERS = {
    "User-Agent": "InsiderTracker/1.0 corradocuri@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}
_REQUEST_DELAY = 0.12   # seconds between requests (~8 req/s, within EDGAR policy)
_EDGAR_MAX_FILINGS = 200  # max Form 4 filings to process per run (~2 business days)


# ── Data classes ──────────────────────────────────────────────────────────

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


# ── Value / date helpers ──────────────────────────────────────────────────

def _parse_value(value_str: str) -> float:
    """Parse a dollar-formatted string to float.

    Strips all non-numeric characters except the decimal point.
    Returns 0.0 if the string is empty, contains multiple dots, or is
    otherwise unparseable.
    """
    clean = re.sub(r"[^\d.]", "", value_str)
    if not clean or clean.count(".") > 1:
        return 0.0
    try:
        return float(clean)
    except ValueError:
        return 0.0


def _parse_date(date_str: str) -> Optional[date]:
    """Parse the first 10 characters of a date string in 'YYYY-MM-DD' format.

    Returns None if the string is missing or malformed.
    """
    try:
        return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return None


# ── Deduplication ─────────────────────────────────────────────────────────

def deduplicate(transactions: List[InsiderTransaction]) -> List[InsiderTransaction]:
    """Remove duplicate transactions (same ticker + insider name + trade date).

    Transactions with trade_date=None are always kept (cannot deduplicate
    without a date). The first occurrence of each key is kept; subsequent
    duplicates are discarded.
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


# ── EDGAR EFTS filing list ────────────────────────────────────────────────

def _fetch_efts_filings(
    start: date,
    end: date,
    session: requests.Session,
    max_results: int = _EDGAR_MAX_FILINGS,
) -> list[dict]:
    """Query EDGAR EFTS for Form 4 filings in the given date range.

    Returns a list of dicts with keys: ``adsh``, ``ciks``, ``doc_filename``,
    ``file_date``.

    The EFTS ``_id`` field encodes both the accession number and XML filename:
    ``"{adsh}:{doc_filename}"``

    The ``ciks`` list follows the EDGAR convention for Form 4:
    - ``ciks[-1]`` = issuer (company whose securities are being reported)
    - ``ciks[0]``  = reporting owner (the insider)

    Raises RuntimeError on network or parse failure.
    """
    params = {
        "forms": "4",
        "dateRange": "custom",
        "startdt": start.isoformat(),
        "enddt": end.isoformat(),
        "from": "0",
        "size": str(min(max_results, 200)),  # EFTS page size cap
    }
    try:
        resp = session.get(_EDGAR_EFTS_URL, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch EDGAR EFTS filings: {exc}") from exc

    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"Failed to parse EDGAR EFTS response: {exc}") from exc

    results = []
    for hit in data.get("hits", {}).get("hits", []):
        _id = hit.get("_id", "")
        source = hit.get("_source", {})

        # _id format: "{adsh}:{doc_filename}"
        if ":" not in _id:
            continue
        _, doc_filename = _id.rsplit(":", 1)
        if not doc_filename.lower().endswith(".xml"):
            continue  # skip non-XML documents

        adsh = source.get("adsh", "").strip()
        if not adsh:
            continue

        ciks = source.get("ciks", [])
        if not ciks:
            continue

        results.append({
            "adsh": adsh,
            "ciks": ciks,
            "doc_filename": doc_filename,
            "file_date": source.get("file_date", "").strip(),
        })

    return results


# ── Form 4 XML URL resolution ─────────────────────────────────────────────

def _xml_urls(adsh: str, ciks: list[str], doc_filename: str) -> list[str]:
    """Return candidate XML URLs in order of preference.

    Tries the ISSUER's CIK first (``ciks[-1]``, EDGAR convention for Form 4),
    then falls back to the reporting owner's CIK (``ciks[0]``).
    """
    acc_path = adsh.replace("-", "")
    seen: set = set()
    urls = []
    for cik in reversed(ciks):  # reversed: last = issuer, first = reporting owner
        cik_str = cik.lstrip("0")
        if cik_str and cik_str not in seen:
            seen.add(cik_str)
            urls.append(f"{_EDGAR_ARCHIVES}/{cik_str}/{acc_path}/{doc_filename}")
    return urls


# ── Form 4 XML parsing ────────────────────────────────────────────────────

def _extract_title(owner_elem: ET.Element) -> str:
    """Extract the officer title or role from a reportingOwner element."""
    rel = owner_elem.find(".//reportingOwnerRelationship")
    if rel is None:
        return ""
    officer_title = (rel.findtext("officerTitle") or "").strip()
    if officer_title:
        return officer_title
    if (rel.findtext("isDirector") or "").strip() == "1":
        return "Director"
    if (rel.findtext("isOfficer") or "").strip() == "1":
        return "Officer"
    return ""


def _parse_form4_xml(xml_content: str | bytes) -> list[dict]:
    """Parse a Form 4 XML document and return purchase transaction dicts.

    Only transactions with ``transactionCode == 'P'`` (open-market purchase)
    and a positive computed value (shares × price) are returned.

    Each returned dict has keys:
      ticker, company, insider_name, title, trade_date (Optional[date]), value (float)

    Returns an empty list on malformed XML or missing issuer/owner data.
    """
    if isinstance(xml_content, bytes):
        xml_content = xml_content.decode("utf-8", errors="replace")

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return []

    # ── Issuer (company) info ─────────────────────────────────────────
    issuer = root.find(".//issuer")
    if issuer is None:
        return []
    ticker = (issuer.findtext("issuerTradingSymbol") or "").strip().upper()
    company = (issuer.findtext("issuerName") or "").strip()
    if not ticker:
        return []

    # ── Reporting owner (insider) info ────────────────────────────────
    owner = root.find(".//reportingOwner")
    if owner is None:
        return []
    insider_name = (owner.findtext(".//rptOwnerName") or "").strip()
    title = _extract_title(owner)

    # ── Transaction records ───────────────────────────────────────────
    results = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        code = (txn.findtext(".//transactionCode") or "").strip()
        if code != "P":
            continue

        # Trade date (nested <value> or direct text)
        date_raw = (
            txn.findtext(".//transactionDate/value")
            or txn.findtext(".//transactionDate")
            or ""
        ).strip()
        trade_date = _parse_date(date_raw)

        # Value = shares × price per share
        shares_raw = (
            txn.findtext(".//transactionShares/value")
            or txn.findtext(".//transactionShares")
            or ""
        ).strip()
        price_raw = (
            txn.findtext(".//transactionPricePerShare/value")
            or txn.findtext(".//transactionPricePerShare")
            or ""
        ).strip()

        value = _parse_value(shares_raw) * _parse_value(price_raw)
        if value <= 0:
            continue

        results.append({
            "ticker": ticker,
            "company": company,
            "insider_name": insider_name,
            "title": title,
            "trade_date": trade_date,
            "value": value,
        })

    return results


# ── Main public function ──────────────────────────────────────────────────

def fetch_all_edgar_transactions(
    min_value: float, lookback_days: int
) -> List[InsiderTransaction]:
    """Fetch recent insider purchase transactions from SEC EDGAR.

    Steps:
      1. Query EDGAR EFTS for all Form 4 filings in the lookback window.
         Processes up to ``_EDGAR_MAX_FILINGS`` most recent filings.
      2. For each filing, fetch the Form 4 raw XML directly using the
         issuer CIK and document filename from the EFTS response.
      3. Parse the XML for open-market purchases (transactionCode='P')
         with value >= min_value.
      4. Return a deduplicated list of InsiderTransaction objects.

    Raises RuntimeError if the EFTS query fails (caller retries).
    Individual filing failures are skipped gracefully (logged at DEBUG).
    """
    cutoff = date.today() - timedelta(days=lookback_days)
    session = requests.Session()
    session.headers.update(_EDGAR_HEADERS)

    # Step 1: EFTS filing list
    filings = _fetch_efts_filings(cutoff, date.today(), session)
    all_txns: list[InsiderTransaction] = []

    for filing in filings:
        time.sleep(_REQUEST_DELAY)

        # Step 2: Fetch Form 4 XML (try issuer CIK first, then reporting owner)
        xml_content: bytes | None = None
        for url in _xml_urls(filing["adsh"], filing["ciks"], filing["doc_filename"]):
            try:
                xml_resp = session.get(url, timeout=20)
                if xml_resp.status_code == 200:
                    xml_content = xml_resp.content
                    break
                if xml_resp.status_code == 404:
                    continue  # try next CIK
                xml_resp.raise_for_status()
            except requests.RequestException:
                continue

        if xml_content is None:
            logger.debug("Could not fetch XML for %s", filing["adsh"])
            continue

        # Step 3: Parse and filter
        for t in _parse_form4_xml(xml_content):
            if t["value"] >= min_value:
                all_txns.append(InsiderTransaction(
                    ticker=t["ticker"],
                    company=t["company"],
                    insider_name=t["insider_name"],
                    title=t["title"],
                    value=t["value"],
                    trade_date=t["trade_date"],
                    cik=filing["ciks"][-1].lstrip("0") if filing["ciks"] else "",
                ))

    return deduplicate(all_txns)
