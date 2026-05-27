from datetime import date
from unittest.mock import patch, MagicMock
import requests as req
from scraper import InsiderTransaction
from scorer import TickerSignal
from notifier import _format_message, _no_signal_message, _signal_label, send_signal, send_error


def make_signal():
    txs = [
        InsiderTransaction("AAPL", "Apple Inc", "Tim Cook", "CEO", 2_500_000, date(2026, 5, 26)),
        InsiderTransaction("AAPL", "Apple Inc", "Luca Maestri", "CFO", 800_000, date(2026, 5, 26)),
    ]
    return TickerSignal(
        ticker="AAPL",
        company="Apple Inc",
        transactions=txs,
        score=17,
        score_breakdown=["• CEO buy +4", "• CFO buy +3", "• Importo $2,500,000 (≥$500K) +4", "• Cluster 2 insider +3"],
    )


# ── _signal_label ─────────────────────────────────────────────────────────

def test_signal_label_debole_for_score_5():
    assert _signal_label(5) == "🔴 Debole"

def test_signal_label_debole_for_score_7():
    assert _signal_label(7) == "🔴 Debole"

def test_signal_label_buono_for_score_8():
    assert _signal_label(8) == "🟡 Buono"

def test_signal_label_buono_for_score_10():
    assert _signal_label(10) == "🟡 Buono"

def test_signal_label_ottimo_for_score_11():
    assert _signal_label(11) == "🟢 Ottimo"

def test_signal_label_ottimo_for_score_13():
    assert _signal_label(13) == "🟢 Ottimo"

def test_signal_label_eccellente_for_score_14():
    assert _signal_label(14) == "🔥 Eccellente"

def test_signal_label_eccellente_for_max_score():
    assert _signal_label(21) == "🔥 Eccellente"


# ── _format_message ────────────────────────────────────────────────────────

def test_format_message_contains_ticker():
    assert "$AAPL" in _format_message(make_signal())

def test_format_message_contains_company():
    assert "Apple Inc" in _format_message(make_signal())

def test_format_message_contains_insider_names():
    msg = _format_message(make_signal())
    assert "Tim Cook" in msg
    assert "Luca Maestri" in msg

def test_format_message_contains_score():
    assert "17 pt" in _format_message(make_signal())

def test_format_message_contains_openinsider_link():
    assert "openinsider.com/AAPL" in _format_message(make_signal())

def test_format_message_contains_signal_label():
    # make_signal() has score=17 → Eccellente
    assert "Eccellente" in _format_message(make_signal())

def test_no_signal_message_contains_no_signal_text():
    assert "Nessun segnale" in _no_signal_message()

def test_no_signal_message_contains_today():
    assert date.today().strftime("%d/%m/%Y") in _no_signal_message()


@patch("notifier.requests.post")
def test_send_signal_calls_telegram_api(mock_post):
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())
    result = send_signal(make_signal(), token="TOKEN", chat_id="CHAT")
    assert result is True
    assert "api.telegram.org" in mock_post.call_args[0][0]


@patch("notifier.requests.post")
def test_send_signal_returns_false_on_network_error(mock_post):
    mock_post.side_effect = req.RequestException("connection failed")
    assert send_signal(make_signal(), token="TOKEN", chat_id="CHAT") is False


@patch("notifier.requests.post")
def test_send_error_includes_error_text(mock_post):
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())
    send_error("timeout error", token="TOKEN", chat_id="CHAT")
    assert "timeout error" in str(mock_post.call_args)
