"""
Configuration constants for InsiderTracker.

Contains URLs, thresholds, and scoring weights for insider trading analysis.
"""

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
