"""
Scraper module for InsiderTracker.

Fetches and parses SEC Form 4 insider purchase data from EDGAR.
Data source: https://www.sec.gov (official US government — no geo-blocks)

Data flow:
  1. EDGAR Atom feed  → list of (CIK, accession_no, filing_date)
  2. Filing index HTML → XML document URL
  3. Form 4 XML        → InsiderTransaction objects (purchases only)
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
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── EDGAR endpoints ───────────────────────────────────────────────────────

# Atom feed for the 100 most recently accepted Form 4 filings
_EDGAR_ATOM_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=4&dateb=&owner=include&count=100&output=atom"
)
_EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
_EDGAR_BASE = "https://www.sec.gov"

# EDGAR requires a User-Agent with contact info (rate limit: <10 req/s)
_EDGAR_HEADERS = {
    "User-Agent": "InsiderTracker/1.0 corradocuri@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}
_REQUEST_DELAY = 0.12  # seconds between requests (~8 req/s, within EDGAR policy)

# Standard Atom XML namespace
_ATOM_NS = "http://www.w3.org/2005/Atom"


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


# ── EDGAR Atom feed parsing ───────────────────────────────────────────────

def _parse_atom_entries(atom_xml: bytes) -> list[dict]:
    """Parse EDGAR Atom feed XML into a list of filing metadata dicts.

    Each dict has keys: ``cik``, ``accession_no``, ``filing_date``.
    Entries missing a CIK or accession number are silently skipped.

    Raises RuntimeError on malformed XML.
    """
    try:
        root = ET.fromstring(atom_xml)
    except ET.ParseError as exc:
        raise RuntimeError(f"Failed to parse EDGAR Atom feed XML: {exc}") from exc

    entries = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        # ── Accession number from <id> ──────────────────────────────────
        id_elem = entry.find(f"{{{_ATOM_NS}}}id")
        id_text = (id_elem.text or "").strip() if id_elem is not None else ""
        acc_match = re.search(r"accession-number=(\d{10}-\d{2}-\d{6})", id_text)
        if not acc_match:
            continue
        accession_no = acc_match.group(1)

        # ── CIK from <link href="...?...CIK=XXXXXXXXXX..."> ────────────
        cik = ""
        link_elem = entry.find(f"{{{_ATOM_NS}}}link")
        if link_elem is not None:
            href = link_elem.get("href", "")
            cik_match = re.search(r"CIK=(\d+)", href, re.IGNORECASE)
            if cik_match:
                cik = cik_match.group(1).lstrip("0")

        if not cik:
            continue

        # ── Filing date from <updated> ──────────────────────────────────
        updated_elem = entry.find(f"{{{_ATOM_NS}}}updated")
        updated_text = (updated_elem.text or "").strip() if updated_elem is not None else ""
        filing_date = updated_text[:10]  # "YYYY-MM-DD" (trim time component)

        entries.append({
            "cik": cik,
            "accession_no": accession_no,
            "filing_date": filing_date,
        })

    return entries


# ── Filing index parsing ──────────────────────────────────────────────────

def _index_url(cik: str, accession_no: str) -> str:
    """Build the EDGAR filing index URL from CIK and accession number."""
    acc_path = accession_no.replace("-", "")
    return f"{_EDGAR_ARCHIVES}/{cik}/{acc_path}/{accession_no}-index.htm"


def _find_xml_in_index(index_html: str) -> Optional[str]:
    """Find the primary Form 4 XML document path from a filing index HTML page.

    Returns the href string (absolute or relative) of the first link whose
    name ends with ``.xml`` and does not contain "index".
    Returns None if no matching link is found.
    """
    soup = BeautifulSoup(index_html, "html.parser")
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.lower().endswith(".xml") and "index" not in href.lower():
            return href
    return None


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
      1. Fetch the EDGAR Atom feed for the 100 most recent Form 4 filings.
      2. For each filing within the lookback window:
         a. Fetch the filing index HTML to locate the Form 4 XML document.
         b. Fetch and parse the Form 4 XML.
         c. Filter for purchases (transactionCode='P') with value >= min_value.
      3. Return a deduplicated list of InsiderTransaction objects.

    Raises RuntimeError if the Atom feed cannot be fetched (after caller retry).
    Individual filing failures are logged at DEBUG level and skipped gracefully.
    """
    cutoff = date.today() - timedelta(days=lookback_days)
    session = requests.Session()
    session.headers.update(_EDGAR_HEADERS)

    # Step 1: Atom feed
    try:
        resp = session.get(_EDGAR_ATOM_URL, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch EDGAR Atom feed: {exc}") from exc

    entries = _parse_atom_entries(resp.content)
    all_txns: list[InsiderTransaction] = []

    for entry in entries:
        # Skip filings older than the lookback window
        filing_date = _parse_date(entry.get("filing_date", ""))
        if filing_date is not None and filing_date < cutoff:
            continue

        cik = entry["cik"]
        accession_no = entry["accession_no"]

        time.sleep(_REQUEST_DELAY)

        # Step 2a: Filing index → XML URL
        try:
            idx_resp = session.get(_index_url(cik, accession_no), timeout=20)
            idx_resp.raise_for_status()
        except requests.RequestException:
            logger.debug("Skipping filing %s/%s — index fetch failed", cik, accession_no)
            continue

        xml_path = _find_xml_in_index(idx_resp.text)
        if not xml_path:
            logger.debug("No XML found in index for %s/%s", cik, accession_no)
            continue

        xml_url = xml_path if xml_path.startswith("http") else _EDGAR_BASE + xml_path

        time.sleep(_REQUEST_DELAY)

        # Step 2b: Fetch and parse Form 4 XML
        try:
            xml_resp = session.get(xml_url, timeout=20)
            xml_resp.raise_for_status()
        except requests.RequestException:
            logger.debug("Skipping XML fetch failed: %s", xml_url)
            continue

        # Step 2c: Filter purchases by min_value
        for t in _parse_form4_xml(xml_resp.content):
            if t["value"] >= min_value:
                all_txns.append(InsiderTransaction(
                    ticker=t["ticker"],
                    company=t["company"],
                    insider_name=t["insider_name"],
                    title=t["title"],
                    value=t["value"],
                    trade_date=t["trade_date"],
                ))

    return deduplicate(all_txns)
