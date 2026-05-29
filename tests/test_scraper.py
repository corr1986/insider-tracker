"""
Tests for the EDGAR EFTS-based scraper module.

Data flow under test:
  EDGAR EFTS search  → _fetch_efts_filings
  EDGAR archive URL  → _xml_urls
  Form 4 XML         → _parse_form4_xml
  Integration: fetch_all_edgar_transactions (fully mocked HTTP)
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from scraper import (
    InsiderTransaction,
    _fetch_efts_filings,
    _parse_form4_xml,
    _parse_value,
    _xml_urls,
    deduplicate,
    fetch_all_edgar_transactions,
)

# ── Shared constants ──────────────────────────────────────────────────────

_RECENT = (date.today() - timedelta(days=1)).isoformat()
_ISSUER_CIK = "0000320193"
_OWNER_CIK = "0000987654"
_ACCESSION = "0001234567-26-123456"
_DOC_FILENAME = "form4.xml"


# ── Sample data builders ──────────────────────────────────────────────────

def _make_efts_data(
    accession: str = _ACCESSION,
    ciks: list | None = None,
    doc_filename: str = _DOC_FILENAME,
    file_date: str = _RECENT,
) -> dict:
    """Build a realistic EDGAR EFTS response dict with a single hit."""
    if ciks is None:
        ciks = [_ISSUER_CIK]
    return {
        "hits": {
            "hits": [
                {
                    "_id": f"{accession}:{doc_filename}",
                    "_source": {
                        "adsh": accession,
                        "ciks": ciks,
                        "file_date": file_date,
                    },
                }
            ]
        }
    }


def _make_efts_data_multi(*entries: tuple) -> dict:
    """Build EFTS response with multiple hits.

    Each entry is a (accession, ciks, doc_filename, file_date) tuple.
    """
    hits = []
    for accession, ciks, doc_filename, file_date in entries:
        hits.append(
            {
                "_id": f"{accession}:{doc_filename}",
                "_source": {
                    "adsh": accession,
                    "ciks": ciks,
                    "file_date": file_date,
                },
            }
        )
    return {"hits": {"hits": hits}}


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


def _make_json_resp(data: dict, status_code: int = 200) -> MagicMock:
    """Mock a requests.Response for JSON endpoints (EFTS)."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = data
    mock.raise_for_status = MagicMock()
    return mock


def _make_xml_resp(content, status_code: int = 200) -> MagicMock:
    """Mock a requests.Response for XML endpoints (EDGAR archive)."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.content = content.encode() if isinstance(content, str) else content
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


# ── _fetch_efts_filings ───────────────────────────────────────────────────

def test_fetch_efts_filings_returns_filing_metadata():
    session = MagicMock()
    session.get.return_value = _make_json_resp(_make_efts_data())

    result = _fetch_efts_filings(date.today() - timedelta(days=7), date.today(), session)

    assert len(result) == 1
    assert result[0]["adsh"] == _ACCESSION
    assert result[0]["ciks"] == [_ISSUER_CIK]
    assert result[0]["doc_filename"] == _DOC_FILENAME
    assert result[0]["file_date"] == _RECENT


def test_fetch_efts_filings_skips_non_xml_documents():
    session = MagicMock()
    session.get.return_value = _make_json_resp(
        _make_efts_data(doc_filename="form4.htm")
    )

    result = _fetch_efts_filings(date.today() - timedelta(days=7), date.today(), session)

    assert result == []


def test_fetch_efts_filings_skips_id_without_colon():
    session = MagicMock()
    data = {
        "hits": {
            "hits": [
                {
                    "_id": "0001234567-26-123456_form4.xml",  # underscore, no colon
                    "_source": {
                        "adsh": _ACCESSION,
                        "ciks": [_ISSUER_CIK],
                        "file_date": _RECENT,
                    },
                }
            ]
        }
    }
    session.get.return_value = _make_json_resp(data)

    result = _fetch_efts_filings(date.today() - timedelta(days=7), date.today(), session)

    assert result == []


def test_fetch_efts_filings_skips_entry_with_empty_adsh():
    session = MagicMock()
    data = {
        "hits": {
            "hits": [
                {
                    "_id": f"{_ACCESSION}:{_DOC_FILENAME}",
                    "_source": {
                        "adsh": "",  # empty
                        "ciks": [_ISSUER_CIK],
                        "file_date": _RECENT,
                    },
                }
            ]
        }
    }
    session.get.return_value = _make_json_resp(data)

    result = _fetch_efts_filings(date.today() - timedelta(days=7), date.today(), session)

    assert result == []


def test_fetch_efts_filings_skips_entry_with_no_ciks():
    session = MagicMock()
    data = {
        "hits": {
            "hits": [
                {
                    "_id": f"{_ACCESSION}:{_DOC_FILENAME}",
                    "_source": {
                        "adsh": _ACCESSION,
                        "ciks": [],  # empty list
                        "file_date": _RECENT,
                    },
                }
            ]
        }
    }
    session.get.return_value = _make_json_resp(data)

    result = _fetch_efts_filings(date.today() - timedelta(days=7), date.today(), session)

    assert result == []


def test_fetch_efts_filings_returns_empty_on_no_hits():
    session = MagicMock()
    session.get.return_value = _make_json_resp({"hits": {"hits": []}})

    result = _fetch_efts_filings(date.today() - timedelta(days=7), date.today(), session)

    assert result == []


def test_fetch_efts_filings_raises_on_network_error():
    session = MagicMock()
    session.get.side_effect = requests.RequestException("connection refused")

    with pytest.raises(RuntimeError, match="EDGAR EFTS"):
        _fetch_efts_filings(date.today() - timedelta(days=7), date.today(), session)


def test_fetch_efts_filings_raises_on_parse_error():
    session = MagicMock()
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.status_code = 200
    mock.json.side_effect = ValueError("not JSON")
    session.get.return_value = mock

    with pytest.raises(RuntimeError, match="EDGAR EFTS"):
        _fetch_efts_filings(date.today() - timedelta(days=7), date.today(), session)


# ── _xml_urls ─────────────────────────────────────────────────────────────

def test_xml_urls_returns_issuer_cik_first():
    """ciks[-1] is the issuer; its stripped CIK should appear in urls[0]."""
    urls = _xml_urls(_ACCESSION, [_OWNER_CIK, _ISSUER_CIK], _DOC_FILENAME)

    assert len(urls) >= 1
    assert "/320193/" in urls[0]  # issuer CIK without leading zeros


def test_xml_urls_strips_leading_zeros():
    urls = _xml_urls(_ACCESSION, [_ISSUER_CIK], _DOC_FILENAME)

    assert "/320193/" in urls[0]
    assert "/0000320193/" not in urls[0]


def test_xml_urls_removes_dashes_from_accession():
    urls = _xml_urls(_ACCESSION, [_ISSUER_CIK], _DOC_FILENAME)

    acc_nodash = _ACCESSION.replace("-", "")
    assert acc_nodash in urls[0]


def test_xml_urls_includes_fallback_for_reporting_owner():
    """Two different CIKs produce two URLs: issuer first, reporting owner second."""
    urls = _xml_urls(_ACCESSION, [_OWNER_CIK, _ISSUER_CIK], _DOC_FILENAME)

    assert len(urls) == 2
    assert "/320193/" in urls[0]   # issuer (ciks[-1])
    assert "/987654/" in urls[1]   # reporting owner (ciks[0])


def test_xml_urls_deduplicates_identical_ciks():
    """Same CIK appearing twice produces only one URL."""
    urls = _xml_urls(_ACCESSION, [_ISSUER_CIK, _ISSUER_CIK], _DOC_FILENAME)

    assert len(urls) == 1


def test_xml_urls_single_cik_returns_one_url():
    urls = _xml_urls(_ACCESSION, [_ISSUER_CIK], _DOC_FILENAME)

    assert len(urls) == 1
    assert urls[0].endswith(f"/{_DOC_FILENAME}")


def test_xml_urls_skips_all_zero_cik():
    """A CIK of all zeros becomes empty after lstrip('0') and is skipped."""
    urls = _xml_urls(_ACCESSION, ["0000"], _DOC_FILENAME)

    assert urls == []


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
        _make_json_resp(_make_efts_data()),                          # EFTS query
        _make_xml_resp(_make_form4_xml(shares="13510", price="185.00")),  # XML
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
        _make_json_resp(_make_efts_data()),
        _make_xml_resp(_make_form4_xml(shares="10", price="100.00")),
    ]

    txns = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)

    assert txns == []


@patch("scraper.time.sleep")
@patch("scraper.requests.Session")
def test_fetch_all_raises_on_efts_failure(mock_session_cls, mock_sleep):
    session = MagicMock()
    mock_session_cls.return_value = session
    session.get.side_effect = requests.RequestException("connection refused")

    with pytest.raises(RuntimeError, match="EDGAR EFTS"):
        fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)


@patch("scraper.time.sleep")
@patch("scraper.requests.Session")
def test_fetch_all_skips_filing_gracefully_when_xml_fails(mock_session_cls, mock_sleep):
    session = MagicMock()
    mock_session_cls.return_value = session

    session.get.side_effect = [
        _make_json_resp(_make_efts_data()),          # EFTS succeeds
        requests.RequestException("timeout"),         # XML fetch fails
    ]

    txns = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)

    assert txns == []  # gracefully skipped, no exception raised


@patch("scraper.time.sleep")
@patch("scraper.requests.Session")
def test_fetch_all_deduplicates_transactions(mock_session_cls, mock_sleep):
    """Two separate EFTS filings with the same (ticker, insider, date) → deduplicated to 1."""
    session = MagicMock()
    mock_session_cls.return_value = session

    acc2 = "0009876543-26-111111"
    efts_data = _make_efts_data_multi(
        (_ACCESSION, [_ISSUER_CIK], _DOC_FILENAME, _RECENT),
        (acc2, [_ISSUER_CIK], _DOC_FILENAME, _RECENT),
    )

    session.get.side_effect = [
        _make_json_resp(efts_data),        # EFTS: 2 hits
        _make_xml_resp(_make_form4_xml()), # XML for filing 1
        _make_xml_resp(_make_form4_xml()), # XML for filing 2 (same content)
    ]

    txns = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)

    assert len(txns) == 1  # same ticker + insider + date → deduplicated


@patch("scraper.time.sleep")
@patch("scraper.requests.Session")
def test_fetch_all_excludes_sales_transactions(mock_session_cls, mock_sleep):
    session = MagicMock()
    mock_session_cls.return_value = session

    session.get.side_effect = [
        _make_json_resp(_make_efts_data()),
        _make_xml_resp(_make_form4_xml(transaction_code="S")),
    ]

    txns = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)

    assert txns == []


@patch("scraper.time.sleep")
@patch("scraper.requests.Session")
def test_fetch_all_tries_fallback_cik_on_404(mock_session_cls, mock_sleep):
    """When the issuer CIK URL returns 404, the reporting owner CIK is tried."""
    session = MagicMock()
    mock_session_cls.return_value = session

    efts_data = _make_efts_data(ciks=[_OWNER_CIK, _ISSUER_CIK])  # two CIKs

    xml_404 = MagicMock()
    xml_404.status_code = 404

    session.get.side_effect = [
        _make_json_resp(efts_data),         # EFTS
        xml_404,                             # issuer CIK → 404
        _make_xml_resp(_make_form4_xml()),  # owner CIK → 200
    ]

    txns = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)

    assert len(txns) == 1


# ── cik field ─────────────────────────────────────────────────────────────

@patch("scraper.requests.Session")
def test_fetch_all_populates_cik_from_issuer(mock_session_cls):
    """InsiderTransaction.cik is populated from the last element in ciks (issuer)."""
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    efts_data = _make_efts_data(ciks=[_OWNER_CIK, _ISSUER_CIK])
    xml = _make_form4_xml(ticker="AAPL", shares="100", price="500.00")
    mock_session.get.side_effect = [
        _make_json_resp(efts_data),
        _make_xml_resp(xml),
    ]
    results = fetch_all_edgar_transactions(min_value=50_000, lookback_days=7)
    assert len(results) == 1
    assert results[0].cik == _ISSUER_CIK.lstrip("0")


def test_insider_transaction_cik_defaults_to_empty_string():
    """InsiderTransaction can be created without cik (backward-compatible)."""
    from datetime import date
    t = InsiderTransaction("AAPL", "Apple Inc", "Tim Cook", "CEO", 100_000, date(2026, 1, 1))
    assert t.cik == ""
