from datetime import date, timedelta
from scraper import InsiderTransaction
from scorer import TickerSignal
from unittest.mock import patch

from insider_tracker import (
    already_sent_today,
    is_weekday,
    main,
    mark_sent,
    pick_top_signal,
)


def make_signal(ticker="AAPL", score=10):
    return TickerSignal(ticker=ticker, company="Apple", transactions=[], score=score, score_breakdown=[])


def test_already_sent_today_returns_true_when_sent_today():
    assert already_sent_today("AAPL", {"AAPL": str(date.today())}) is True

def test_already_sent_today_returns_false_when_sent_yesterday():
    yesterday = str(date.today() - timedelta(days=1))
    assert already_sent_today("AAPL", {"AAPL": yesterday}) is False

def test_already_sent_today_returns_false_when_not_present():
    assert already_sent_today("AAPL", {}) is False

def test_mark_sent_records_today():
    last_seen = {}
    mark_sent("AAPL", last_seen)
    assert last_seen["AAPL"] == str(date.today())


def test_pick_top_signal_returns_highest_score():
    signals = [make_signal("AAPL", 15), make_signal("MSFT", 8)]
    assert pick_top_signal(signals, last_seen={}).ticker == "AAPL"

def test_pick_top_signal_returns_none_when_all_below_min_score():
    import config
    signals = [make_signal("AAPL", config.MIN_SCORE - 1)]
    assert pick_top_signal(signals, last_seen={}) is None

def test_pick_top_signal_skips_already_sent_today():
    last_seen = {"AAPL": str(date.today())}
    signals = [make_signal("AAPL", 15), make_signal("MSFT", 8)]
    assert pick_top_signal(signals, last_seen=last_seen).ticker == "MSFT"

def test_pick_top_signal_returns_none_when_all_sent_today():
    last_seen = {"AAPL": str(date.today()), "MSFT": str(date.today())}
    signals = [make_signal("AAPL", 15), make_signal("MSFT", 8)]
    assert pick_top_signal(signals, last_seen=last_seen) is None


# ── is_weekday ────────────────────────────────────────────────────────────

def test_is_weekday_true_on_monday():
    assert is_weekday(date(2026, 5, 25)) is True   # lunedì

def test_is_weekday_true_on_friday():
    assert is_weekday(date(2026, 5, 29)) is True   # venerdì

def test_is_weekday_false_on_saturday():
    assert is_weekday(date(2026, 5, 30)) is False  # sabato

def test_is_weekday_false_on_sunday():
    assert is_weekday(date(2026, 5, 31)) is False  # domenica


# ── main() weekend skip ───────────────────────────────────────────────────

@patch("insider_tracker.is_weekday", return_value=False)
@patch("insider_tracker._fetch_all")
def test_main_does_not_fetch_on_weekend(mock_fetch, mock_is_weekday):
    main()
    mock_fetch.assert_not_called()


def test_config_has_company_history_lookback_days():
    import config
    assert config.COMPANY_HISTORY_LOOKBACK_DAYS == 730

def test_config_has_sl_percent():
    import config
    assert config.SL_PERCENT == 0.08
