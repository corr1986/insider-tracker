from datetime import date
from scraper import InsiderTransaction
from scorer import score_ticker, score_all, TickerSignal


def make_tx(ticker="AAPL", company="Apple", name="Tim Cook", title="CEO", value=2_500_000):
    return InsiderTransaction(ticker, company, name, title, value, date(2026, 5, 26))


# --- Role scoring ---

def test_ceo_scores_4():
    s = score_ticker("AAPL", [make_tx(title="CEO")])
    assert any("+4" in item for item in s.score_breakdown)

def test_cfo_scores_3():
    s = score_ticker("AAPL", [make_tx(title="CFO")])
    assert any("+3" in item for item in s.score_breakdown)

def test_director_scores_1():
    s = score_ticker("AAPL", [make_tx(title="Director")])
    assert any("+1" in item for item in s.score_breakdown)

def test_chief_executive_officer_detected_as_ceo():
    s = score_ticker("AAPL", [make_tx(title="Chief Executive Officer")])
    assert any("CEO" in item and "+4" in item for item in s.score_breakdown)

def test_chief_financial_officer_detected_as_cfo():
    s = score_ticker("AAPL", [make_tx(title="Chief Financial Officer")])
    assert any("CFO" in item and "+3" in item for item in s.score_breakdown)


# --- Value scoring ---

def test_value_50k_to_100k_scores_1():
    s = score_ticker("AAPL", [make_tx(value=75_000)])
    assert any("≥$50K" in item and "+1" in item for item in s.score_breakdown)

def test_value_100k_to_500k_scores_2():
    s = score_ticker("AAPL", [make_tx(value=200_000)])
    assert any("≥$100K" in item and "+2" in item for item in s.score_breakdown)

def test_value_above_500k_scores_4():
    s = score_ticker("AAPL", [make_tx(value=600_000)])
    assert any("≥$500K" in item and "+4" in item for item in s.score_breakdown)


# --- Cluster scoring ---

def test_cluster_2_scores_3():
    txs = [make_tx(name="Cook"), make_tx(name="Maestri", title="CFO")]
    s = score_ticker("AAPL", txs)
    assert any("Cluster 2" in item and "+3" in item for item in s.score_breakdown)

def test_cluster_3plus_scores_6():
    txs = [make_tx(name="A"), make_tx(name="B", title="CFO"), make_tx(name="C", title="Director")]
    s = score_ticker("AAPL", txs)
    assert any("Cluster 3" in item and "+6" in item for item in s.score_breakdown)

def test_cluster_total_above_500k_scores_3():
    txs = [make_tx(name="A", value=300_000), make_tx(name="B", title="CFO", value=300_000)]
    s = score_ticker("AAPL", txs)
    assert any("Totale" in item and "+3" in item for item in s.score_breakdown)

def test_cluster_total_below_500k_no_bonus():
    txs = [make_tx(name="A", value=100_000), make_tx(name="B", title="CFO", value=100_000)]
    s = score_ticker("AAPL", txs)
    assert not any("Totale" in item for item in s.score_breakdown)


# --- score_all ---

def test_score_all_groups_by_ticker():
    txs = [
        make_tx(ticker="AAPL", name="Cook"),
        make_tx(ticker="AAPL", name="Maestri", title="CFO"),
        make_tx(ticker="MSFT", company="Microsoft", name="Nadella"),
    ]
    tickers = [s.ticker for s in score_all(txs)]
    assert "AAPL" in tickers
    assert "MSFT" in tickers

def test_score_all_sorted_descending():
    txs = [
        make_tx(ticker="MSFT", company="Microsoft", name="Nadella", value=60_000),
        make_tx(ticker="AAPL", name="Cook", value=2_500_000),
        make_tx(ticker="AAPL", name="Maestri", title="CFO", value=800_000),
        make_tx(ticker="AAPL", name="Williams", title="Director", value=120_000),
    ]
    signals = score_all(txs)
    assert signals[0].ticker == "AAPL"
