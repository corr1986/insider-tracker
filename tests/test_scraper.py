"""
Tests for the EDGAR-based scraper module.

Data flow under test:
  EDGAR Atom feed → _parse_atom_entries
  Filing index HTML → _find_xml_in_index
  Form 4 XML → _parse_form4_xml
  Integration: fetch_all_edgar_transactions (fully mocked HTTP)
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from scraper import (
    InsiderTransaction,
    _find_xml_in_index,
    _parse_atom_entries,
    _parse_form4_xml,
    _parse_value,
    deduplicate,
    fetch_all_edgar_transactions,
)

# ── Shared constants ──────────────────────────────────────────────────────

_RECENT = (date.today() - timedelta(days=1)).isoformat()
_CIK = "320193"
_ACCESSION = "0001234567-26-123456"


# ── Sample data builders ──────────────────────────────────────────────────

def _make_atom_feed(cik: str, accession: str, filing_date: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>EDGAR Form 4 Feed</title>
  <entry>
    <title type="html">4 - APPLE INC (0000320193) (Subject)</title>
    <link rel="alternate" type="text/html"
          href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK={cik}&amp;type=4"/>
    <id>urn:tag:sec.gov,2008:accession-number={accession}</id>
    <updated>{filing_date}T10:00:00-04:00</updated>
    <summary type="html">Filed: {filing_date}</summary>
  </entry>
</feed>""".encode()


def _make_index_html(xml_filename: str) -> str:
    acc_path = _ACCESSION.replace("-", "")
    return f"""<html><body>
<table>
  <tr><td><a href="/Archives/edgar/data/{_CIK}/{acc_path}/{xml_filename}">{xml_filename}</a></td></tr>
</table>
</body></html>"""


def _make_form4_xml(
    ticker="AAPL",
    company="Apple Inc",
    insider_name="Tim Cook",
    officer_title="Chief Executive Officer",
    trade_date=_RECENT,
    shares="13510",
    price="185.00",
    transaction_code="P",
) -> str:
    return f"""<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>{company}</issuerName>
    <issuerTradingSymbol>{ticker}</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerName>{insider_name}</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle>{officer_title}</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>{trade_date}</value></transactionDate>
      <transactionCoding>
        <transactionCode>{transaction_code}</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>{shares}</value></transactionShares>
        <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def _make_mock_resp(content, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    if isinstance(content, bytes):
        mock.content = content
        mock.text = content.decode("utf-8", errors="replace")
    else:
        mock.content = content.encode()
        mock.text = content
    mock.raise_for_status = MagicMock()
    return mock


# ── _parse_value ──────────────────────────────────────────────────────────

def test_parse_value_dollar_formatted():
    assert _parse_value("$1,234,567") == 1_234_567.0


def test_parse_value_plain_float():
    assert _parse_value("185.00") == 185.0


def test_parse_value_multiple_dots_returns_zero():
    assert _parse_value("1.2.3") == 0.0


def test_parse_value_empty_returns_zero():
    assert _parse_value("") == 0.0


def test_parse_value_parenthesis_notation():
    # "(50,000)" → strips parens → "50000" → 50000.0
    assert _parse_value("(50,000)") == 50_000.0


# ── _parse_atom_entries ───────────────────────────────────────────────────

def test_parse_atom_extracts_cik():
    entries = _parse_atom_entries(_make_atom_feed(_CIK, _ACCESSION, _RECENT))
    assert len(entries) == 1
    assert entries[0]["cik"] == _CIK


def test_parse_atom_extracts_accession():
    entries = _parse_atom_entries(_make_atom_feed(_CIK, _ACCESSION, _RECENT))
    assert entries[0]["accession_no"] == _ACCESSION


def test_parse_atom_extracts_filing_date():
    entries = _parse_atom_entries(_make_atom_feed(_CIK, _ACCESSION, _RECENT))
    assert entries[0]["filing_date"] == _RECENT


def test_parse_atom_strips_leading_zeros_from_cik():
    # CIK "0000320193" in href → stripped to "320193"
    entries = _parse_atom_entries(_make_atom_feed("0000320193", _ACCESSION, _RECENT))
    assert entries[0]["cik"] == "320193"


def test_parse_atom_skips_entry_without_cik():
    atom_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <link rel="alternate" href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;type=4"/>
    <id>urn:tag:sec.gov,2008:accession-number=0001234567-26-999999</id>
    <updated>2026-05-27T10:00:00-04:00</updated>
  </entry>
</feed>"""
    assert _parse_atom_entries(atom_xml) == []


def test_parse_atom_returns_empty_on_empty_feed():
    atom_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>"""
    assert _parse_atom_entries(atom_xml) == []


def test_parse_atom_raises_on_malformed_xml():
    with pytest.raises(RuntimeError, match="Atom"):
        _parse_atom_entries(b"this is not xml at all <<<")


# ── _find_xml_in_index ────────────────────────────────────────────────────

def test_find_xml_finds_named_xml():
    html = _make_index_html("wf-form4_12345.xml")
    result = _find_xml_in_index(html)
    assert result is not None
    assert result.endswith("wf-form4_12345.xml")


def test_find_xml_returns_none_when_no_xml_link():
    html = "<html><body><a href='doc.htm'>Document</a></body></html>"
    assert _find_xml_in_index(html) is None


def test_find_xml_skips_index_xml_files():
    # Files with "index" in their name should be skipped
    html = "<html><body><a href='/Archives/edgar/data/1/000/0001-26-001-index.xml'>idx</a></body></html>"
    assert _find_xml_in_index(html) is None


def test_find_xml_returns_absolute_or_relative_path():
    html = _make_index_html("form4.xml")
    result = _find_xml_in_index(html)
    # Must be either an absolute URL or a /path
    assert result is not None
    assert "form4.xml" in result


# ── _parse_form4_xml ──────────────────────────────────────────────────────

def test_form4_extracts_ticker():
    results = _parse_form4_xml(_make_form4_xml())
    assert results[0]["ticker"] == "AAPL"


def test_form4_extracts_company():
    results = _parse_form4_xml(_make_form4_xml())
    assert results[0]["company"] == "Apple Inc"


def test_form4_extracts_insider_name():
    results = _parse_form4_xml(_make_form4_xml())
    assert results[0]["insider_name"] == "Tim Cook"


def test_form4_extracts_officer_title():
    results = _parse_form4_xml(_make_form4_xml(officer_title="Chief Financial Officer"))
    assert results[0]["title"] == "Chief Financial Officer"


def test_form4_calculates_value_shares_times_price():
    results = _parse_form4_xml(_make_form4_xml(shares="13510", price="185.00"))
    assert results[0]["value"] == pytest.approx(13510 * 185.0)


def test_form4_extracts_trade_date():
    results = _parse_form4_xml(_make_form4_xml(trade_date=_RECENT))
    assert results[0]["trade_date"] == date.fromisoformat(_RECENT)


def test_form4_excludes_sales():
    results = _parse_form4_xml(_make_form4_xml(transaction_code="S"))
    assert results == []


def test_form4_excludes_disposals():
    results = _parse_form4_xml(_make_form4_xml(transaction_code="D"))
    assert results == []


def test_form4_skips_empty_ticker():
    results = _parse_form4_xml(_make_form4_xml(ticker=""))
    assert results == []


def test_form4_returns_empty_on_malformed_xml():
    results = _parse_form4_xml("this is not xml <<<")
    assert results == []


def test_form4_returns_empty_on_zero_value():
    results = _parse_form4_xml(_make_form4_xml(shares="0", price="185.00"))
    assert results == []


def test_form4_director_role_when_no_officer_title():
    xml = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerName>Acme Inc</issuerName>
    <issuerTradingSymbol>ACME</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Jane Smith</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>0</isOfficer>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-05-27</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>100.00</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""
    results = _parse_form4_xml(xml)
    assert len(results) == 1
    assert results[0]["title"] == "Director"


# ── deduplicate ───────────────────────────────────────────────────────────

def test_deduplicate_removes_same_ticker_insider_date():
    tx = InsiderTransaction(
        ticker="AAPL", company="Apple", insider_name="Tim Cook",
        title="CEO", value=1_000_000, trade_date=date(2026, 5, 26),
    )
    assert len(deduplicate([tx, tx])) == 1


def test_deduplicate_keeps_different_insiders():
    tx1 = InsiderTransaction("AAPL", "Apple", "Tim Cook", "CEO", 1_000_000, date(2026, 5, 26))
    tx2 = InsiderTransaction("AAPL", "Apple", "Luca Maestri", "CFO", 500_000, date(2026, 5, 26))
    assert len(deduplicate([tx1, tx2])) == 2


def test_deduplicate_always_keeps_none_trade_date():
    tx = InsiderTransaction("AAPL", "Apple", "Tim Cook", "CEO", 1_000_000, None)
    assert len(deduplicate([tx, tx])) == 2


# ── fetch_all_edgar_transactions (integration, HTTP mocked) ──────────────

@patch("scraper.time.sleep")
@patch("scraper.requests.Session")
def test_fetch_all_returns_purchase_above_min_value(mock_session_cls, mock_sleep):
    session = MagicMock()
    mock_session_cls.return_value = session

    session.get.side_effect = [
        _make_mock_resp(_make_atom_feed(_CIK, _ACCESSION, _RECENT)),
        _make_mock_resp(_make_index_html("form4.xml")),
        _make_mock_resp(_make_form4_xml(shares="13510", price="185.00")),
    ]

    txns = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)
    assert len(txns) == 1
    assert txns[0].ticker == "AAPL"
    assert txns[0].insider_name == "Tim Cook"


@patch("scraper.time.sleep")
@patch("scraper.requests.Session")
def test_fetch_all_excludes_below_min_value(mock_session_cls, mock_sleep):
    session = MagicMock()
    mock_session_cls.return_value = session

    # 10 shares × $100 = $1,000 < $50,000
    session.get.side_effect = [
        _make_mock_resp(_make_atom_feed(_CIK, _ACCESSION, _RECENT)),
        _make_mock_resp(_make_index_html("form4.xml")),
        _make_mock_resp(_make_form4_xml(shares="10", price="100.00")),
    ]

    txns = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)
    assert txns == []


@patch("scraper.time.sleep")
@patch("scraper.requests.Session")
def test_fetch_all_skips_old_filings_without_extra_requests(mock_session_cls, mock_sleep):
    session = MagicMock()
    mock_session_cls.return_value = session

    old_date = (date.today() - timedelta(days=30)).isoformat()
    session.get.return_value = _make_mock_resp(_make_atom_feed(_CIK, _ACCESSION, old_date))

    txns = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)
    assert txns == []
    # Only the Atom feed request was made; no index/XML requests for old filings
    assert session.get.call_count == 1


@patch("scraper.time.sleep")
@patch("scraper.requests.Session")
def test_fetch_all_raises_runtime_error_on_atom_failure(mock_session_cls, mock_sleep):
    session = MagicMock()
    mock_session_cls.return_value = session
    session.get.side_effect = requests.RequestException("connection refused")

    with pytest.raises(RuntimeError, match="EDGAR Atom feed"):
        fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)


@patch("scraper.time.sleep")
@patch("scraper.requests.Session")
def test_fetch_all_skips_filing_gracefully_when_index_fails(mock_session_cls, mock_sleep):
    session = MagicMock()
    mock_session_cls.return_value = session

    session.get.side_effect = [
        _make_mock_resp(_make_atom_feed(_CIK, _ACCESSION, _RECENT)),
        requests.RequestException("timeout"),  # filing index request fails
    ]

    txns = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)
    assert txns == []  # gracefully skipped, no exception raised


@patch("scraper.time.sleep")
@patch("scraper.requests.Session")
def test_fetch_all_deduplicates_identical_transactions(mock_session_cls, mock_sleep):
    session = MagicMock()
    mock_session_cls.return_value = session

    atom = _make_atom_feed(_CIK, _ACCESSION, _RECENT)
    idx = _make_index_html("form4.xml")
    xml = _make_form4_xml()

    # Two identical filings (same ticker, insider, date)
    session.get.side_effect = [
        _make_mock_resp(atom),
        _make_mock_resp(idx),
        _make_mock_resp(xml),
    ]

    txns = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)
    assert len(txns) == 1


@patch("scraper.time.sleep")
@patch("scraper.requests.Session")
def test_fetch_all_excludes_sales_transactions(mock_session_cls, mock_sleep):
    session = MagicMock()
    mock_session_cls.return_value = session

    session.get.side_effect = [
        _make_mock_resp(_make_atom_feed(_CIK, _ACCESSION, _RECENT)),
        _make_mock_resp(_make_index_html("form4.xml")),
        _make_mock_resp(_make_form4_xml(transaction_code="S")),
    ]

    txns = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)
    assert txns == []
