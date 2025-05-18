# -----------------------------------------------------------------------------
# Project layout
# -----------------------------------------------------------------------------
#   ctrader_bot/                ← package root (add this to PYTHONPATH or install with pip -e .)
#   ├── __init__.py             ← makes this directory an importable module
#   ├── settings.py             ← all environment‑dependent config in one place
#   ├── bridge.py               ← Twisted ↔︎ asyncio reactor bridging
#   ├── database.py             ← SQLAlchemy async engine + Session factory
#   ├── models.py               ← ORM models (TokenDB, DealLog, …)
#   ├── helpers.py              ← DB helper functions (fetch_access_token, insert_deal)
#   ├── bot.py                  ← SimpleBot implementation
#   └── cli.py                  ← command‑line entry‑point (replaces monolithic main.py)
# -----------------------------------------------------------------------------
# Each file is fully self‑contained; import cycles are avoided by keeping helpers
# and settings in dedicated modules.
# -----------------------------------------------------------------------------

your-project/
├── .env                     👈 Here
├── ctrader_bot/
│   ├── __init__.py
│   ├── settings.py
│   ├── bridge.py
│   ├── database.py
│   ├── models.py
│   ├── helpers.py
│   ├── bot.py
│   └── cli.py
├── pyproject.toml           (optional, for pip install -e .)
└── README.md