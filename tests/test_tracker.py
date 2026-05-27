from datetime import date, timedelta
from scraper import InsiderTransaction
from scorer import TickerSignal
from insider_tracker import (
    already_sent_today,
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
