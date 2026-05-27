"""
Scoring module for InsiderTracker.

Computes a signal score for each ticker based on insider role, transaction
value, and cluster buy behaviour. Higher scores indicate stronger insider
conviction signals.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple

import config
from scraper import InsiderTransaction


@dataclass
class TickerSignal:
    """Aggregated scoring result for a single ticker."""

    ticker: str
    company: str
    transactions: List[InsiderTransaction]
    score: int = 0
    score_breakdown: List[str] = field(default_factory=list)


def _role_score(title: str) -> Tuple[int, str]:
    """Return (points, label) for an insider's title.

    Matches CEO and CFO both by abbreviation and full title (case-insensitive).
    All other roles receive the default officer score.
    """
    t = title.upper()
    if "CEO" in t or "CHIEF EXECUTIVE" in t:
        return config.SCORE_CEO, f"CEO buy +{config.SCORE_CEO}"
    if "CFO" in t or "CHIEF FINANCIAL" in t:
        return config.SCORE_CFO, f"CFO buy +{config.SCORE_CFO}"
    return config.SCORE_OTHER, f"Officer buy +{config.SCORE_OTHER}"


def _value_score(value: float) -> Tuple[int, str]:
    """Return (points, label) based on transaction dollar value.

    Thresholds (inclusive lower bound):
    - >= $500K  → SCORE_VALUE_LARGE
    - >= $100K  → SCORE_VALUE_MED
    - < $100K   → SCORE_VALUE_SMALL
    """
    if value >= 500_000:
        return config.SCORE_VALUE_LARGE, f"Importo ${value:,.0f} (≥$500K) +{config.SCORE_VALUE_LARGE}"
    if value >= 100_000:
        return config.SCORE_VALUE_MED, f"Importo ${value:,.0f} (≥$100K) +{config.SCORE_VALUE_MED}"
    return config.SCORE_VALUE_SMALL, f"Importo ${value:,.0f} (<$100K) +{config.SCORE_VALUE_SMALL}"


def score_ticker(ticker: str, transactions: List[InsiderTransaction]) -> TickerSignal:
    """Compute a TickerSignal by scoring all transactions for a single ticker.

    Scoring components applied in order:
    1. Role points for each transaction (CEO > CFO > other).
    2. Value points based on the highest single transaction value.
    3. Cluster bonus based on the number of distinct insiders.
    4. Cluster total bonus when aggregate value >= CLUSTER_TOTAL_THRESHOLD.
    """
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
    n = len({tx.insider_name for tx in transactions})
    if n >= 3:
        signal.score += config.SCORE_CLUSTER_3PLUS
        signal.score_breakdown.append(f"• Cluster {n} insider +{config.SCORE_CLUSTER_3PLUS}")
    elif n == 2:
        signal.score += config.SCORE_CLUSTER_2
        signal.score_breakdown.append(f"• Cluster 2 insider +{config.SCORE_CLUSTER_2}")

    # Cluster total bonus: aggregate value across all transactions
    total = sum(t.value for t in transactions)
    if total >= config.CLUSTER_TOTAL_THRESHOLD:
        signal.score += config.SCORE_CLUSTER_TOTAL
        signal.score_breakdown.append(
            f"• Totale cluster ${total:,.0f} (≥$500K) +{config.SCORE_CLUSTER_TOTAL}"
        )

    return signal


def score_all(transactions: List[InsiderTransaction]) -> List[TickerSignal]:
    """Group transactions by ticker, score each group, return sorted descending by score."""
    groups: dict = defaultdict(list)
    for t in transactions:
        groups[t.ticker].append(t)

    signals = [score_ticker(ticker, txs) for ticker, txs in groups.items()]
    return sorted(signals, key=lambda s: s.score, reverse=True)
