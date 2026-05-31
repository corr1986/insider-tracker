"""
Configuration constants for InsiderTracker.

Contains thresholds and scoring weights for insider trading analysis.
Data source: SEC EDGAR Form 4 filings (globally accessible, no geo-blocks).
"""

from pathlib import Path

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

# Company analyzer — historical backtest settings
COMPANY_HISTORY_LOOKBACK_DAYS = 730   # 2 years of company history
SL_PERCENT = 0.08                      # fixed 8% stop-loss

# Display settings for company analyzer UI
COMPANY_DISPLAY_LOOKBACK_DAYS = 365   # 12 months shown in purchase list
MAX_DISPLAY_PURCHASES = 5             # max rows in the individual purchase list

# Portfolio simulator settings
PORTFOLIO_MIN_SCORE = 8
PORTFOLIO_CAPITAL = 20_000.0
PORTFOLIO_FILE = Path("portfolio_insider.json")
PORTFOLIO_MD = Path(r"C:\Users\corr8\Desktop\obsidian-vault\Insider Project\Portfolio Simulato.md")
