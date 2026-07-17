# Insider Newsletter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Costruire il modulo `newsletter/` dentro InsiderTracker: digest giornaliero premium su Telegram (template Python, no LLM) + newsletter settimanale EN/IT generata con Claude Code headless e caricata come bozza su beehiiv, senza modificare nessun file del sistema live.

**Architecture:** Il modulo riusa in sola lettura `scraper`, `scorer` e `portfolio_insider.json`. Due entry point: `run_daily.py` (fetch+score → archivio segnali → digest premium via Telegram) e `run_weekly.py` (archivio settimana + track record → report strutturato → `claude -p` per EN/IT → bozze beehiiv o file locali → notifica review). Stato proprio in `newsletter/data/` — mai toccare `last_seen.json` del bot live.

**Tech Stack:** Python 3.14 (venv esistente), pytest, requests, Claude Code CLI headless (`claude -p`), beehiiv API v2, Telegram Bot API.

**Spec:** `docs/superpowers/specs/2026-07-17-insider-newsletter-design.md`

**Regole di sessione:**
- Lavorare SOLO dentro `newsletter/` e `tests/test_news_*.py`. Vietato modificare i file del sistema live (`insider_tracker.py`, `scraper.py`, `scorer.py`, `notifier.py`, `portfolio_tracker.py`, `company_analyzer.py`, `config.py`, `last_seen.json`, `portfolio_insider.json`).
- Eseguire pytest SOLO sui file di test nominati (`venv\Scripts\python -m pytest tests/test_news_archive.py -v`), mai sull'intera cartella.
- I test non devono MAI fare chiamate di rete reali (Telegram, beehiiv, SEC, claude): sempre mock/monkeypatch.
- Working directory per tutti i comandi: `C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker`

---

### Task 1: Package scaffold + configurazione

**Files:**
- Create: `newsletter/__init__.py`
- Create: `newsletter/config_news.py`
- Test: `tests/test_news_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_news_config.py
"""Tests for newsletter.config_news constants."""


def test_config_constants_exist():
    from newsletter import config_news as cn

    assert cn.ARCHIVE_FILE.name == "signals_archive.json"
    assert cn.STATE_FILE.name == "newsletter_state.json"
    assert cn.OUTPUT_DIR.name == "output"
    assert cn.DIGEST_LANGS == ["en"]
    assert cn.MIN_DIGEST_SCORE >= 5
    assert cn.CLAUDE_TIMEOUT_SECONDS >= 300
    assert "not financial advice" in cn.DISCLAIMER_EN.lower()
    assert "non è un consiglio finanziario" in cn.DISCLAIMER_IT.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest tests/test_news_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newsletter'`

- [ ] **Step 3: Write minimal implementation**

```python
# newsletter/__init__.py
```
(file vuoto)

```python
# newsletter/config_news.py
"""
Configurazione del modulo newsletter.

Costanti per digest giornaliero premium (Telegram) e newsletter settimanale
(beehiiv EN/IT). NON importa né modifica lo stato del bot live.

Variabili d'ambiente lette a runtime (in .env, come per il bot):
  TELEGRAM_TOKEN               — token bot (riusato dal bot live, sola lettura)
  NEWS_PREMIUM_CHAT_ID_EN      — chat_id canale Telegram premium (edizione EN)
  NEWS_REVIEW_CHAT_ID          — chat_id personale utente per review/notifiche
  BEEHIIV_API_KEY              — API key beehiiv
  BEEHIIV_PUB_ID_EN            — publication id edizione inglese
  BEEHIIV_PUB_ID_IT            — publication id edizione italiana
"""

from pathlib import Path

# Directory dati/output del modulo (create a runtime se mancanti)
NEWS_DIR = Path(__file__).resolve().parent
DATA_DIR = NEWS_DIR / "data"
OUTPUT_DIR = NEWS_DIR / "output"

ARCHIVE_FILE = DATA_DIR / "signals_archive.json"
STATE_FILE = DATA_DIR / "newsletter_state.json"

# Soglia minima per includere un segnale nel digest premium
# (allineata a config.MIN_SCORE del bot; duplicata qui per indipendenza)
MIN_DIGEST_SCORE = 5

# Lingue del digest premium. Un canale Telegram per lingua:
# env var NEWS_PREMIUM_CHAT_ID_EN, NEWS_PREMIUM_CHAT_ID_IT, ...
# MVP: solo inglese. Aggiungere "it" qui quando si apre il canale italiano.
DIGEST_LANGS = ["en"]

# REVIEW_MODE True = tutto va SOLO alla chat personale dell'utente
# (rodaggio 2-3 settimane). False = digest diretto sul canale premium.
REVIEW_MODE = True

# Generazione settimanale con Claude Code headless
CLAUDE_TIMEOUT_SECONDS = 600

# Nella newsletter gratuita mostriamo solo i top N segnali della settimana
WEEKLY_TOP_N = 3

DISCLAIMER_EN = (
    "This is not financial advice. Insider activity is one signal among many; "
    "always do your own research before investing."
)
DISCLAIMER_IT = (
    "Questo contenuto non è un consiglio finanziario. L'attività degli insider "
    "è solo uno dei tanti segnali: fai sempre le tue ricerche prima di investire."
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest tests/test_news_config.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add newsletter/__init__.py newsletter/config_news.py tests/test_news_config.py
git commit -m "feat(newsletter): package scaffold and config module"
```

---

### Task 2: Archivio segnali (`archive.py`)

L'archivio persiste OGNI segnale giornaliero sopra soglia (non solo il top-1 del bot). È la fonte dati della newsletter settimanale.

**Files:**
- Create: `newsletter/archive.py`
- Test: `tests/test_news_archive.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_archive.py
"""Tests for newsletter.archive — persistenza segnali giornalieri."""

import json
from datetime import date

from scraper import InsiderTransaction
from scorer import TickerSignal
from newsletter import archive


def _make_signal(ticker="ABC", score=9):
    tx = InsiderTransaction(
        ticker=ticker, company="Acme Corp", insider_name="John Doe",
        title="CEO", value=250_000.0, trade_date=date(2026, 7, 15), cik="123",
    )
    return TickerSignal(
        ticker=ticker, company="Acme Corp", transactions=[tx],
        score=score, score_breakdown=["• CEO buy +4"],
    )


def test_append_signals_creates_file_and_serializes(tmp_path):
    f = tmp_path / "signals_archive.json"
    archive.append_signals([_make_signal()], date(2026, 7, 16), archive_file=f)

    data = json.loads(f.read_text(encoding="utf-8"))
    assert len(data) == 1
    entry = data[0]
    assert entry["date"] == "2026-07-16"
    assert entry["ticker"] == "ABC"
    assert entry["score"] == 9
    assert entry["total_value"] == 250_000.0
    assert entry["insiders"] == [
        {"name": "John Doe", "title": "CEO", "value": 250_000.0}
    ]


def test_append_signals_is_idempotent_per_day(tmp_path):
    f = tmp_path / "signals_archive.json"
    archive.append_signals([_make_signal()], date(2026, 7, 16), archive_file=f)
    # secondo run stesso giorno stesso ticker: non duplica
    archive.append_signals([_make_signal()], date(2026, 7, 16), archive_file=f)

    data = json.loads(f.read_text(encoding="utf-8"))
    assert len(data) == 1


def test_load_week_returns_only_last_7_days(tmp_path):
    f = tmp_path / "signals_archive.json"
    archive.append_signals([_make_signal("OLD")], date(2026, 7, 5), archive_file=f)
    archive.append_signals([_make_signal("NEW")], date(2026, 7, 14), archive_file=f)

    week = archive.load_week(end_date=date(2026, 7, 16), archive_file=f)
    assert [e["ticker"] for e in week] == ["NEW"]


def test_load_week_sorted_by_score_desc(tmp_path):
    f = tmp_path / "signals_archive.json"
    archive.append_signals(
        [_make_signal("LOW", score=6), _make_signal("HIGH", score=14)],
        date(2026, 7, 15), archive_file=f,
    )
    week = archive.load_week(end_date=date(2026, 7, 16), archive_file=f)
    assert [e["ticker"] for e in week] == ["HIGH", "LOW"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv\Scripts\python -m pytest tests/test_news_archive.py -v`
Expected: FAIL with `ImportError: cannot import name 'archive'` (o ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
# newsletter/archive.py
"""
Archivio dei segnali giornalieri della newsletter.

Persiste ogni segnale sopra soglia in un JSON append-only, con idempotenza
per (date, ticker). Fonte dati per digest e newsletter settimanale.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from scorer import TickerSignal

from newsletter import config_news


def _load(archive_file: Path) -> list:
    if archive_file.exists():
        return json.loads(archive_file.read_text(encoding="utf-8"))
    return []


def _save(entries: list, archive_file: Path) -> None:
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    archive_file.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _to_entry(signal: TickerSignal, day: date) -> dict:
    return {
        "date": day.isoformat(),
        "ticker": signal.ticker,
        "company": signal.company,
        "score": signal.score,
        "score_breakdown": list(signal.score_breakdown),
        "total_value": sum(t.value for t in signal.transactions),
        "insiders": [
            {"name": t.insider_name, "title": t.title, "value": t.value}
            for t in signal.transactions
        ],
    }


def append_signals(
    signals: List[TickerSignal], day: date, archive_file: Optional[Path] = None
) -> None:
    """Aggiunge i segnali del giorno all'archivio. Idempotente per (date, ticker)."""
    f = archive_file or config_news.ARCHIVE_FILE
    entries = _load(f)
    existing = {(e["date"], e["ticker"]) for e in entries}
    for s in signals:
        key = (day.isoformat(), s.ticker)
        if key not in existing:
            entries.append(_to_entry(s, day))
            existing.add(key)
    _save(entries, f)


def load_week(end_date: date, archive_file: Optional[Path] = None) -> list:
    """Ritorna i segnali degli ultimi 7 giorni (end_date incluso), score desc."""
    f = archive_file or config_news.ARCHIVE_FILE
    start = end_date - timedelta(days=7)
    week = [
        e for e in _load(f)
        if start < date.fromisoformat(e["date"]) <= end_date
    ]
    return sorted(week, key=lambda e: e["score"], reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv\Scripts\python -m pytest tests/test_news_archive.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add newsletter/archive.py tests/test_news_archive.py
git commit -m "feat(newsletter): signal archive with per-day idempotency and weekly query"
```

---

### Task 3: Track record (`track_record.py`)

Calcola le statistiche verificabili dal portfolio simulator esistente (`portfolio_insider.json`, sola lettura). È il motore di credibilità della newsletter.

**Files:**
- Create: `newsletter/track_record.py`
- Test: `tests/test_news_track_record.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_track_record.py
"""Tests for newsletter.track_record — statistiche dal portfolio simulato."""

from newsletter import track_record


def _portfolio(closed):
    return {
        "capital_initial": 20000.0,
        "cash": 18000.0,
        "positions": [],
        "closed": closed,
    }


def _trade(ticker, pnl, pnl_pct, exit_date="2026-07-10"):
    return {
        "ticker": ticker, "score": 11, "signal_date": "2026-07-01",
        "entry_price": 100.0, "shares": 10.0, "invested": 1000.0,
        "exit_price": 100.0 + pnl / 10.0, "exit_date": exit_date,
        "pnl": pnl, "pnl_pct": pnl_pct,
    }


def test_compute_track_record_basic_stats():
    pf = _portfolio([
        _trade("AAA", 50.0, 5.0),
        _trade("BBB", -20.0, -2.0),
        _trade("CCC", 30.0, 3.0),
    ])
    tr = track_record.compute_track_record(pf)

    assert tr["n_trades"] == 3
    assert tr["n_wins"] == 2
    assert tr["win_rate_pct"] == 66.7
    assert tr["total_pnl"] == 60.0
    assert tr["avg_pnl_pct"] == 2.0
    assert tr["best"]["ticker"] == "AAA"
    assert tr["worst"]["ticker"] == "BBB"


def test_compute_track_record_empty_portfolio():
    tr = track_record.compute_track_record(_portfolio([]))
    assert tr["n_trades"] == 0
    assert tr["win_rate_pct"] == 0.0
    assert tr["total_pnl"] == 0.0
    assert tr["recent"] == []


def test_recent_trades_limited_and_newest_first():
    closed = [_trade(f"T{i}", 10.0, 1.0, exit_date=f"2026-07-{i:02d}") for i in range(1, 9)]
    tr = track_record.compute_track_record(_portfolio(closed), recent_n=5)
    assert len(tr["recent"]) == 5
    assert tr["recent"][0]["exit_date"] == "2026-07-08"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv\Scripts\python -m pytest tests/test_news_track_record.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# newsletter/track_record.py
"""
Track record del portfolio simulato per la newsletter.

Legge (in sola lettura) la struttura di portfolio_insider.json e produce
statistiche aggregate verificabili: win rate, PnL totale, media, best/worst,
ultimi trade chiusi.
"""

from pathlib import Path
from typing import Optional

import json

import config as bot_config


def load_portfolio(portfolio_file: Optional[Path] = None) -> dict:
    """Carica il portfolio JSON del bot live (sola lettura)."""
    f = portfolio_file or bot_config.PORTFOLIO_FILE
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"capital_initial": 0.0, "cash": 0.0, "positions": [], "closed": []}


def compute_track_record(portfolio: dict, recent_n: int = 5) -> dict:
    """Statistiche aggregate dai trade chiusi del portfolio simulato."""
    closed = portfolio.get("closed", [])
    n = len(closed)
    if n == 0:
        return {
            "n_trades": 0, "n_wins": 0, "win_rate_pct": 0.0,
            "total_pnl": 0.0, "avg_pnl_pct": 0.0,
            "best": None, "worst": None, "recent": [],
        }
    wins = [t for t in closed if t["pnl"] > 0]
    recent = sorted(closed, key=lambda t: t["exit_date"], reverse=True)[:recent_n]
    return {
        "n_trades": n,
        "n_wins": len(wins),
        "win_rate_pct": round(len(wins) / n * 100, 1),
        "total_pnl": round(sum(t["pnl"] for t in closed), 2),
        "avg_pnl_pct": round(sum(t["pnl_pct"] for t in closed) / n, 2),
        "best": max(closed, key=lambda t: t["pnl_pct"]),
        "worst": min(closed, key=lambda t: t["pnl_pct"]),
        "recent": recent,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv\Scripts\python -m pytest tests/test_news_track_record.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add newsletter/track_record.py tests/test_news_track_record.py
git commit -m "feat(newsletter): track record stats from simulated portfolio"
```

---

### Task 4: Digest giornaliero premium (`digest.py`)

Template Python puro, nessuna chiamata LLM. Output deterministico e testabile.

**Files:**
- Create: `newsletter/digest.py`
- Test: `tests/test_news_digest.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_digest.py
"""Tests for newsletter.digest — digest premium via template, no LLM."""

from datetime import date

from newsletter import digest


def _entry(ticker="ABC", score=12):
    return {
        "date": "2026-07-16", "ticker": ticker, "company": "Acme Corp",
        "score": score, "score_breakdown": ["• CEO buy +4"],
        "total_value": 750_000.0,
        "insiders": [{"name": "John Doe", "title": "CEO", "value": 750_000.0}],
    }


def test_digest_en_contains_core_fields():
    text = digest.build_digest([_entry()], date(2026, 7, 16), lang="en")
    assert "INSIDER DIGEST" in text
    assert "$ABC" in text
    assert "Acme Corp" in text
    assert "John Doe (CEO)" in text
    assert "$750,000" in text
    assert "Score: 12" in text
    assert "not financial advice" in text.lower()


def test_digest_it_uses_italian_disclaimer():
    text = digest.build_digest([_entry()], date(2026, 7, 16), lang="it")
    assert "non è un consiglio finanziario" in text.lower()


def test_digest_empty_day_message():
    text = digest.build_digest([], date(2026, 7, 16), lang="en")
    assert "No insider buy signals" in text


def test_digest_orders_by_score_desc():
    entries = [_entry("LOW", 6), _entry("HIGH", 14)]
    text = digest.build_digest(entries, date(2026, 7, 16), lang="en")
    assert text.index("HIGH") < text.index("LOW")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv\Scripts\python -m pytest tests/test_news_digest.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# newsletter/digest.py
"""
Digest giornaliero premium.

Trasforma le entry dell'archivio segnali in un messaggio Telegram formattato.
Template Python puro: nessuna chiamata LLM, output deterministico.
"""

from datetime import date
from typing import List

from newsletter import config_news


_LABELS = [(14, "🔥"), (11, "🟢"), (8, "🟡"), (0, "🔴")]

_HEADERS = {
    "en": "🔔 INSIDER DIGEST — {d}\nPre-market briefing: {n} insider buy signal(s) in the last 24h.",
    "it": "🔔 INSIDER DIGEST — {d}\nBriefing pre-market: {n} segnali di acquisto insider nelle ultime 24h.",
}
_EMPTY = {
    "en": "🔔 INSIDER DIGEST — {d}\n😴 No insider buy signals in the last 24h.",
    "it": "🔔 INSIDER DIGEST — {d}\n😴 Nessun segnale di acquisto insider nelle ultime 24h.",
}
_DISCLAIMERS = {"en": config_news.DISCLAIMER_EN, "it": config_news.DISCLAIMER_IT}


def _score_emoji(score: int) -> str:
    for threshold, emoji in _LABELS:
        if score >= threshold:
            return emoji
    return "🔴"


def build_digest(entries: List[dict], day: date, lang: str = "en") -> str:
    """Costruisce il testo del digest per una lingua. entries = righe archivio."""
    d = day.strftime("%d/%m/%Y") if lang == "it" else day.strftime("%b %d, %Y")
    if not entries:
        return "\n\n".join([_EMPTY[lang].format(d=d), _DISCLAIMERS[lang]])

    entries = sorted(entries, key=lambda e: e["score"], reverse=True)
    lines = [_HEADERS[lang].format(d=d, n=len(entries)), ""]
    for i, e in enumerate(entries, start=1):
        lines.append(
            f"{i}. ${e['ticker']} — {e['company']} — "
            f"Score: {e['score']} {_score_emoji(e['score'])}"
        )
        for ins in e["insiders"]:
            lines.append(f"   • {ins['name']} ({ins['title']}) → ${ins['value']:,.0f}")
        lines.append("")
    lines.append(_DISCLAIMERS[lang])
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv\Scripts\python -m pytest tests/test_news_digest.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add newsletter/digest.py tests/test_news_digest.py
git commit -m "feat(newsletter): daily premium digest via pure-Python template"
```

---

### Task 5: Invio Telegram con review mode (`telegram_news.py`)

**Files:**
- Create: `newsletter/telegram_news.py`
- Test: `tests/test_news_telegram.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_telegram.py
"""Tests for newsletter.telegram_news — routing review mode vs canale premium."""

from newsletter import telegram_news


def test_send_to_channel_when_review_off(monkeypatch):
    sent = []
    monkeypatch.setattr(
        telegram_news, "_send_telegram",
        lambda text, token, chat_id: sent.append((text, chat_id)) or True,
    )
    ok = telegram_news.send_digest(
        "hello", token="T", premium_chat_id="-100PREMIUM",
        review_chat_id="USER", review_mode=False,
    )
    assert ok is True
    assert sent == [("hello", "-100PREMIUM")]


def test_send_to_review_chat_when_review_on(monkeypatch):
    sent = []
    monkeypatch.setattr(
        telegram_news, "_send_telegram",
        lambda text, token, chat_id: sent.append((text, chat_id)) or True,
    )
    telegram_news.send_digest(
        "hello", token="T", premium_chat_id="-100PREMIUM",
        review_chat_id="USER", review_mode=True,
    )
    # in review mode il messaggio va SOLO all'utente, con prefisso [REVIEW]
    assert len(sent) == 1
    text, chat_id = sent[0]
    assert chat_id == "USER"
    assert text.startswith("[REVIEW]")


def test_notify_user_always_goes_to_review_chat(monkeypatch):
    sent = []
    monkeypatch.setattr(
        telegram_news, "_send_telegram",
        lambda text, token, chat_id: sent.append((text, chat_id)) or True,
    )
    telegram_news.notify_user("bozze pronte", token="T", review_chat_id="USER")
    assert sent == [("bozze pronte", "USER")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv\Scripts\python -m pytest tests/test_news_telegram.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# newsletter/telegram_news.py
"""
Invio Telegram per la newsletter.

Instrada il digest premium: in review mode va solo alla chat personale
dell'utente (rodaggio), altrimenti al canale premium. Le notifiche di
servizio (bozze settimanali pronte, errori) vanno sempre alla chat utente.
"""

import logging

import requests

logger = logging.getLogger(__name__)


def _send_telegram(text: str, token: str, chat_id: str) -> bool:
    """Invia un messaggio via Bot API. True su successo, False su errore."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("Telegram send failed: %s", e)
        return False


def send_digest(
    text: str, token: str, premium_chat_id: str,
    review_chat_id: str, review_mode: bool,
) -> bool:
    """Invia il digest al canale premium, o alla chat utente in review mode."""
    if review_mode:
        return _send_telegram(f"[REVIEW]\n{text}", token, review_chat_id)
    return _send_telegram(text, token, premium_chat_id)


def notify_user(text: str, token: str, review_chat_id: str) -> bool:
    """Notifica di servizio alla chat personale dell'utente."""
    return _send_telegram(text, token, review_chat_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv\Scripts\python -m pytest tests/test_news_telegram.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add newsletter/telegram_news.py tests/test_news_telegram.py
git commit -m "feat(newsletter): telegram sender with review-mode routing"
```

---

### Task 6: Orchestrazione giornaliera (`run_daily.py`)

**Files:**
- Create: `newsletter/run_daily.py`
- Test: `tests/test_news_run_daily.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_run_daily.py
"""Tests for newsletter.run_daily — orchestrazione digest giornaliero."""

from datetime import date

from scraper import InsiderTransaction
from scorer import TickerSignal
from newsletter import run_daily


def _signal(ticker="ABC", score=9):
    tx = InsiderTransaction(
        ticker=ticker, company="Acme", insider_name="John Doe", title="CEO",
        value=250_000.0, trade_date=date(2026, 7, 15), cik="1",
    )
    return TickerSignal(ticker=ticker, company="Acme", transactions=[tx],
                        score=score, score_breakdown=[])


def test_run_archives_and_sends(tmp_path, monkeypatch):
    archive_file = tmp_path / "archive.json"
    state_file = tmp_path / "state.json"
    sent = []

    monkeypatch.setattr(run_daily, "_fetch_signals",
                        lambda *a, **k: [_signal("ABC", 9), _signal("LOW", 3)])
    monkeypatch.setattr(
        run_daily.telegram_news, "send_digest",
        lambda text, **kw: sent.append(text) or True,
    )
    env = {"TELEGRAM_TOKEN": "T", "NEWS_PREMIUM_CHAT_ID_EN": "-100X",
           "NEWS_REVIEW_CHAT_ID": "U"}
    monkeypatch.setattr(run_daily.os, "environ", env)

    run_daily.run(today=date(2026, 7, 16),
                  archive_file=archive_file, state_file=state_file)

    # segnale sotto soglia (3 < MIN_DIGEST_SCORE) escluso
    assert len(sent) == 1
    assert "$ABC" in sent[0]
    assert "LOW" not in sent[0]
    # archivio scritto
    import json
    assert len(json.loads(archive_file.read_text(encoding="utf-8"))) == 1


def test_run_is_idempotent_per_day(tmp_path, monkeypatch):
    archive_file = tmp_path / "archive.json"
    state_file = tmp_path / "state.json"
    sent = []

    monkeypatch.setattr(run_daily, "_fetch_signals", lambda *a, **k: [_signal()])
    monkeypatch.setattr(run_daily.telegram_news, "send_digest",
                        lambda text, **kw: sent.append(text) or True)
    env = {"TELEGRAM_TOKEN": "T", "NEWS_PREMIUM_CHAT_ID_EN": "-100X",
           "NEWS_REVIEW_CHAT_ID": "U"}
    monkeypatch.setattr(run_daily.os, "environ", env)

    run_daily.run(today=date(2026, 7, 16), archive_file=archive_file, state_file=state_file)
    run_daily.run(today=date(2026, 7, 16), archive_file=archive_file, state_file=state_file)

    assert len(sent) == 1  # secondo run: skip


def test_run_skips_weekend(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(run_daily, "_fetch_signals",
                        lambda *a, **k: called.append(1) or [])
    run_daily.run(today=date(2026, 7, 18),  # sabato
                  archive_file=tmp_path / "a.json", state_file=tmp_path / "s.json")
    assert called == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv\Scripts\python -m pytest tests/test_news_run_daily.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# newsletter/run_daily.py
"""
Entry point giornaliero della newsletter (digest premium).

Fetch + score indipendenti dal bot live (riuso read-only di scraper/scorer),
archiviazione di TUTTI i segnali sopra soglia, invio digest per ogni lingua
configurata. Stato di idempotenza proprio (newsletter_state.json).

Schedulare nei giorni feriali ~19:00 WITA (= ~7:00 ET, pre-market USA):
  venv\\Scripts\\python -m newsletter.run_daily
"""

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

import config as bot_config
from scorer import score_all, TickerSignal
from scraper import fetch_all_edgar_transactions

from newsletter import archive, config_news, digest, telegram_news

logging.basicConfig(
    filename=str(config_news.NEWS_DIR / "newsletter_errors.log"),
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _fetch_signals(today: Optional[date] = None) -> List[TickerSignal]:
    """Fetch transazioni EDGAR e scoring.

    Lookback: 1 giorno feriale; il lunedì 3 giorni per coprire i filing
    depositati nel weekend. L'archivio è comunque idempotente per
    (date, ticker), quindi un'eventuale sovrapposizione non duplica.
    """
    today = today or date.today()
    lookback = 3 if today.weekday() == 0 else 1
    transactions = fetch_all_edgar_transactions(
        bot_config.MIN_TRANSACTION_VALUE, lookback
    )
    return score_all(transactions)


def _load_state(state_file: Path) -> dict:
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def run(
    today: Optional[date] = None,
    archive_file: Optional[Path] = None,
    state_file: Optional[Path] = None,
) -> None:
    """Orchestrazione: fetch → filtro soglia → archivio → digest per lingua."""
    today = today or date.today()
    state_file = state_file or config_news.STATE_FILE

    if today.weekday() >= 5:
        return

    state = _load_state(state_file)
    if state.get("last_daily") == today.isoformat():
        logger.info("Digest già inviato oggi — skip.")
        return

    signals = _fetch_signals(today)
    eligible = [s for s in signals if s.score >= config_news.MIN_DIGEST_SCORE]
    archive.append_signals(eligible, today, archive_file=archive_file)

    entries = [e for e in archive.load_week(today, archive_file=archive_file)
               if e["date"] == today.isoformat()]

    token = os.environ["TELEGRAM_TOKEN"].strip()
    review_chat = os.environ["NEWS_REVIEW_CHAT_ID"].strip()
    all_sent = True
    for lang in config_news.DIGEST_LANGS:
        premium_chat = os.environ[f"NEWS_PREMIUM_CHAT_ID_{lang.upper()}"].strip()
        text = digest.build_digest(entries, today, lang=lang)
        ok = telegram_news.send_digest(
            text, token=token, premium_chat_id=premium_chat,
            review_chat_id=review_chat, review_mode=config_news.REVIEW_MODE,
        )
        all_sent = all_sent and ok

    if all_sent:
        state["last_daily"] = today.isoformat()
        _save_state(state, state_file)


def main() -> None:
    load_dotenv()
    try:
        run()
    except Exception as exc:
        logger.error("run_daily fatal: %s", exc, exc_info=True)
        try:
            telegram_news.notify_user(
                f"⚠️ NEWSLETTER daily — errore: {exc}",
                token=os.environ.get("TELEGRAM_TOKEN", "").strip(),
                review_chat_id=os.environ.get("NEWS_REVIEW_CHAT_ID", "").strip(),
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
```

**Nota per l'esecutore:** verificare la firma reale di `fetch_all_edgar_transactions` in `scraper.py` (posizionale vs keyword `lookback_days`) e adeguare SOLO la chiamata in `run_daily.py` — mai modificare `scraper.py`. Se il parametro si chiama diversamente (es. `lookback_calendar_days`), usare quello.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv\Scripts\python -m pytest tests/test_news_run_daily.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add newsletter/run_daily.py tests/test_news_run_daily.py
git commit -m "feat(newsletter): daily digest orchestration with own idempotency state"
```

---

### Task 7: Report settimanale strutturato (`weekly.py`)

**Files:**
- Create: `newsletter/weekly.py`
- Test: `tests/test_news_weekly.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_weekly.py
"""Tests for newsletter.weekly — report strutturato per la generazione."""

from datetime import date

from newsletter import weekly


def _entry(ticker, score, day="2026-07-15"):
    return {
        "date": day, "ticker": ticker, "company": f"{ticker} Corp",
        "score": score, "score_breakdown": [], "total_value": 100_000.0,
        "insiders": [{"name": "A B", "title": "CEO", "value": 100_000.0}],
    }


def _tr():
    return {"n_trades": 10, "n_wins": 6, "win_rate_pct": 60.0,
            "total_pnl": 123.45, "avg_pnl_pct": 1.2,
            "best": {"ticker": "AAA", "pnl_pct": 9.0},
            "worst": {"ticker": "BBB", "pnl_pct": -4.0}, "recent": []}


def test_build_report_splits_top_and_rest():
    entries = [_entry("A", 14), _entry("B", 11), _entry("C", 9),
               _entry("D", 8), _entry("E", 6)]
    report = weekly.build_weekly_report(
        entries, _tr(), week_end=date(2026, 7, 17), top_n=3,
    )
    assert report["week_end"] == "2026-07-17"
    assert [s["ticker"] for s in report["top_signals"]] == ["A", "B", "C"]
    assert report["n_other_signals"] == 2
    assert report["track_record"]["win_rate_pct"] == 60.0


def test_build_report_slow_week_flag():
    report = weekly.build_weekly_report([], _tr(), week_end=date(2026, 7, 17))
    assert report["slow_week"] is True
    assert report["top_signals"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv\Scripts\python -m pytest tests/test_news_weekly.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# newsletter/weekly.py
"""
Report settimanale strutturato (input per la generazione LLM).

Combina i segnali archiviati della settimana con il track record: i top N
finiscono nel dettaglio della newsletter gratuita, il resto è citato in
forma aggregata (il valore pieno resta nel premium).
"""

from datetime import date
from typing import List

from newsletter import config_news


def build_weekly_report(
    week_entries: List[dict], track_record: dict,
    week_end: date, top_n: int = config_news.WEEKLY_TOP_N,
) -> dict:
    """Costruisce il dict-report della settimana. slow_week=True se vuota."""
    ordered = sorted(week_entries, key=lambda e: e["score"], reverse=True)
    return {
        "week_end": week_end.isoformat(),
        "slow_week": len(ordered) == 0,
        "top_signals": ordered[:top_n],
        "n_other_signals": max(0, len(ordered) - top_n),
        "track_record": track_record,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv\Scripts\python -m pytest tests/test_news_weekly.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add newsletter/weekly.py tests/test_news_weekly.py
git commit -m "feat(newsletter): weekly structured report builder"
```

---

### Task 8: Generazione con Claude Code headless (`generate.py`)

**Files:**
- Create: `newsletter/generate.py`
- Test: `tests/test_news_generate.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_generate.py
"""Tests for newsletter.generate — Claude headless, subprocess mockato."""

import subprocess

import pytest

from newsletter import generate


def _report():
    return {"week_end": "2026-07-17", "slow_week": False,
            "top_signals": [{"ticker": "ABC", "company": "Acme", "score": 12,
                             "total_value": 750000.0, "date": "2026-07-15",
                             "insiders": [{"name": "J D", "title": "CEO",
                                           "value": 750000.0}],
                             "score_breakdown": []}],
            "n_other_signals": 2,
            "track_record": {"n_trades": 10, "win_rate_pct": 60.0,
                             "total_pnl": 100.0, "avg_pnl_pct": 1.0,
                             "best": None, "worst": None, "recent": []}}


def test_build_prompt_contains_report_and_language():
    p_en = generate.build_prompt(_report(), lang="en")
    p_it = generate.build_prompt(_report(), lang="it")
    assert "ABC" in p_en and "win rate" in p_en.lower()
    assert "English" in p_en
    assert "italiano" in p_it


def test_generate_invokes_claude_cli(monkeypatch):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="# Newsletter\nbody", stderr="")

    monkeypatch.setattr(generate.subprocess, "run", fake_run)
    monkeypatch.setattr(generate.shutil, "which", lambda name: r"C:\claude.cmd")

    out = generate.generate_newsletter(_report(), lang="en")
    assert out == "# Newsletter\nbody"
    assert calls["cmd"][0] == r"C:\claude.cmd"
    assert calls["cmd"][1] == "-p"


def test_generate_raises_if_claude_missing(monkeypatch):
    monkeypatch.setattr(generate.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="claude CLI"):
        generate.generate_newsletter(_report(), lang="en")


def test_generate_raises_on_nonzero_exit(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(generate.subprocess, "run", fake_run)
    monkeypatch.setattr(generate.shutil, "which", lambda name: "claude")
    with pytest.raises(RuntimeError, match="boom"):
        generate.generate_newsletter(_report(), lang="en")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv\Scripts\python -m pytest tests/test_news_generate.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# newsletter/generate.py
"""
Generazione della newsletter settimanale via Claude Code headless.

Invoca `claude -p <prompt>` come subprocess: usa l'abbonamento Claude
dell'utente (nessun costo API). Il prompt contiene il report strutturato
in JSON e le istruzioni editoriali per lingua.
"""

import json
import shutil
import subprocess

from newsletter import config_news

_STYLE = {
    "en": (
        "Write the newsletter in English. Audience: retail investors interested "
        "in US insider buying. Tone: factual, concise, no hype, no financial advice. "
        "Structure (markdown): a 2-3 sentence intro on the week; one section per top "
        "signal (what happened, who bought, why the score is what it is); a 'Track "
        "Record' section presenting the stats as verifiable facts; a closing line "
        "reminding that premium subscribers received these signals pre-market daily. "
        f"End with this exact disclaimer: \"{config_news.DISCLAIMER_EN}\""
    ),
    "it": (
        "Scrivi la newsletter in italiano (adattamento naturale, non traduzione "
        "letterale). Pubblico: investitori retail italiani interessati agli acquisti "
        "insider USA. Tono: fattuale, conciso, niente hype, nessun consiglio "
        "finanziario. Struttura (markdown): intro di 2-3 frasi sulla settimana; una "
        "sezione per ogni top segnale; una sezione 'Track Record' con le statistiche "
        "presentate come fatti verificabili; chiusura che ricorda che gli abbonati "
        "premium ricevono questi segnali ogni mattina pre-market. "
        f"Chiudi con questo disclaimer esatto: \"{config_news.DISCLAIMER_IT}\""
    ),
}

_SLOW_WEEK_NOTE = (
    "NOTE: this was a slow week with no qualifying signals. Write a shorter "
    "issue: follow up on how previous weeks' signals performed (use the track "
    "record data) instead of forcing weak content."
)


def build_prompt(report: dict, lang: str) -> str:
    """Prompt completo: istruzioni editoriali + report JSON."""
    parts = [
        "You are the writer of an insider-trading newsletter based on a "
        "quantitative SEC Form 4 signal system. Use ONLY the data provided "
        "below; never invent numbers, names, or performance figures.",
        _STYLE[lang],
    ]
    if report.get("slow_week"):
        parts.append(_SLOW_WEEK_NOTE)
    parts.append("DATA (JSON):")
    parts.append(json.dumps(report, indent=2))
    parts.append("Output ONLY the newsletter markdown, no preamble.")
    return "\n\n".join(parts)


def generate_newsletter(report: dict, lang: str) -> str:
    """Genera il markdown della newsletter invocando claude -p."""
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("claude CLI non trovato nel PATH — serve Claude Code installato")
    prompt = build_prompt(report, lang)
    result = subprocess.run(
        [exe, "-p", prompt],
        capture_output=True, text=True, encoding="utf-8",
        timeout=config_news.CLAUDE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed (exit {result.returncode}): {result.stderr}")
    return result.stdout.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv\Scripts\python -m pytest tests/test_news_generate.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add newsletter/generate.py tests/test_news_generate.py
git commit -m "feat(newsletter): weekly generation via Claude Code headless"
```

---

### Task 9: Client beehiiv con fallback locale (`beehiiv_client.py`)

L'endpoint beehiiv v2 per creare post via API potrebbe non essere disponibile sul piano gratuito: il client tenta l'API e, su errore 4xx, degrada a salvataggio locale (il file .md viene comunque sempre scritto da run_weekly — il fallback è la modalità operativa di default finché l'API non è verificata).

**Files:**
- Create: `newsletter/beehiiv_client.py`
- Test: `tests/test_news_beehiiv.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_beehiiv.py
"""Tests for newsletter.beehiiv_client — API mockata, mai rete reale."""

import requests

from newsletter import beehiiv_client


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def test_create_draft_success(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, body=json)
        return _Resp(201, {"data": {"id": "post_123"}})

    monkeypatch.setattr(beehiiv_client.requests, "post", fake_post)
    post_id = beehiiv_client.create_draft(
        pub_id="pub_en", title="Issue #1", body_md="# Hello", api_key="KEY",
    )
    assert post_id == "post_123"
    assert "pub_en" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer KEY"
    assert captured["body"]["status"] == "draft"


def test_create_draft_returns_none_on_api_error(monkeypatch):
    monkeypatch.setattr(beehiiv_client.requests, "post",
                        lambda *a, **k: _Resp(403))
    post_id = beehiiv_client.create_draft(
        pub_id="pub_en", title="t", body_md="b", api_key="KEY",
    )
    assert post_id is None  # fallback: il chiamante usa i file locali


def test_create_draft_returns_none_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("net down")
    monkeypatch.setattr(beehiiv_client.requests, "post", boom)
    assert beehiiv_client.create_draft("p", "t", "b", "K") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv\Scripts\python -m pytest tests/test_news_beehiiv.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# newsletter/beehiiv_client.py
"""
Client minimale per l'API beehiiv v2: creazione bozze post.

Se l'API rifiuta (piano/endpoint non disponibile) o la rete fallisce,
ritorna None: il chiamante ha già salvato i .md locali come fallback,
quindi nessun errore è fatale.
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_BASE = "https://api.beehiiv.com/v2"


def create_draft(pub_id: str, title: str, body_md: str, api_key: str) -> Optional[str]:
    """Crea una bozza post. Ritorna il post id, o None su qualsiasi errore."""
    url = f"{_BASE}/publications/{pub_id}/posts"
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"title": title, "body_content": body_md, "status": "draft"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"]["id"]
    except (requests.RequestException, KeyError, ValueError) as e:
        logger.warning("beehiiv create_draft fallita (%s): fallback locale", e)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv\Scripts\python -m pytest tests/test_news_beehiiv.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add newsletter/beehiiv_client.py tests/test_news_beehiiv.py
git commit -m "feat(newsletter): beehiiv draft client with graceful local fallback"
```

**Nota per l'esecutore:** al primo uso reale, verificare su https://developers.beehiiv.com il payload esatto dell'endpoint create-post (campo body: `body_content` vs altro) e correggere SOLO questo client. Se l'endpoint non esiste sul piano gratuito, il fallback locale è la modalità operativa definitiva: l'utente incolla il .md nell'editor beehiiv (2 minuti).

---

### Task 10: Orchestrazione settimanale (`run_weekly.py`)

**Files:**
- Create: `newsletter/run_weekly.py`
- Test: `tests/test_news_run_weekly.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_news_run_weekly.py
"""Tests for newsletter.run_weekly — orchestrazione bozze settimanali."""

from datetime import date

from newsletter import run_weekly


def _setup(monkeypatch, tmp_path, draft_id="post_1"):
    sent = []
    monkeypatch.setattr(run_weekly.archive, "load_week",
                        lambda end_date, archive_file=None: [])
    monkeypatch.setattr(run_weekly.track_record, "load_portfolio", lambda: {})
    monkeypatch.setattr(run_weekly.track_record, "compute_track_record",
                        lambda pf: {"n_trades": 0, "n_wins": 0,
                                    "win_rate_pct": 0.0, "total_pnl": 0.0,
                                    "avg_pnl_pct": 0.0, "best": None,
                                    "worst": None, "recent": []})
    monkeypatch.setattr(run_weekly.generate, "generate_newsletter",
                        lambda report, lang: f"# Issue {lang}\nbody")
    monkeypatch.setattr(run_weekly.beehiiv_client, "create_draft",
                        lambda **kw: draft_id)
    monkeypatch.setattr(run_weekly.telegram_news, "notify_user",
                        lambda text, **kw: sent.append(text) or True)
    env = {"TELEGRAM_TOKEN": "T", "NEWS_REVIEW_CHAT_ID": "U",
           "BEEHIIV_API_KEY": "K", "BEEHIIV_PUB_ID_EN": "pe",
           "BEEHIIV_PUB_ID_IT": "pi"}
    monkeypatch.setattr(run_weekly.os, "environ", env)
    return sent


def test_run_writes_both_md_files_and_notifies(tmp_path, monkeypatch):
    sent = _setup(monkeypatch, tmp_path)
    run_weekly.run(today=date(2026, 7, 19), output_dir=tmp_path,
                   state_file=tmp_path / "state.json")

    assert (tmp_path / "2026-07-19-en.md").read_text(encoding="utf-8").startswith("# Issue en")
    assert (tmp_path / "2026-07-19-it.md").read_text(encoding="utf-8").startswith("# Issue it")
    assert len(sent) == 1
    assert "post_1" in sent[0]


def test_run_notifies_fallback_when_beehiiv_fails(tmp_path, monkeypatch):
    sent = _setup(monkeypatch, tmp_path, draft_id=None)
    run_weekly.run(today=date(2026, 7, 19), output_dir=tmp_path,
                   state_file=tmp_path / "state.json")
    assert "manuale" in sent[0].lower() or "file" in sent[0].lower()


def test_run_is_idempotent_per_day(tmp_path, monkeypatch):
    sent = _setup(monkeypatch, tmp_path)
    run_weekly.run(today=date(2026, 7, 19), output_dir=tmp_path,
                   state_file=tmp_path / "state.json")
    run_weekly.run(today=date(2026, 7, 19), output_dir=tmp_path,
                   state_file=tmp_path / "state.json")
    assert len(sent) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv\Scripts\python -m pytest tests/test_news_run_weekly.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# newsletter/run_weekly.py
"""
Entry point settimanale della newsletter.

Archivio settimana + track record → report → generazione EN/IT (Claude
headless) → salvataggio .md locali (sempre) → tentativo bozze beehiiv →
notifica Telegram all'utente per la review.

Schedulare la domenica sera (invio manuale lunedì mattina USA dopo review):
  venv\\Scripts\\python -m newsletter.run_weekly
"""

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from newsletter import (archive, beehiiv_client, config_news, generate,
                        telegram_news, track_record, weekly)

logging.basicConfig(
    filename=str(config_news.NEWS_DIR / "newsletter_errors.log"),
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

_LANGS = ["en", "it"]


def _load_state(state_file: Path) -> dict:
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return {}


def _save_state(state: dict, state_file: Path) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def run(
    today: Optional[date] = None,
    output_dir: Optional[Path] = None,
    state_file: Optional[Path] = None,
) -> None:
    """Orchestrazione settimanale completa."""
    today = today or date.today()
    output_dir = output_dir or config_news.OUTPUT_DIR
    state_file = state_file or config_news.STATE_FILE

    state = _load_state(state_file)
    if state.get("last_weekly") == today.isoformat():
        logger.info("Weekly già generata oggi — skip.")
        return

    week = archive.load_week(end_date=today)
    tr = track_record.compute_track_record(track_record.load_portfolio())
    report = weekly.build_weekly_report(week, tr, week_end=today)

    output_dir.mkdir(parents=True, exist_ok=True)
    api_key = os.environ["BEEHIIV_API_KEY"].strip()
    results = []
    for lang in _LANGS:
        body_md = generate.generate_newsletter(report, lang=lang)
        md_path = output_dir / f"{today.isoformat()}-{lang}.md"
        md_path.write_text(body_md, encoding="utf-8")

        title = body_md.splitlines()[0].lstrip("# ").strip() if body_md else f"Issue {today}"
        pub_id = os.environ[f"BEEHIIV_PUB_ID_{lang.upper()}"].strip()
        post_id = beehiiv_client.create_draft(
            pub_id=pub_id, title=title, body_md=body_md, api_key=api_key,
        )
        if post_id:
            results.append(f"{lang.upper()}: bozza beehiiv {post_id}")
        else:
            results.append(
                f"{lang.upper()}: beehiiv non disponibile — caricamento manuale "
                f"del file {md_path.name}"
            )

    telegram_news.notify_user(
        "📰 NEWSLETTER settimanale pronta per la review:\n"
        + "\n".join(f"• {r}" for r in results)
        + f"\nFile in: {output_dir}",
        token=os.environ["TELEGRAM_TOKEN"].strip(),
        review_chat_id=os.environ["NEWS_REVIEW_CHAT_ID"].strip(),
    )
    state["last_weekly"] = today.isoformat()
    _save_state(state, state_file)


def main() -> None:
    load_dotenv()
    try:
        run()
    except Exception as exc:
        logger.error("run_weekly fatal: %s", exc, exc_info=True)
        try:
            telegram_news.notify_user(
                f"⚠️ NEWSLETTER weekly — errore: {exc}",
                token=os.environ.get("TELEGRAM_TOKEN", "").strip(),
                review_chat_id=os.environ.get("NEWS_REVIEW_CHAT_ID", "").strip(),
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv\Scripts\python -m pytest tests/test_news_run_weekly.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add newsletter/run_weekly.py tests/test_news_run_weekly.py
git commit -m "feat(newsletter): weekly orchestration with beehiiv drafts and review notification"
```

---

### Task 11: Dry-run end-to-end, .bat e documentazione

**Files:**
- Create: `newsletter/dry_run.py`
- Create: `run_newsletter_daily.bat`
- Create: `run_newsletter_weekly.bat`
- Create: `newsletter/README.md`

- [ ] **Step 1: Script di dry-run (nessun invio, nessuna scrittura persistente)**

```python
# newsletter/dry_run.py
"""
Dry-run end-to-end della pipeline newsletter: fetch reale da EDGAR,
digest e report generati e STAMPATI a terminale. Nessun Telegram,
nessun beehiiv, nessuna scrittura su archivio/stato reali.

Uso: venv\\Scripts\\python -m newsletter.dry_run [--with-claude]
  --with-claude: genera anche la newsletter EN via claude -p (lento)
"""

import sys
import tempfile
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from newsletter import archive, config_news, digest, generate, track_record, weekly
from newsletter.run_daily import _fetch_signals


def main() -> None:
    load_dotenv()
    today = date.today()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_archive = Path(tmp) / "archive.json"

        print("=== FETCH + SCORE (EDGAR reale) ===")
        signals = _fetch_signals()
        eligible = [s for s in signals if s.score >= config_news.MIN_DIGEST_SCORE]
        print(f"{len(signals)} segnali totali, {len(eligible)} sopra soglia\n")

        archive.append_signals(eligible, today, archive_file=tmp_archive)
        entries = archive.load_week(today, archive_file=tmp_archive)

        print("=== DIGEST GIORNALIERO (EN) ===")
        print(digest.build_digest(entries, today, lang="en"), "\n")

        print("=== TRACK RECORD (portfolio reale, sola lettura) ===")
        tr = track_record.compute_track_record(track_record.load_portfolio())
        print(tr, "\n")

        report = weekly.build_weekly_report(entries, tr, week_end=today)
        print("=== REPORT SETTIMANALE (struttura) ===")
        print(report, "\n")

        if "--with-claude" in sys.argv:
            print("=== NEWSLETTER EN (claude -p, attendere...) ===")
            print(generate.generate_newsletter(report, lang="en"))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: File .bat per Task Scheduler**

```bat
@echo off
REM run_newsletter_daily.bat — digest premium giornaliero
cd /d "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker"
venv\Scripts\python.exe -m newsletter.run_daily
```

```bat
@echo off
REM run_newsletter_weekly.bat — bozze newsletter settimanale EN/IT
cd /d "C:\Users\corr8\Desktop\obsidian-vault\Insider Project\InsiderTracker"
venv\Scripts\python.exe -m newsletter.run_weekly
```

- [ ] **Step 3: README del modulo**

```markdown
# newsletter/ — Insider Newsletter

Modulo indipendente dal bot live (riuso read-only di scraper/scorer/portfolio).

## Pipeline
- **Giornaliera** (`run_daily`): fetch EDGAR → score → archivio → digest premium
  su Telegram (template Python, no LLM). Feriali ~19:00 WITA (= ~7:00 ET).
- **Settimanale** (`run_weekly`): archivio 7gg + track record → report →
  `claude -p` (EN + IT) → .md in `newsletter/output/` → bozze beehiiv (se
  disponibile) → notifica review su Telegram. Domenica sera.

## Variabili d'ambiente (.env)
| Var | Uso |
|---|---|
| `TELEGRAM_TOKEN` | riusato dal bot live |
| `NEWS_PREMIUM_CHAT_ID_EN` | canale Telegram premium (EN) |
| `NEWS_REVIEW_CHAT_ID` | chat personale per review/notifiche |
| `BEEHIIV_API_KEY` | API key beehiiv |
| `BEEHIIV_PUB_ID_EN` / `BEEHIIV_PUB_ID_IT` | id pubblicazioni |

## Rodaggio
`config_news.REVIEW_MODE = True` (default): il digest va SOLO alla tua chat.
Dopo 2-3 settimane di digest corretti → mettere `False`.

## Test
Eseguire SOLO i file nominati: `venv\Scripts\python -m pytest tests/test_news_archive.py -v`
(mai pytest sull'intera cartella tests/).

## Dry-run
`venv\Scripts\python -m newsletter.dry_run` (aggiungere `--with-claude` per
generare anche la newsletter EN reale).
```

- [ ] **Step 4: Verifica manuale del dry-run**

Run: `venv\Scripts\python -m newsletter.dry_run`
Expected: stampa segnali reali del giorno (o zero), digest EN formattato, track record dal portfolio reale, struttura report. Nessun messaggio Telegram inviato, nessun file scritto fuori dal tmp.

Poi: `venv\Scripts\python -m newsletter.dry_run --with-claude`
Expected: markdown newsletter EN completo e sensato (verificare a occhio: numeri coerenti col report, disclaimer presente, nessun dato inventato).

- [ ] **Step 5: Commit**

```bash
git add newsletter/dry_run.py newsletter/README.md run_newsletter_daily.bat run_newsletter_weekly.bat
git commit -m "feat(newsletter): dry-run script, scheduler bats, module README"
```

---

## Fuori scope di questo piano (fase 2)

- **Posting automatico su X** (1-2 post/settimana con segnale gratuito + link): bloccato dalle chiavi API X ancora da configurare dall'utente (dipendenza Copy Funnel). Quando disponibili, aggiungere `newsletter/x_promo.py` riusando la pipeline in `ctrader-portfolio/copyfunnel/`.
- **Promozione IG via ReelFactory**: parte quando ReelFactory sarà live.
- **Alert infrasettimanali istantanei**: l'infrastruttura attuale gira una volta al giorno; il digest giornaliero pre-market È l'alert. Alert intraday richiederebbero un run schedulato più frequente — valutare dopo il rodaggio.
- **Passaggio full-auto del digest** (REVIEW_MODE = False): decisione utente dopo 2-3 settimane di rodaggio.

## Setup manuale richiesto all'utente (fuori dal codice)

Da fare PRIMA del primo run reale (il codice funziona in dry-run anche senza):

1. **beehiiv**: creare account gratuito + 2 pubblicazioni (EN e IT), scegliere nome/descrizione definitivi, generare API key, recuperare i publication id → `.env`
2. **Telegram**: creare canale privato premium (EN), aggiungere il bot esistente come admin, recuperare chat_id → `.env` (`NEWS_PREMIUM_CHAT_ID_EN`); recuperare il proprio chat_id personale → `NEWS_REVIEW_CHAT_ID`
3. **Whop**: creare prodotto $5/mese collegato al canale Telegram premium (si può rimandare a dopo il rodaggio: finché REVIEW_MODE è attivo non c'è nessun cliente)
4. **Task Scheduler**: 2 task — `run_newsletter_daily.bat` (Lun-Ven 19:00 WITA), `run_newsletter_weekly.bat` (Dom 20:00 WITA)
5. **Nome definitivo** della newsletter (attualmente "Insider Weekly", nome di lavoro)

## Criteri di completamento (dalla spec)

- [ ] Tutti i test `tests/test_news_*.py` passano (eseguiti file per file)
- [ ] Dry-run end-to-end eseguito e output verificato dall'utente
- [ ] 2-3 numeri di prova generati e approvati dall'utente prima di qualsiasi invio reale
- [ ] Nessun file del sistema live modificato (verificare con `git diff --stat` che le modifiche siano solo in `newsletter/`, `tests/test_news_*`, `*.bat`)
