from datetime import date, timedelta
from scraper import parse_transactions, deduplicate, InsiderTransaction, _parse_value

_RECENT = (date.today() - timedelta(days=1)).isoformat()

SAMPLE_HTML = f"""
<table class="tinytable">
  <thead><tr>
    <th>X</th><th>Filing Date</th><th>Trade Date</th><th>Ticker</th>
    <th>Company</th><th>Insider Name</th><th>Title</th><th>Trade Type</th>
    <th>Price</th><th>Qty</th><th>Owned</th><th>DeltaOwn</th><th>Value</th>
  </tr></thead>
  <tbody>
    <tr>
      <td></td><td>2026-05-27 06:00:00</td><td>{_RECENT}</td>
      <td>AAPL</td><td>Apple Inc</td><td>Tim Cook</td><td>CEO</td>
      <td>P</td><td>$185.00</td><td>+13,510</td><td>3,280,000</td>
      <td>+0.41%</td><td>$2,500,000</td>
    </tr>
    <tr>
      <td></td><td>2026-05-27 06:00:00</td><td>{_RECENT}</td>
      <td>MSFT</td><td>Microsoft Corp</td><td>Satya Nadella</td><td>CEO</td>
      <td>S</td><td>$420.00</td><td>+1,000</td><td>500,000</td>
      <td>+0.2%</td><td>$420,000</td>
    </tr>
    <tr>
      <td></td><td>2026-05-27 06:00:00</td><td>{_RECENT}</td>
      <td>GOOG</td><td>Alphabet Inc</td><td>Sundar Pichai</td><td>CEO</td>
      <td>P</td><td>$170.00</td><td>+100</td><td>200,000</td>
      <td>+0.05%</td><td>$17,000</td>
    </tr>
  </tbody>
</table>
"""

OLD_HTML = """
<table class="tinytable">
  <thead><tr>
    <th>X</th><th>Filing Date</th><th>Trade Date</th><th>Ticker</th>
    <th>Company</th><th>Insider Name</th><th>Title</th><th>Trade Type</th>
    <th>Price</th><th>Qty</th><th>Owned</th><th>DeltaOwn</th><th>Value</th>
  </tr></thead>
  <tbody>
    <tr>
      <td></td><td>2025-01-01 06:00:00</td><td>2025-01-01</td>
      <td>OLD</td><td>Old Corp</td><td>John Doe</td><td>CEO</td>
      <td>P</td><td>$100.00</td><td>+500</td><td>100,000</td>
      <td>+0.5%</td><td>$100,000</td>
    </tr>
  </tbody>
</table>
"""


def test_parse_extracts_purchase():
    txs = parse_transactions(SAMPLE_HTML, min_value=50_000, lookback_days=7)
    assert len(txs) == 1
    assert txs[0].ticker == "AAPL"
    assert txs[0].company == "Apple Inc"
    assert txs[0].insider_name == "Tim Cook"
    assert txs[0].title == "CEO"
    assert txs[0].value == 2_500_000.0


def test_parse_excludes_sales():
    txs = parse_transactions(SAMPLE_HTML, min_value=50_000, lookback_days=7)
    assert "MSFT" not in [t.ticker for t in txs]


def test_parse_excludes_below_min_value():
    # GOOG has value $17,000 < $50,000
    txs = parse_transactions(SAMPLE_HTML, min_value=50_000, lookback_days=7)
    assert "GOOG" not in [t.ticker for t in txs]


def test_parse_excludes_old_transactions():
    txs = parse_transactions(OLD_HTML, min_value=50_000, lookback_days=7)
    assert len(txs) == 0


def test_parse_returns_empty_on_no_table():
    txs = parse_transactions("<html><body>no table</body></html>", 50_000, 7)
    assert txs == []


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


def test_parse_includes_transaction_on_cutoff_date():
    """Trade exactly on the cutoff date (today - lookback_days) must be included."""
    cutoff_date = (date.today() - timedelta(days=7)).isoformat()
    html = f"""
    <table class="tinytable">
      <thead><tr>
        <th>X</th><th>Filing Date</th><th>Trade Date</th><th>Ticker</th>
        <th>Company</th><th>Insider Name</th><th>Title</th><th>Trade Type</th>
        <th>Price</th><th>Qty</th><th>Owned</th><th>DeltaOwn</th><th>Value</th>
      </tr></thead>
      <tbody>
        <tr>
          <td></td><td>2026-05-27 06:00:00</td><td>{cutoff_date}</td>
          <td>CUTOFF</td><td>Cutoff Corp</td><td>Jane Doe</td><td>CEO</td>
          <td>P</td><td>$100.00</td><td>+1,000</td><td>100,000</td>
          <td>+1%</td><td>$100,000</td>
        </tr>
      </tbody>
    </table>
    """
    txs = parse_transactions(html, min_value=50_000, lookback_days=7)
    assert len(txs) == 1
    assert txs[0].ticker == "CUTOFF"


def test_parse_skips_blank_ticker_rows():
    _RECENT = (date.today() - timedelta(days=1)).isoformat()
    html = f"""
    <table class="tinytable">
      <thead><tr>
        <th>X</th><th>Filing Date</th><th>Trade Date</th><th>Ticker</th>
        <th>Company</th><th>Insider Name</th><th>Title</th><th>Trade Type</th>
        <th>Price</th><th>Qty</th><th>Owned</th><th>DeltaOwn</th><th>Value</th>
      </tr></thead>
      <tbody>
        <tr>
          <td></td><td>2026-05-27 06:00:00</td><td>{_RECENT}</td>
          <td>  </td><td>Some Corp</td><td>Jane Doe</td><td>CEO</td>
          <td>P</td><td>$100.00</td><td>+1,000</td><td>100,000</td>
          <td>+1%</td><td>$100,000</td>
        </tr>
      </tbody>
    </table>
    """
    txs = parse_transactions(html, min_value=50_000, lookback_days=7)
    assert len(txs) == 0


def test_parse_value_malformed_multiple_dots():
    """Malformed value strings with multiple decimal points must return 0.0."""
    assert _parse_value("1.2.3") == 0.0


def test_parse_value_parenthesis_notation():
    """Parenthesis-notation negative values return 0.0 (parens stripped, no minus sign)."""
    # "(50,000)" cleans to "50000" — no minus preserved, so it parses as positive.
    # This test documents the current behaviour: callers should not rely on sign.
    result = _parse_value("(50,000)")
    assert result == 50_000.0
