"""Tests for portfolio_tracker module."""

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import pandas as pd

from portfolio_tracker import (
    position_size,
    load_portfolio,
    save_portfolio,
    open_position,
    get_open_price,
    get_current_price,
    resolve_yf_ticker,
    update,
    generate_markdown,
)


def _default_portfolio(tmp_path) -> Path:
    f = tmp_path / "portfolio.json"
    data = {
        "capital_initial": 20000.0,
        "cash": 20000.0,
        "positions": [],
        "closed": [],
    }
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


# ── position_size ─────────────────────────────────────────────────────────

def test_position_size_buono():
    assert position_size(8) == 500.0
    assert position_size(10) == 500.0

def test_position_size_ottimo():
    assert position_size(11) == 1000.0
    assert position_size(13) == 1000.0

def test_position_size_eccellente():
    assert position_size(14) == 2000.0
    assert position_size(21) == 2000.0

def test_position_size_below_min_returns_zero():
    assert position_size(7) == 0.0
    assert position_size(0) == 0.0


# ── load / save ───────────────────────────────────────────────────────────

def test_load_portfolio_returns_default_when_file_missing(tmp_path):
    f = tmp_path / "portfolio.json"
    data = load_portfolio(f)
    assert data["cash"] == 20000.0
    assert data["positions"] == []
    assert data["closed"] == []


# ── open_position ─────────────────────────────────────────────────────────

def test_open_position_adds_position_and_deducts_cash(tmp_path):
    pf = _default_portfolio(tmp_path)
    open_position("NAKA", 17, date(2026, 5, 29), portfolio_file=pf)
    data = json.loads(pf.read_text())
    assert len(data["positions"]) == 1
    assert data["positions"][0]["ticker"] == "NAKA"
    assert data["positions"][0]["invested"] == 2000.0
    assert data["positions"][0]["entry_price"] is None
    assert data["positions"][0]["exit_date_target"] == "2026-06-05"  # +7 giorni default
    assert data["cash"] == 18000.0


def test_open_position_respects_custom_holding_days(tmp_path):
    pf = _default_portfolio(tmp_path)
    open_position("COE", 23, date(2026, 6, 1), portfolio_file=pf, holding_days=30)
    data = json.loads(pf.read_text())
    assert data["positions"][0]["exit_date_target"] == "2026-07-01"  # +30 giorni
    assert data["positions"][0]["ticker"] == "COE"


def test_open_position_ignores_low_score(tmp_path):
    pf = _default_portfolio(tmp_path)
    open_position("WEAK", 5, date(2026, 5, 29), portfolio_file=pf)
    data = json.loads(pf.read_text())
    assert data["positions"] == []
    assert data["cash"] == 20000.0


def test_open_position_ignores_invalid_ticker(tmp_path):
    # Ticker non risolto dallo scraper (N/A, vuoto, None): niente posizione
    # zombie, cash intatto. Il segnale Telegram resta comunque informativo.
    pf = _default_portfolio(tmp_path)
    for bad in ("N/A", "n/a", "", "   ", None):
        open_position(bad, 17, date(2026, 5, 29), portfolio_file=pf)
    data = json.loads(pf.read_text())
    assert data["positions"] == []
    assert data["cash"] == 20000.0


def test_open_position_stores_yf_ticker(tmp_path):
    pf = _default_portfolio(tmp_path)
    open_position("VII", 11, date(2026, 7, 9), portfolio_file=pf, yf_ticker="VII-UN")
    data = json.loads(pf.read_text())
    assert data["positions"][0]["ticker"] == "VII"        # display: ticker base
    assert data["positions"][0]["yf_ticker"] == "VII-UN"  # pricing: units


def test_open_position_yf_ticker_defaults_to_ticker(tmp_path):
    pf = _default_portfolio(tmp_path)
    open_position("COE", 23, date(2026, 7, 9), portfolio_file=pf)
    data = json.loads(pf.read_text())
    assert data["positions"][0]["yf_ticker"] == "COE"


# ── resolve_yf_ticker ──────────────────────────────────────────────────────

@patch("portfolio_tracker.get_current_price")
def test_resolve_yf_ticker_returns_base_when_priceable(mock_price):
    mock_price.return_value = 25.0
    assert resolve_yf_ticker("COE") == "COE"


@patch("portfolio_tracker.get_current_price")
def test_resolve_yf_ticker_tries_spac_units_suffix(mock_price):
    # Ticker base non prezzabile ma la variante units "-UN" sì (caso SPAC VII)
    mock_price.side_effect = lambda t: 10.0 if t == "VII-UN" else None
    assert resolve_yf_ticker("VII") == "VII-UN"


@patch("portfolio_tracker.get_current_price")
def test_resolve_yf_ticker_returns_none_when_nothing_priceable(mock_price):
    mock_price.return_value = None
    assert resolve_yf_ticker("NOPE") is None


@patch("portfolio_tracker.get_current_price")
def test_resolve_yf_ticker_none_for_invalid_ticker(mock_price):
    assert resolve_yf_ticker("N/A") is None
    mock_price.assert_not_called()


@patch("portfolio_tracker.get_current_price")
@patch("portfolio_tracker.get_open_price")
def test_update_uses_yf_ticker_for_pricing(mock_open, mock_curr, tmp_path):
    # La posizione VII deve essere prezzata usando yf_ticker (VII-UN), non "VII"
    pf = tmp_path / "portfolio.json"
    data = {
        "capital_initial": 20000.0, "cash": 19000.0,
        "positions": [{
            "ticker": "VII", "yf_ticker": "VII-UN", "score": 11,
            "signal_date": str(date.today() - timedelta(days=1)),
            "entry_price": None, "shares": None, "invested": 1000.0,
            "exit_date_target": str(date.today() + timedelta(days=5)),
            "current_price": None, "unrealized_pnl": None,
        }],
        "closed": [],
    }
    pf.write_text(json.dumps(data), encoding="utf-8")
    mock_open.return_value = 10.0
    mock_curr.return_value = 10.02
    update(portfolio_file=pf, md_path=tmp_path / "out.md")
    # il pricing deve usare VII-UN
    assert mock_open.call_args[0][0] == "VII-UN"
    result = json.loads(pf.read_text())
    assert result["positions"][0]["entry_price"] == pytest.approx(10.0, abs=0.001)
    assert result["positions"][0]["ticker"] == "VII"  # display resta VII


# ── get_open_price ────────────────────────────────────────────────────────

@patch("portfolio_tracker.yf")
def test_get_open_price_returns_open(mock_yf):
    hist = pd.DataFrame(
        {"Open": [5.42], "Close": [5.60]},
        index=[pd.Timestamp("2026-05-29")]
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    price = get_open_price("NAKA", date(2026, 5, 29))
    assert price == pytest.approx(5.42)


@patch("portfolio_tracker.yf")
def test_get_open_price_falls_back_to_next_trading_day(mock_yf):
    # Segnale in un giorno di festività USA (mercati chiusi): la prima barra
    # disponibile è quella del giorno di mercato successivo.
    hist = pd.DataFrame(
        {"Open": [12.30], "Close": [12.50]},
        index=[pd.Timestamp("2026-07-06")]   # 2026-07-03 era festivo
    )
    mock_yf.Ticker.return_value.history.return_value = hist
    price = get_open_price("ACME", date(2026, 7, 3))
    assert price == pytest.approx(12.30)


@patch("portfolio_tracker.yf")
def test_get_open_price_searches_a_window_after_target_date(mock_yf):
    mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
    get_open_price("ACME", date(2026, 7, 3))
    kwargs = mock_yf.Ticker.return_value.history.call_args.kwargs
    # la finestra deve estendersi oltre il giorno successivo per scavalcare
    # weekend e festività consecutive
    assert kwargs["start"] == "2026-07-03"
    assert kwargs["end"] > "2026-07-04"


@patch("portfolio_tracker.yf")
def test_get_open_price_returns_none_on_empty(mock_yf):
    mock_yf.Ticker.return_value.history.return_value = pd.DataFrame()
    assert get_open_price("NAKA", date(2026, 5, 29)) is None


# ── update ────────────────────────────────────────────────────────────────

@patch("portfolio_tracker.get_current_price")
@patch("portfolio_tracker.get_open_price")
def test_update_fills_entry_price(mock_open, mock_curr, tmp_path):
    pf = tmp_path / "portfolio.json"
    # Date relative a oggi: la posizione deve restare APERTA (scadenza nel futuro),
    # altrimenti update() la chiude e il test diventa fragile col passare del tempo.
    data = {
        "capital_initial": 20000.0, "cash": 18000.0,
        "positions": [{
            "ticker": "NAKA", "score": 17,
            "signal_date": str(date.today() - timedelta(days=2)),
            "entry_price": None, "shares": None,
            "invested": 2000.0,
            "exit_date_target": str(date.today() + timedelta(days=5)),
            "current_price": None, "unrealized_pnl": None,
        }],
        "closed": [],
    }
    pf.write_text(json.dumps(data), encoding="utf-8")
    mock_open.return_value = 5.42
    mock_curr.return_value = 5.60
    update(portfolio_file=pf, md_path=tmp_path / "out.md")
    result = json.loads(pf.read_text())
    assert result["positions"][0]["entry_price"] == pytest.approx(5.42, abs=0.001)
    assert result["positions"][0]["shares"] == pytest.approx(2000.0 / 5.42, abs=0.01)


@patch("portfolio_tracker.get_current_price")
@patch("portfolio_tracker.get_open_price")
def test_update_closes_expired_position(mock_open, mock_curr, tmp_path):
    pf = tmp_path / "portfolio.json"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    data = {
        "capital_initial": 20000.0, "cash": 18000.0,
        "positions": [{
            "ticker": "NAKA", "score": 17,
            "signal_date": "2026-05-22",
            "entry_price": 5.42, "shares": 369.0,
            "invested": 2000.0, "exit_date_target": yesterday,
            "current_price": 5.60, "unrealized_pnl": 66.42,
        }],
        "closed": [],
    }
    pf.write_text(json.dumps(data), encoding="utf-8")
    mock_open.return_value = 5.80
    mock_curr.return_value = 5.80
    update(portfolio_file=pf, md_path=tmp_path / "out.md")
    result = json.loads(pf.read_text())
    assert result["positions"] == []
    assert len(result["closed"]) == 1
    assert result["closed"][0]["ticker"] == "NAKA"
    assert result["closed"][0]["pnl"] == pytest.approx((5.80 - 5.42) * 369.0, abs=0.01)
    assert result["cash"] > 18000.0


@patch("portfolio_tracker.get_current_price")
@patch("portfolio_tracker.get_open_price")
def test_update_keeps_position_open_if_no_exit_price(mock_open, mock_curr, tmp_path):
    pf = tmp_path / "portfolio.json"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    data = {
        "capital_initial": 20000.0, "cash": 18000.0,
        "positions": [{
            "ticker": "NAKA", "score": 17,
            "signal_date": "2026-05-22", "entry_price": 5.42, "shares": 369.0,
            "invested": 2000.0, "exit_date_target": yesterday,
            "current_price": None, "unrealized_pnl": None,
        }],
        "closed": [],
    }
    pf.write_text(json.dumps(data), encoding="utf-8")
    mock_open.return_value = None
    mock_curr.return_value = None
    update(portfolio_file=pf, md_path=tmp_path / "out.md")
    result = json.loads(pf.read_text())
    assert len(result["positions"]) == 1
    assert result["closed"] == []


# ── stop-loss ─────────────────────────────────────────────────────────────

@patch("portfolio_tracker.get_current_price")
@patch("portfolio_tracker.get_open_price")
def test_update_closes_position_on_stop_loss(mock_open, mock_curr, tmp_path):
    """Prezzo sotto entry*(1-SL_PERCENT) → chiusura anticipata closed_by=stop_loss."""
    pf = tmp_path / "portfolio.json"
    data = {
        "capital_initial": 20000.0, "cash": 18000.0,
        "positions": [{
            "ticker": "NAKA", "score": 17,
            "signal_date": str(date.today() - timedelta(days=2)),
            "entry_price": 10.0, "shares": 200.0,
            "invested": 2000.0,
            "exit_date_target": str(date.today() + timedelta(days=5)),
            "current_price": 10.0, "unrealized_pnl": 0.0,
        }],
        "closed": [],
    }
    pf.write_text(json.dumps(data), encoding="utf-8")
    mock_open.return_value = 10.0
    mock_curr.return_value = 8.9  # -11% < -10% SL
    update(portfolio_file=pf, md_path=tmp_path / "out.md")
    result = json.loads(pf.read_text())
    assert result["positions"] == []
    assert len(result["closed"]) == 1
    trade = result["closed"][0]
    assert trade["closed_by"] == "stop_loss"
    assert trade["exit_price"] == pytest.approx(8.9, abs=0.001)
    assert trade["pnl"] == pytest.approx((8.9 - 10.0) * 200.0, abs=0.01)
    assert result["cash"] == pytest.approx(18000.0 + 2000.0 + trade["pnl"], abs=0.01)


@patch("portfolio_tracker.get_current_price")
@patch("portfolio_tracker.get_open_price")
def test_update_no_stop_loss_above_threshold(mock_open, mock_curr, tmp_path):
    """Prezzo sopra la soglia SL (-9% con SL 10%) → posizione resta aperta."""
    pf = tmp_path / "portfolio.json"
    data = {
        "capital_initial": 20000.0, "cash": 18000.0,
        "positions": [{
            "ticker": "NAKA", "score": 17,
            "signal_date": str(date.today() - timedelta(days=2)),
            "entry_price": 10.0, "shares": 200.0,
            "invested": 2000.0,
            "exit_date_target": str(date.today() + timedelta(days=5)),
            "current_price": 10.0, "unrealized_pnl": 0.0,
        }],
        "closed": [],
    }
    pf.write_text(json.dumps(data), encoding="utf-8")
    mock_open.return_value = 10.0
    mock_curr.return_value = 9.1  # -9% > soglia -10%
    update(portfolio_file=pf, md_path=tmp_path / "out.md")
    result = json.loads(pf.read_text())
    assert len(result["positions"]) == 1
    assert result["closed"] == []


@patch("portfolio_tracker.get_current_price")
@patch("portfolio_tracker.get_open_price")
def test_update_stop_loss_skipped_without_entry_price(mock_open, mock_curr, tmp_path):
    """Senza entry_price (mercato non ancora aperto) lo SL non può scattare."""
    pf = tmp_path / "portfolio.json"
    data = {
        "capital_initial": 20000.0, "cash": 18000.0,
        "positions": [{
            "ticker": "NAKA", "score": 17,
            "signal_date": str(date.today()),
            "entry_price": None, "shares": None,
            "invested": 2000.0,
            "exit_date_target": str(date.today() + timedelta(days=7)),
            "current_price": None, "unrealized_pnl": None,
        }],
        "closed": [],
    }
    pf.write_text(json.dumps(data), encoding="utf-8")
    mock_open.return_value = None  # entry non ancora disponibile
    mock_curr.return_value = 1.0
    update(portfolio_file=pf, md_path=tmp_path / "out.md")
    result = json.loads(pf.read_text())
    assert len(result["positions"]) == 1
    assert result["closed"] == []


@patch("portfolio_tracker.get_current_price")
@patch("portfolio_tracker.get_open_price")
def test_update_expired_close_marked_as_expiry(mock_open, mock_curr, tmp_path):
    """Le chiusure a scadenza vengono marcate closed_by=expiry."""
    pf = tmp_path / "portfolio.json"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    data = {
        "capital_initial": 20000.0, "cash": 18000.0,
        "positions": [{
            "ticker": "NAKA", "score": 17,
            "signal_date": "2026-05-22", "entry_price": 5.42, "shares": 369.0,
            "invested": 2000.0, "exit_date_target": yesterday,
            "current_price": 5.60, "unrealized_pnl": 66.42,
        }],
        "closed": [],
    }
    pf.write_text(json.dumps(data), encoding="utf-8")
    mock_open.return_value = 5.80
    mock_curr.return_value = 5.80
    update(portfolio_file=pf, md_path=tmp_path / "out.md")
    result = json.loads(pf.read_text())
    assert result["closed"][0]["closed_by"] == "expiry"


# ── generate_markdown ─────────────────────────────────────────────────────

def test_generate_markdown_creates_file(tmp_path):
    data = {
        "capital_initial": 20000.0, "cash": 20000.0,
        "positions": [], "closed": [],
    }
    out = tmp_path / "Portfolio Simulato.md"
    generate_markdown(data, md_path=out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "Portfolio Simulato" in content
    assert "$20,000" in content


def test_generate_markdown_shows_open_position(tmp_path):
    data = {
        "capital_initial": 20000.0, "cash": 18000.0,
        "positions": [{
            "ticker": "NAKA", "score": 17,
            "signal_date": "2026-05-29",
            "entry_price": 5.42, "shares": 369.0,
            "invested": 2000.0, "exit_date_target": "2026-06-05",
            "current_price": 5.60, "unrealized_pnl": 66.42,
        }],
        "closed": [],
    }
    out = tmp_path / "out.md"
    generate_markdown(data, md_path=out)
    content = out.read_text(encoding="utf-8")
    assert "NAKA" in content
    assert "5.42" in content
    assert "5.60" in content
    assert "05/06" in content


def test_generate_markdown_shows_closed_trade(tmp_path):
    data = {
        "capital_initial": 20000.0, "cash": 20016.0,
        "positions": [],
        "closed": [{
            "ticker": "PSEC", "score": 6,
            "signal_date": "2026-05-27",
            "entry_price": 5.21, "shares": 96.0,
            "invested": 500.0, "exit_price": 5.38,
            "exit_date": "2026-06-03", "pnl": 16.32, "pnl_pct": 3.26,
        }],
    }
    out = tmp_path / "out.md"
    generate_markdown(data, md_path=out)
    content = out.read_text(encoding="utf-8")
    assert "PSEC" in content
    assert "5.21" in content
    assert "5.38" in content
    assert "+3.3" in content


def test_generate_markdown_win_rate(tmp_path):
    data = {
        "capital_initial": 20000.0, "cash": 20000.0,
        "positions": [],
        "closed": [
            {"ticker": "A", "score": 8, "signal_date": "2026-05-20",
             "entry_price": 10.0, "shares": 50.0, "invested": 500.0,
             "exit_price": 11.0, "exit_date": "2026-05-27", "pnl": 50.0, "pnl_pct": 10.0},
            {"ticker": "B", "score": 8, "signal_date": "2026-05-21",
             "entry_price": 10.0, "shares": 50.0, "invested": 500.0,
             "exit_price": 9.5, "exit_date": "2026-05-28", "pnl": -25.0, "pnl_pct": -5.0},
        ],
    }
    out = tmp_path / "out.md"
    generate_markdown(data, md_path=out)
    content = out.read_text(encoding="utf-8")
    assert "50%" in content
    assert "1W / 1L" in content
