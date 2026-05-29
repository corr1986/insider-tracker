"""Tests for company_analyzer module."""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scraper import InsiderTransaction
from company_analyzer import (
    fetch_company_history,
    score_and_filter,
    backtest,
    BacktestResult,
    Recommendation,
    generate_recommendation,
    build_message,
    analyze,
)


# ── Shared helpers ────────────────────────────────────────────────────────

_TICKER = "MIMI"
_CIK = "1998560"
_CIK_PADDED = "0001998560"
_OTHER_CIK = "0000111111"


def _make_tx(
    ticker=_TICKER,
    insider="Chan Hoi Lung",
    title="Chief Executive Officer",
    value=637_756.0,
    trade_date=date(2026, 1, 10),
    cik=_CIK,
) -> InsiderTransaction:
    return InsiderTransaction(
        ticker=ticker,
        company="Mint Incorporation Limited",
        insider_name=insider,
        title=title,
        value=value,
        trade_date=trade_date,
        cik=cik,
    )


def _make_efts_hit(ciks, accession="0001234567-26-111111"):
    return {
        "_id": f"{accession}:form4.xml",
        "_source": {
            "adsh": accession,
            "ciks": ciks,
            "file_date": "2026-01-11",
        },
    }


def _make_efts_resp(hits):
    return MagicMock(
        status_code=200,
        json=MagicMock(return_value={"hits": {"hits": hits}}),
        raise_for_status=MagicMock(),
    )


def _make_xml_resp(xml_str):
    return MagicMock(
        status_code=200,
        content=xml_str.encode(),
        raise_for_status=MagicMock(),
    )


_CEO_BUY_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerCik>0001998560</issuerCik>
    <issuerName>Mint Incorporation Limited</issuerName>
    <issuerTradingSymbol>MIMI</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Chan Hoi Lung</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-01-10</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>211879</value></transactionShares>
        <transactionPricePerShare><value>3.01</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


# ── fetch_company_history ─────────────────────────────────────────────────

@patch("company_analyzer.requests.Session")
def test_fetch_company_history_returns_transactions_for_matching_cik(mock_session_cls):
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    hit = _make_efts_hit(ciks=[_CIK_PADDED])  # issuer = last CIK
    mock_session.get.side_effect = [
        _make_efts_resp([hit]),
        _make_xml_resp(_CEO_BUY_XML),
    ]
    results = fetch_company_history(cik=_CIK, ticker=_TICKER, lookback_days=730)
    assert len(results) == 1
    assert results[0].ticker == "MIMI"
    assert results[0].insider_name == "Chan Hoi Lung"


@patch("company_analyzer.requests.Session")
def test_fetch_company_history_filters_out_different_cik(mock_session_cls):
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    # Hit where issuer CIK does NOT match our target CIK
    hit = _make_efts_hit(ciks=[_OTHER_CIK])
    mock_session.get.side_effect = [_make_efts_resp([hit])]
    results = fetch_company_history(cik=_CIK, ticker=_TICKER, lookback_days=730)
    assert results == []


@patch("company_analyzer.requests.Session")
def test_fetch_company_history_returns_empty_on_edgar_error(mock_session_cls):
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    import requests as req
    mock_session.get.side_effect = req.RequestException("timeout")
    results = fetch_company_history(cik=_CIK, ticker=_TICKER, lookback_days=730)
    assert results == []


# ── score_and_filter ──────────────────────────────────────────────────────

def test_score_and_filter_returns_signals_above_min_score():
    # CEO buy $637K → score 4 (CEO) + 4 (≥$500K) = 8
    txs = [_make_tx(value=637_756.0, trade_date=date(2026, 1, 10))]
    result = score_and_filter(txs, min_score=8)
    assert len(result) == 1
    assert result[0][0] == date(2026, 1, 10)
    assert result[0][1] == _TICKER
    assert result[0][2] >= 8


def test_score_and_filter_excludes_signals_below_min_score():
    # Other officer buy $60K → score 1 (Other) + 1 (<$100K) = 2
    txs = [_make_tx(title="Director", value=60_000.0, trade_date=date(2026, 1, 10))]
    result = score_and_filter(txs, min_score=8)
    assert result == []


def test_score_and_filter_groups_by_date():
    # Two transactions on different dates — should produce 2 separate signals
    txs = [
        _make_tx(trade_date=date(2026, 1, 10), value=637_756.0),
        _make_tx(trade_date=date(2026, 3, 15), value=637_756.0),
    ]
    result = score_and_filter(txs, min_score=5)
    assert len(result) == 2
    dates = {r[0] for r in result}
    assert date(2026, 1, 10) in dates
    assert date(2026, 3, 15) in dates


def test_score_and_filter_skips_transactions_without_trade_date():
    txs = [_make_tx(trade_date=None)]
    result = score_and_filter(txs, min_score=5)
    assert result == []


def test_score_and_filter_applies_cluster_bonus_for_same_date():
    # Two different insiders on same date → cluster bonus → higher score
    txs = [
        _make_tx(insider="CEO Person", title="Chief Executive Officer",
                 value=200_000.0, trade_date=date(2026, 1, 10)),
        _make_tx(insider="CFO Person", title="Chief Financial Officer",
                 value=100_000.0, trade_date=date(2026, 1, 10)),
    ]
    result = score_and_filter(txs, min_score=5)
    assert len(result) == 1
    # Score: CEO+4 + CFO+3 + value≥$100K+2 + cluster2+3 = 12
    assert result[0][2] >= 10


# ── backtest ──────────────────────────────────────────────────────────────

def _make_hist(*date_price_pairs) -> pd.DataFrame:
    """Build a mock yfinance history DataFrame."""
    dates = [pd.Timestamp(d) for d, _ in date_price_pairs]
    prices = [p for _, p in date_price_pairs]
    return pd.DataFrame({"Close": prices}, index=pd.DatetimeIndex(dates))


@patch("company_analyzer.yf")
def test_backtest_returns_empty_results_for_no_signals(mock_yf):
    result = backtest([])
    for h in [3, 7, 30]:
        assert result[h].count == 0


@patch("company_analyzer.yf")
def test_backtest_computes_correct_pct_at_each_horizon(mock_yf):
    hist = _make_hist(
        (date(2026, 1, 10), 10.0),   # entry (T+0)
        (date(2026, 1, 13), 11.0),   # T+3
        (date(2026, 1, 17), 12.0),   # T+7
        (date(2026, 2, 9),  14.0),   # T+30
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    signals = [(date(2026, 1, 10), "MIMI", 8)]
    result = backtest(signals)
    assert result[3].avg_pct == pytest.approx(10.0, abs=0.1)   # +10%
    assert result[7].avg_pct == pytest.approx(20.0, abs=0.1)   # +20%
    assert result[30].avg_pct == pytest.approx(40.0, abs=0.1)  # +40%


@patch("company_analyzer.yf")
def test_backtest_counts_positives_correctly(mock_yf):
    # Two signals: one positive (+10%), one negative (-5%) at T+7
    hist1 = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 17), 11.0),   # +10%
    )
    hist2 = _make_hist(
        (date(2026, 3, 1), 20.0),
        (date(2026, 3, 8), 19.0),    # -5%
    )
    mock_yf.Ticker.return_value.history.side_effect = [hist1, hist2]
    signals = [
        (date(2026, 1, 10), "MIMI", 8),
        (date(2026, 3, 1),  "MIMI", 8),
    ]
    result = backtest(signals)
    assert result[7].count == 2
    assert result[7].positives == 1


@patch("company_analyzer.yf")
def test_backtest_skips_signal_when_yfinance_returns_empty(mock_yf):
    mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
    signals = [(date(2026, 1, 10), "MIMI", 8)]
    result = backtest(signals)
    for h in [3, 7, 30]:
        assert result[h].count == 0


@patch("company_analyzer.yf")
def test_backtest_skips_horizon_when_price_unavailable(mock_yf):
    # Only entry + T+3 available; T+7 and T+30 missing
    hist = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 13), 11.0),
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    signals = [(date(2026, 1, 10), "MIMI", 8)]
    result = backtest(signals)
    assert result[3].count == 1
    assert result[7].count == 0
    assert result[30].count == 0


# ── _make_stats helper ────────────────────────────────────────────────────

def _make_stats(t3=(0, 0, 0.0), t7=(0, 0, 0.0), t30=(0, 0, 0.0)):
    """Helper: build a stats dict from (count, positives, avg_pct) tuples."""
    c3, p3, a3 = t3
    c7, p7, a7 = t7
    c30, p30, a30 = t30
    return {
        3:  BacktestResult(horizon_days=3,  count=c3,  positives=p3,  avg_pct=a3),
        7:  BacktestResult(horizon_days=7,  count=c7,  positives=p7,  avg_pct=a7),
        30: BacktestResult(horizon_days=30, count=c30, positives=p30, avg_pct=a30),
    }


# ── generate_recommendation ───────────────────────────────────────────────

def test_generate_recommendation_returns_nd_when_no_data():
    stats = _make_stats(t3=(0, 0, 0.0), t7=(0, 0, 0.0), t30=(0, 0, 0.0))
    rec = generate_recommendation(stats, entry_price=3.21)
    assert rec.action == "N/D"
    assert rec.tp is None


def test_generate_recommendation_compra_on_positive_avg():
    stats = _make_stats(t7=(3, 3, 15.0))
    rec = generate_recommendation(stats, entry_price=10.0)
    assert rec.action == "COMPRA"
    assert rec.tp == pytest.approx(11.50, abs=0.01)  # 10.0 * 1.15


def test_generate_recommendation_attenzione_on_negative_avg():
    stats = _make_stats(t7=(3, 0, -5.0))
    rec = generate_recommendation(stats, entry_price=10.0)
    assert rec.action == "ATTENZIONE"
    assert rec.tp is None


def test_generate_recommendation_sl_calculation():
    import config
    stats = _make_stats(t7=(3, 3, 15.0))
    rec = generate_recommendation(stats, entry_price=10.0)
    assert rec.sl == pytest.approx(10.0 * (1 - config.SL_PERCENT), abs=0.01)


def test_generate_recommendation_selects_best_horizon_by_success_rate():
    # T+7: 3/3 (100%) avg +5%  — T+30: 2/3 (67%) avg +20%
    # T+7 wins because higher success rate
    stats = _make_stats(
        t3=(0, 0, 0.0),
        t7=(3, 3, 5.0),
        t30=(3, 2, 20.0),
    )
    rec = generate_recommendation(stats, entry_price=10.0)
    assert rec.best_horizon == 7


def test_generate_recommendation_tiebreaks_by_avg_pct():
    # T+7 and T+30 both 2/3 (67%) — T+30 wins on avg_pct
    stats = _make_stats(
        t3=(0, 0, 0.0),
        t7=(3, 2, 5.0),
        t30=(3, 2, 12.0),
    )
    rec = generate_recommendation(stats, entry_price=10.0)
    assert rec.best_horizon == 30


# ── build_message ─────────────────────────────────────────────────────────

def test_build_message_no_history_contains_nd():
    stats = _make_stats(t3=(0, 0, 0.0), t7=(0, 0, 0.0), t30=(0, 0, 0.0))
    rec = Recommendation(action="N/D", best_horizon=7, tp=None, sl=2.95, avg_pct=0.0)
    msg = build_message(ticker="MIMI", entry_price=3.21, stats=stats, rec=rec,
                        today_score=11, signal_count=0)
    assert "MIMI" in msg
    assert "nessuno trovato" in msg
    assert "N/D" in msg


def test_build_message_with_history_contains_key_fields():
    stats = _make_stats(t7=(3, 3, 15.0))
    rec = Recommendation(action="COMPRA", best_horizon=7, tp=3.69, sl=2.95, avg_pct=15.0)
    msg = build_message(ticker="MIMI", entry_price=3.21, stats=stats, rec=rec,
                        today_score=11, signal_count=3)
    assert "$MIMI" in msg
    assert "3 trovati" in msg
    assert "COMPRA" in msg
    assert "3.69" in msg   # TP
    assert "2.95" in msg   # SL
    assert "7 giorni" in msg


def test_build_message_marks_best_horizon():
    stats = _make_stats(t7=(3, 3, 15.0))
    rec = Recommendation(action="COMPRA", best_horizon=7, tp=3.69, sl=2.95, avg_pct=15.0)
    msg = build_message(ticker="MIMI", entry_price=3.21, stats=stats, rec=rec,
                        today_score=11, signal_count=3)
    assert "migliore" in msg


# ── analyze (orchestrator) ────────────────────────────────────────────────

@patch("company_analyzer.requests.Session")
@patch("company_analyzer.yf")
def test_analyze_returns_nd_message_on_empty_edgar_history(mock_yf, mock_session_cls):
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    mock_session.get.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"hits": {"hits": []}}),
        raise_for_status=MagicMock(),
    )
    msg = analyze(ticker="MIMI", cik="1998560", today_score=11, entry_price=3.21)
    assert "MIMI" in msg
    assert "N/D" in msg


@patch("company_analyzer.requests.Session")
@patch("company_analyzer.yf")
def test_analyze_returns_error_message_on_exception(mock_yf, mock_session_cls):
    mock_session_cls.side_effect = Exception("unexpected")
    msg = analyze(ticker="MIMI", cik="1998560", today_score=11, entry_price=3.21)
    assert "MIMI" in msg
    assert "N/D" in msg
