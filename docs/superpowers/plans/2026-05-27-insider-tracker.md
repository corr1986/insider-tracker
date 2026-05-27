# Insider Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python script that scrapes OpenInsider daily, scores insider purchases by role/value/cluster, and sends the top-1 signal via Telegram at 8:00 AM Italian time via Windows Task Scheduler.

**Architecture:** Five focused modules (config → scraper → scorer → notifier → orchestrator) wired by `insider_tracker.py`. No daemon — Windows Task Scheduler fires the script once per day and the script exits. A `last_seen.json` file prevents duplicate sends.

**Tech Stack:** Python 3.11+, requests, beautifulsoup4, python-dotenv, pytest

---

## File Map

| File | Responsibility |
|---|---|
| `config.py` | All constants and scoring weights |
| `scraper.py` | Fetch + parse OpenInsider HTML → `InsiderTransaction` list |
| `scorer.py` | Group by ticker, calculate score → `TickerSignal` list |
| `notifier.py` | Format Telegram messages, call Telegram API |
| `insider_tracker.py` | Orchestration: fetch → score → pick → send → persist |
| `tests/test_scraper.py` | Unit tests for HTML parsing and filtering |
| `tests/test_scorer.py` | Unit tests for scoring algorithm |
| `tests/test_notifier.py` | Unit tests for message formatting and API call |
| `tests/test_tracker.py` | Unit tests for orchestration logic |
| `run_insider.bat` | Windows launcher for Task Scheduler |
| `requirements.txt` | Pinned dependencies |
| `.env.example` | Credential template |

---

### Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `tests/__init__.py`

- [ ] **Step 1: Activate virtual environment**

```bat
cd C:\Users\corr8\Desktop\InsiderTracker
python -m venv venv
venv\Scripts\activate
```

- [ ] **Step 2: Create requirements.txt**

```
requests==2.32.3
beautifulsoup4==4.12.3
python-dotenv==1.0.1
pytest==8.3.5
```

- [ ] **Step 3: Install dependencies**

```bat
pip install -r requirements.txt
```

Expected: All packages install without errors.

- [ ] **Step 4: Create .env.example**

```
TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

- [ ] **Step 5: Copy .env.example to .env and fill in credentials**

Copy `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` from:
`C:\Users\corr8\Desktop\obsidian-vault\Stock Market Bot\.env`

- [ ] **Step 6: Create .gitignore**

```
venv/
.env
last_seen.json
errors.log
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 7: Create tests/__init__.py**

Empty file — required for pytest to discover the tests package.

```python
```

- [ ] **Step 8: Commit**

```bat
git init
git add requirements.txt .env.example .gitignore tests/__init__.py
git commit -m "chore: project setup"
```

---

### Task 2: config.py — Constants

**Files:**
- Create: `config.py`

- [ ] **Step 1: Create config.py**

```python
# OpenInsider URLs to scrape (all free, no auth required)
OPENINSIDER_URLS = [
    "https://openinsider.com/latest-cluster-buys",
    "https://openinsider.com/latest-ceo-cfo-purchases-25k",
    (
        "https://openinsider.com/screener?s=0&o=&pl=&ph=&ll=&lh="
        "&fd=3&fdr=&td=&tdr=&fdlyl=&fdlyh=&daysago=&xp=1&xs=1"
        "&vl=50&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999"
        "&grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h="
        "&oc2l=&oc2h=&sortcol=0&cnt=40&Action=screener"
    ),
]

# Minimum transaction value (USD) to include in scoring
MIN_TRANSACTION_VALUE = 50_000

# Minimum score required to send a Telegram alert (below = "no signal today")
MIN_SCORE = 5

# Calendar days to look back (7 = safe window covering 3 business days + weekend)
LOOKBACK_CALENDAR_DAYS = 7

# Scoring weights — insider role
SCORE_CEO = 4
SCORE_CFO = 3
SCORE_OTHER = 1

# Scoring weights — transaction value
SCORE_VALUE_SMALL = 1    # $50K – $100K
SCORE_VALUE_MED = 2      # $100K – $500K
SCORE_VALUE_LARGE = 4    # $500K+

# Scoring weights — cluster buy
SCORE_CLUSTER_2 = 3      # 2 insiders, same ticker, within lookback window
SCORE_CLUSTER_3PLUS = 6  # 3+ insiders, same ticker, within lookback window
SCORE_CLUSTER_TOTAL = 3  # bonus when total cluster value ≥ threshold
CLUSTER_TOTAL_THRESHOLD = 500_000
```

- [ ] **Step 2: Verify config imports cleanly**

```bat
python -c "import config; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bat
git add config.py
git commit -m "feat: add config constants"
```

---

### Task 3: scraper.py — Fetch and Parse OpenInsider

**Files:**
- Create: `scraper.py`
- Create: `tests/test_scraper.py`

- [ ] **Step 1: Inspect live OpenInsider HTML to verify column order**

Run this once to confirm the column indices before writing the parser:

```bat
python -c "
import requests
from bs4 import BeautifulSoup
r = requests.get('https://openinsider.com/latest-ceo-cfo-purchases-25k', headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.text, 'html.parser')
table = soup.find('table', {'class': 'tinytable'})
headers = [th.get_text(strip=True) for th in table.find_all('th')]
print('Headers:', headers)
first_row = table.find('tbody').find_all('tr')[0]
cols = [td.get_text(strip=True) for td in first_row.find_all('td')]
for i, c in enumerate(cols): print(i, repr(c))
"
```

Expected column order (adjust indices below if different):
- 0: X, 1: Filing Date, 2: Trade Date, 3: Ticker, 4: Company,
  5: Insider Name, 6: Title, 7: Trade Type, 8: Price,
  9: Qty, 10: Owned, 11: ΔOwn, **12: Value**

- [ ] **Step 2: Write failing tests**

Create `tests/test_scraper.py`:

```python
from datetime import date, timedelta
from scraper import parse_transactions, deduplicate, InsiderTransaction

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
```

- [ ] **Step 3: Run tests to verify they fail**

```bat
pytest tests/test_scraper.py -v
```

Expected: `ModuleNotFoundError: No module named 'scraper'`

- [ ] **Step 4: Create scraper.py**

```python
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional
import re
import logging

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class InsiderTransaction:
    ticker: str
    company: str
    insider_name: str
    title: str
    value: float
    trade_date: Optional[date]


def _parse_value(value_str: str) -> float:
    """Parse '$1,234,567' → 1234567.0"""
    clean = re.sub(r"[^\d.]", "", value_str)
    return float(clean) if clean else 0.0


def _parse_date(date_str: str) -> Optional[date]:
    """Parse 'YYYY-MM-DD ...' → date. Returns None on failure."""
    try:
        return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return None


def parse_transactions(
    html: str, min_value: float, lookback_days: int
) -> List[InsiderTransaction]:
    """Parse OpenInsider HTML table and return filtered InsiderTransaction list."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "tinytable"})
    if not table:
        return []

    tbody = table.find("tbody")
    if not tbody:
        return []

    cutoff = date.today() - timedelta(days=lookback_days)
    transactions = []

    for row in tbody.find_all("tr"):
        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) < 13:
            continue

        # Column indices (verified against OpenInsider HTML — see Task 3 Step 1):
        # 0: X, 1: Filing Date, 2: Trade Date, 3: Ticker, 4: Company,
        # 5: Insider Name, 6: Title, 7: Trade Type, 8: Price,
        # 9: Qty, 10: Owned, 11: ΔOwn, 12: Value
        if cols[7] != "P":          # only open-market purchases
            continue

        trade_date = _parse_date(cols[2])
        if trade_date is None or trade_date < cutoff:
            continue

        value = _parse_value(cols[12])
        if value < min_value:
            continue

        ticker = cols[3].upper().strip()
        company = cols[4].strip()
        if not ticker or not company:
            continue

        transactions.append(InsiderTransaction(
            ticker=ticker,
            company=company,
            insider_name=cols[5].strip(),
            title=cols[6].strip(),
            value=value,
            trade_date=trade_date,
        ))

    return transactions


def fetch_transactions(
    url: str, min_value: float, lookback_days: int
) -> List[InsiderTransaction]:
    """Fetch and parse insider transactions from a live OpenInsider URL."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; InsiderTracker/1.0)"}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return parse_transactions(response.text, min_value, lookback_days)


def deduplicate(transactions: List[InsiderTransaction]) -> List[InsiderTransaction]:
    """Remove duplicate transactions (same ticker + insider name + trade date)."""
    seen: set = set()
    result = []
    for t in transactions:
        key = (t.ticker, t.insider_name, t.trade_date)
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

```bat
pytest tests/test_scraper.py -v
```

Expected: All 7 tests PASSED.

- [ ] **Step 6: Commit**

```bat
git add scraper.py tests/test_scraper.py
git commit -m "feat: add scraper with HTML parsing and deduplication"
```

---

### Task 4: scorer.py — Scoring Algorithm

**Files:**
- Create: `scorer.py`
- Create: `tests/test_scorer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_scorer.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bat
pytest tests/test_scorer.py -v
```

Expected: `ModuleNotFoundError: No module named 'scorer'`

- [ ] **Step 3: Create scorer.py**

```python
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple

import config
from scraper import InsiderTransaction


@dataclass
class TickerSignal:
    ticker: str
    company: str
    transactions: List[InsiderTransaction]
    score: int = 0
    score_breakdown: List[str] = field(default_factory=list)


def _role_score(title: str) -> Tuple[int, str]:
    t = title.upper()
    if "CEO" in t or "CHIEF EXECUTIVE" in t:
        return config.SCORE_CEO, f"CEO buy +{config.SCORE_CEO}"
    if "CFO" in t or "CHIEF FINANCIAL" in t:
        return config.SCORE_CFO, f"CFO buy +{config.SCORE_CFO}"
    return config.SCORE_OTHER, f"Officer buy +{config.SCORE_OTHER}"


def _value_score(value: float) -> Tuple[int, str]:
    if value >= 500_000:
        return config.SCORE_VALUE_LARGE, f"Importo ${value:,.0f} (≥$500K) +{config.SCORE_VALUE_LARGE}"
    if value >= 100_000:
        return config.SCORE_VALUE_MED, f"Importo ${value:,.0f} (≥$100K) +{config.SCORE_VALUE_MED}"
    return config.SCORE_VALUE_SMALL, f"Importo ${value:,.0f} (≥$50K) +{config.SCORE_VALUE_SMALL}"


def score_ticker(ticker: str, transactions: List[InsiderTransaction]) -> TickerSignal:
    company = transactions[0].company if transactions else ""
    signal = TickerSignal(ticker=ticker, company=company, transactions=transactions)

    # Role points: one entry per transaction
    for tx in transactions:
        pts, label = _role_score(tx.title)
        signal.score += pts
        signal.score_breakdown.append(f"• {label}")

    # Value points: based on the highest single transaction
    max_tx = max(transactions, key=lambda t: t.value)
    pts, label = _value_score(max_tx.value)
    signal.score += pts
    signal.score_breakdown.append(f"• {label}")

    # Cluster bonus: based on number of distinct insiders
    n = len(transactions)
    if n >= 3:
        signal.score += config.SCORE_CLUSTER_3PLUS
        signal.score_breakdown.append(f"• Cluster {n} insider +{config.SCORE_CLUSTER_3PLUS}")
    elif n == 2:
        signal.score += config.SCORE_CLUSTER_2
        signal.score_breakdown.append(f"• Cluster 2 insider +{config.SCORE_CLUSTER_2}")

    # Cluster total bonus
    total = sum(t.value for t in transactions)
    if total >= config.CLUSTER_TOTAL_THRESHOLD:
        signal.score += config.SCORE_CLUSTER_TOTAL
        signal.score_breakdown.append(
            f"• Totale cluster ${total:,.0f} (≥$500K) +{config.SCORE_CLUSTER_TOTAL}"
        )

    return signal


def score_all(transactions: List[InsiderTransaction]) -> List[TickerSignal]:
    """Group transactions by ticker, score each group, return sorted descending."""
    groups: dict = defaultdict(list)
    for t in transactions:
        groups[t.ticker].append(t)

    signals = [score_ticker(ticker, txs) for ticker, txs in groups.items()]
    return sorted(signals, key=lambda s: s.score, reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```bat
pytest tests/test_scorer.py -v
```

Expected: All 14 tests PASSED.

- [ ] **Step 5: Commit**

```bat
git add scorer.py tests/test_scorer.py
git commit -m "feat: add scoring algorithm with role/value/cluster bonuses"
```

---

### Task 5: notifier.py — Telegram Formatting and Sending

**Files:**
- Create: `notifier.py`
- Create: `tests/test_notifier.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_notifier.py`:

```python
from datetime import date
from unittest.mock import patch, MagicMock
import requests as req
from scraper import InsiderTransaction
from scorer import TickerSignal
from notifier import _format_message, _no_signal_message, send_signal, send_error


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bat
pytest tests/test_notifier.py -v
```

Expected: `ModuleNotFoundError: No module named 'notifier'`

- [ ] **Step 3: Create notifier.py**

```python
import logging
from datetime import date
from typing import Optional

import requests

from scorer import TickerSignal

logger = logging.getLogger(__name__)


def _format_message(signal: TickerSignal) -> str:
    today = date.today().strftime("%d/%m/%Y")
    lines = [f"🔍 INSIDER TRACKER — {today}", ""]
    lines.append(f"📌 ${signal.ticker} — {signal.company}")
    for tx in signal.transactions:
        lines.append(f"👤 {tx.insider_name} ({tx.title}) → ${tx.value:,.0f}")
    lines.append("")
    lines.append(f"📊 Score: {signal.score} pt")
    lines.extend(signal.score_breakdown)
    lines.append("")
    lines.append(f"🔗 openinsider.com/{signal.ticker}")
    return "\n".join(lines)


def _no_signal_message() -> str:
    today = date.today().strftime("%d/%m/%Y")
    return f"🔍 INSIDER TRACKER — {today}\n😴 Nessun segnale insider oggi."


def _error_message(error: str) -> str:
    return f"⚠️ INSIDER TRACKER — Errore scraping OpenInsider:\n{error}"


def _send_telegram(text: str, token: str, chat_id: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("Telegram send failed: %s", e)
        return False


def send_signal(signal: Optional[TickerSignal], token: str, chat_id: str) -> bool:
    text = _format_message(signal) if signal is not None else _no_signal_message()
    return _send_telegram(text, token, chat_id)


def send_error(error: str, token: str, chat_id: str) -> bool:
    return _send_telegram(_error_message(error), token, chat_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```bat
pytest tests/test_notifier.py -v
```

Expected: All 10 tests PASSED.

- [ ] **Step 5: Commit**

```bat
git add notifier.py tests/test_notifier.py
git commit -m "feat: add Telegram notifier with message formatting"
```

---

### Task 6: insider_tracker.py — Orchestration

**Files:**
- Create: `insider_tracker.py`
- Create: `tests/test_tracker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_tracker.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bat
pytest tests/test_tracker.py -v
```

Expected: `ModuleNotFoundError: No module named 'insider_tracker'`

- [ ] **Step 3: Create insider_tracker.py**

```python
import json
import logging
import os
import time
from datetime import date
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv

import config
from scraper import fetch_transactions, deduplicate
from scorer import score_all, TickerSignal
from notifier import send_signal, send_error

load_dotenv()

logging.basicConfig(
    filename="errors.log",
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

LAST_SEEN_FILE = Path("last_seen.json")


def load_last_seen() -> dict:
    if LAST_SEEN_FILE.exists():
        return json.loads(LAST_SEEN_FILE.read_text(encoding="utf-8"))
    return {}


def save_last_seen(last_seen: dict) -> None:
    LAST_SEEN_FILE.write_text(json.dumps(last_seen, indent=2), encoding="utf-8")


def already_sent_today(ticker: str, last_seen: dict) -> bool:
    return last_seen.get(ticker) == str(date.today())


def mark_sent(ticker: str, last_seen: dict) -> None:
    last_seen[ticker] = str(date.today())


def pick_top_signal(
    signals: List[TickerSignal], last_seen: dict
) -> Optional[TickerSignal]:
    for signal in signals:
        if signal.score >= config.MIN_SCORE and not already_sent_today(signal.ticker, last_seen):
            return signal
    return None


def _fetch_all() -> list:
    all_transactions = []
    for url in config.OPENINSIDER_URLS:
        for attempt in range(3):
            try:
                txs = fetch_transactions(
                    url, config.MIN_TRANSACTION_VALUE, config.LOOKBACK_CALENDAR_DAYS
                )
                all_transactions.extend(txs)
                break
            except requests.RequestException as exc:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
    return deduplicate(all_transactions)


def main() -> None:
    token = os.environ["TELEGRAM_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    last_seen = load_last_seen()

    try:
        transactions = _fetch_all()
        signals = score_all(transactions)
        top = pick_top_signal(signals, last_seen)
        sent = send_signal(top, token, chat_id)
        if sent and top is not None:
            mark_sent(top.ticker, last_seen)
            save_last_seen(last_seen)
    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        send_error(str(exc), token, chat_id)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

```bat
pytest tests/ -v
```

Expected: All 39 tests PASSED, no warnings.

- [ ] **Step 5: Commit**

```bat
git add insider_tracker.py tests/test_tracker.py
git commit -m "feat: add orchestration logic with last_seen guard"
```

---

### Task 7: Launcher + Task Scheduler

**Files:**
- Create: `run_insider.bat`

- [ ] **Step 1: Create run_insider.bat**

```bat
@echo off
cd /d "C:\Users\corr8\Desktop\InsiderTracker"
call venv\Scripts\activate
python insider_tracker.py
```

- [ ] **Step 2: Test manual launch**

Double-click `run_insider.bat` or run from terminal:

```bat
C:\Users\corr8\Desktop\InsiderTracker\run_insider.bat
```

Expected: Script completes within ~30 seconds. A Telegram message arrives with either a signal or "Nessun segnale insider oggi."

- [ ] **Step 3: Configure Windows Task Scheduler**

1. Open Task Scheduler: `Win+R` → `taskschd.msc`
2. Click **Create Basic Task...**
3. **Name:** `InsiderTracker Daily`
4. **Trigger:** Daily — start at **08:00:00** — tick **"Synchronize across time zones"** and set timezone to **Europe/Rome**
5. **Action:** Start a program
   - **Program/script:** `C:\Users\corr8\Desktop\InsiderTracker\run_insider.bat`
   - **Start in:** `C:\Users\corr8\Desktop\InsiderTracker`
6. Click **Finish**, then open **Properties** of the task:
   - **General tab:** check "Run whether user is logged on or not"
   - **Settings tab:** uncheck "Stop task if it runs longer than 3 days"
7. Click **OK**, enter Windows password if prompted.

- [ ] **Step 4: Verify task appears in Task Scheduler library**

In Task Scheduler, find `InsiderTracker Daily` in the library. Right-click → **Run** to test it fires correctly.

- [ ] **Step 5: Commit**

```bat
git add run_insider.bat
git commit -m "chore: add Windows launcher and Task Scheduler setup"
```

---

### Task 8: End-to-End Verification

- [ ] **Step 1: Run full test suite**

```bat
pytest tests/ -v
```

Expected: All 39 tests PASSED.

- [ ] **Step 2: Run script manually**

```bat
python insider_tracker.py
```

Expected: Telegram message received within 30 seconds.

- [ ] **Step 3: Verify last_seen.json created**

```bat
type last_seen.json
```

Expected: JSON with today's date for the ticker sent (or `{}` if no signal).

- [ ] **Step 4: Final commit**

```bat
git add -A
git commit -m "chore: insider tracker v1 complete"
```
