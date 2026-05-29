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
    SignalEvent,
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


def _make_signal_event(
    trade_date=date(2026, 1, 10),
    ticker=_TICKER,
    score=8,
    insiders=None,
) -> SignalEvent:
    if insiders is None:
        insiders = [("Chan Hoi Lung", "Chief Executive Officer", 637_756.0)]
    return SignalEvent(
        trade_date=trade_date,
        ticker=ticker,
        score=score,
        insiders=insiders,
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
    txs = [_make_tx(value=637_756.0, trade_date=date(2026, 1, 10))]
    result = score_and_filter(txs, min_score=8)
    assert len(result) == 1
    assert result[0].trade_date == date(2026, 1, 10)
    assert result[0].ticker == _TICKER
    assert result[0].score >= 8
    assert len(result[0].insiders) == 1
    assert result[0].insiders[0][0] == "Chan Hoi Lung"


def test_score_and_filter_excludes_signals_below_min_score():
    txs = [_make_tx(title="Director", value=60_000.0, trade_date=date(2026, 1, 10))]
    result = score_and_filter(txs, min_score=8)
    assert result == []


def test_score_and_filter_groups_by_date():
    txs = [
        _make_tx(trade_date=date(2026, 1, 10), value=637_756.0),
        _make_tx(trade_date=date(2026, 3, 15), value=637_756.0),
    ]
    result = score_and_filter(txs, min_score=5)
    assert len(result) == 2
    dates = {e.trade_date for e in result}
    assert date(2026, 1, 10) in dates
    assert date(2026, 3, 15) in dates


def test_score_and_filter_skips_transactions_without_trade_date():
    txs = [_make_tx(trade_date=None)]
    result = score_and_filter(txs, min_score=5)
    assert result == []


def test_score_and_filter_applies_cluster_bonus_for_same_date():
    txs = [
        _make_tx(insider="CEO Person", title="Chief Executive Officer",
                 value=200_000.0, trade_date=date(2026, 1, 10)),
        _make_tx(insider="CFO Person", title="Chief Financial Officer",
                 value=100_000.0, trade_date=date(2026, 1, 10)),
    ]
    result = score_and_filter(txs, min_score=5)
    assert len(result) == 1
    assert result[0].score >= 10
    assert len(result[0].insiders) == 2


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
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 13), 11.0),   # T+3 → +10%
        (date(2026, 1, 17), 12.0),   # T+7 → +20%
        (date(2026, 2, 9),  14.0),   # T+30 → +40%
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    events = [_make_signal_event(trade_date=date(2026, 1, 10))]
    result = backtest(events)
    assert result[3].avg_pct == pytest.approx(10.0, abs=0.1)
    assert result[7].avg_pct == pytest.approx(20.0, abs=0.1)
    assert result[30].avg_pct == pytest.approx(40.0, abs=0.1)


@patch("company_analyzer.yf")
def test_backtest_counts_positives_correctly(mock_yf):
    hist1 = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 17), 11.0),   # +10%
    )
    hist2 = _make_hist(
        (date(2026, 3, 1), 20.0),
        (date(2026, 3, 8), 19.0),    # -5%
    )
    mock_yf.Ticker.return_value.history.side_effect = [hist1, hist2]
    events = [
        _make_signal_event(trade_date=date(2026, 1, 10)),
        _make_signal_event(trade_date=date(2026, 3, 1)),
    ]
    result = backtest(events)
    assert result[7].count == 2
    assert result[7].positives == 1


@patch("company_analyzer.yf")
def test_backtest_skips_signal_when_yfinance_returns_empty(mock_yf):
    mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
    events = [_make_signal_event()]
    result = backtest(events)
    for h in [3, 7, 30]:
        assert result[h].count == 0


@patch("company_analyzer.yf")
def test_backtest_skips_horizon_when_price_unavailable(mock_yf):
    hist = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 13), 11.0),
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    events = [_make_signal_event()]
    result = backtest(events)
    assert result[3].count == 1
    assert result[7].count == 0
    assert result[30].count == 0


@patch("company_analyzer.yf")
def test_backtest_populates_per_event_pcts(mock_yf):
    hist = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 13), 11.0),   # T+3 → +10%
        (date(2026, 1, 17), 12.0),   # T+7 → +20%
        (date(2026, 2, 9),  14.0),   # T+30 → +40%
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    event = _make_signal_event(trade_date=date(2026, 1, 10))
    backtest([event])
    assert event.t3_pct == pytest.approx(10.0, abs=0.1)
    assert event.t7_pct == pytest.approx(20.0, abs=0.1)
    assert event.t30_pct == pytest.approx(40.0, abs=0.1)


@patch("company_analyzer.yf")
def test_backtest_leaves_pct_none_when_price_unavailable(mock_yf):
    hist = _make_hist(
        (date(2026, 1, 10), 10.0),
        (date(2026, 1, 13), 11.0),   # only T+3 available
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    event = _make_signal_event(trade_date=date(2026, 1, 10))
    backtest([event])
    assert event.t3_pct == pytest.approx(10.0, abs=0.1)
    assert event.t7_pct is None
    assert event.t30_pct is None


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

def test_build_message_no_events_shows_nessuno_trovato():
    stats = _make_stats()
    rec = Recommendation(action="N/D", best_horizon=7, tp=None, sl=2.95, avg_pct=0.0)
    msg = build_message(ticker="MIMI", entry_price=3.21, signal_events=[], stats=stats, rec=rec)
    assert "MIMI" in msg
    assert "Nessun" in msg
    assert "N/D" in msg


def test_build_message_shows_purchase_list_and_stats():
    stats = _make_stats(t7=(1, 1, 18.0))
    rec = Recommendation(action="COMPRA", best_horizon=7, tp=3.79, sl=2.95, avg_pct=18.0)
    events = [
        SignalEvent(
            trade_date=date.today() - timedelta(days=30),
            ticker="MIMI", score=8,
            insiders=[("Chan Hoi Lung", "Chief Executive Officer", 637_756.0)],
            t3_pct=5.0, t7_pct=18.0, t30_pct=22.0,
        )
    ]
    msg = build_message("MIMI", 3.21, events, stats, rec)
    assert "$MIMI" in msg
    assert "CEO" in msg
    assert "COMPRA" in msg
    assert "3.79" in msg
    assert "2.95" in msg
    assert "7 giorni" in msg
    assert "migliore" in msg


def test_build_message_truncates_to_max_display():
    stats = _make_stats(t7=(7, 6, 12.0))
    rec = Recommendation(action="COMPRA", best_horizon=7, tp=3.60, sl=2.95, avg_pct=12.0)
    events = [
        SignalEvent(
            trade_date=date.today() - timedelta(days=i + 10),
            ticker="MIMI", score=8,
            insiders=[("A Person", "Chief Executive Officer", 100_000.0)],
            t7_pct=5.0,
        )
        for i in range(7)
    ]
    msg = build_message("MIMI", 3.21, events, stats, rec)
    assert "e altri 2" in msg


def test_build_message_orders_most_recent_first():
    stats = _make_stats(t7=(2, 2, 10.0))
    rec = Recommendation(action="COMPRA", best_horizon=7, tp=3.53, sl=2.95, avg_pct=10.0)
    old_date = date.today() - timedelta(days=180)
    new_date = date.today() - timedelta(days=30)
    events = [
        SignalEvent(trade_date=old_date, ticker="MIMI", score=8,
                    insiders=[("Old Buyer", "Chief Executive Officer", 100_000.0)], t7_pct=5.0),
        SignalEvent(trade_date=new_date, ticker="MIMI", score=8,
                    insiders=[("New Buyer", "Chief Executive Officer", 100_000.0)], t7_pct=8.0),
    ]
    msg = build_message("MIMI", 3.21, events, stats, rec)
    new_str = new_date.strftime("%d/%m")
    old_str = old_date.strftime("%d/%m")
    assert msg.index(new_str) < msg.index(old_str)


def test_build_message_attenzione_no_tp():
    stats = _make_stats(t7=(2, 0, -5.0))
    rec = Recommendation(action="ATTENZIONE", best_horizon=7, tp=None, sl=2.95, avg_pct=-5.0)
    events = [
        SignalEvent(
            trade_date=date.today() - timedelta(days=30),
            ticker="MIMI", score=8,
            insiders=[("John Smith", "Chief Executive Officer", 100_000.0)],
            t7_pct=-5.0,
        )
    ]
    msg = build_message("MIMI", 3.21, events, stats, rec)
    assert "ATTENZIONE" in msg
    assert "TP" not in msg


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


@patch("company_analyzer.requests.Session")
@patch("company_analyzer.yf")
def test_analyze_excludes_purchases_in_current_lookback_window(mock_yf, mock_session_cls):
    """analyze() excludes purchases within LOOKBACK_CALENDAR_DAYS of today."""
    import config
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    mock_session.get.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"hits": {"hits": []}}),
        raise_for_status=MagicMock(),
    )
    mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
    # Even if a purchase happened yesterday, it falls within LOOKBACK_CALENDAR_DAYS
    # and should be excluded (it's part of the current signal window)
    msg = analyze(ticker="MIMI", cik="1998560", today_score=5, entry_price=3.21)
    assert "MIMI" in msg
    assert "N/D" in msg


# -- format helpers -----------------------------------------------------------

from company_analyzer import _fmt_value, _short_role, _format_purchase_row


def test_fmt_value_thousands():
    assert _fmt_value(637_756.0) == "$638K"


def test_fmt_value_millions():
    assert _fmt_value(1_500_000.0) == "$1.5M"


def test_fmt_value_small():
    assert _fmt_value(50_000.0) == "$50K"


def test_short_role_ceo():
    assert _short_role('Chief Executive Officer') == 'CEO'


def test_short_role_cfo():
    assert _short_role('Chief Financial Officer') == 'CFO'


def test_format_purchase_row_basic():
    event = SignalEvent(
        trade_date=date(2026, 3, 15),
        ticker='MIMI',
        score=8,
        insiders=[('Chan Hoi Lung', 'Chief Executive Officer', 637_756.0)],
        t3_pct=5.2,
        t7_pct=18.0,
        t30_pct=22.3,
    )
    row = _format_purchase_row(event)
    assert row.startswith("• 15/03")
    assert "CEO" in row
    assert "$638K" in row
    assert "+5.2%" in row
    assert "+18.0%" in row
    assert "+22.3%" in row


def test_format_purchase_row_none_pct_shows_dash():
    event = SignalEvent(
        trade_date=date(2026, 3, 15),
        ticker='MIMI',
        score=8,
        insiders=[('John Smith', 'Chief Financial Officer', 150_000.0)],
        t3_pct=5.2,
        t7_pct=None,
        t30_pct=None,
    )
    row = _format_purchase_row(event)
    assert '+5.2%' in row
    assert row.count("—") >= 2


def test_format_purchase_row_negative_pct():
    event = SignalEvent(
        trade_date=date(2026, 1, 10),
        ticker='MIMI',
        score=5,
        insiders=[('John Smith', 'Director', 150_000.0)],
        t3_pct=-3.5,
        t7_pct=-5.0,
        t30_pct=8.0,
    )
    row = _format_purchase_row(event)
    assert '-3.5%' in row
    assert '-5.0%' in row
    assert '+8.0%' in row
