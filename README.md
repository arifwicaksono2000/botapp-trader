# cTrader Bot Toolkit

This repository provides a small toolkit for building automated trading bots
that interact with the cTrader Open API. The code uses Python's asyncio in
combination with Twisted, stores token and account information in MySQL via
SQLAlchemy and broadcasts position updates over a FastAPI websocket service.

## Directory layout

```
ctraderbot/
├── __init__.py           # package marker
├── settings.py           # environment variables loaded from .env
├── bridge.py             # Twisted ↔ asyncio reactor bridge
├── database.py           # SQLAlchemy async engine & session factory
├── models.py             # ORM models (TokenDB, Subaccount, ...)
├── helpers.py            # DB helpers (fetch_access_token, fetch_main_account)
├── bot/
│   ├── auth.py
│   ├── event_handlers.py
│   ├── execution.py
│   ├── simple_bot.py
│   ├── spot_event.py
│   └── trading.py
├── websocket/
│   └── server.py         # FastAPI websocket endpoint
└── cli.py                # command line entry point
```

Additional helper scripts live in `setup/` for obtaining and refreshing OAuth
tokens. Older monolithic examples are kept in `main.py` and `manual_main.py`.

## Getting started

1. Create and activate a virtual environment.
2. Install requirements with `pip install -r requirements.txt`.
3. Provide API credentials and database settings in a `.env` file.
4. Use the scripts in `setup/` to fetch and refresh cTrader tokens.
5. Start the websocket service:
   ```
   uvicorn ctraderbot.websocket.server:app --host 0.0.0.0 --port 9000 --reload
   ```
6. Launch the bot:
   ```
   python -m ctraderbot.cli --volume 1000 --hold 60
   ```

## Simulation

Offline testing utilities live under `ctraderbot/simulate`. A quick example:

```bash
python -c "from ctraderbot.simulate.simple_bot import SimpleBot; \
bot = SimpleBot(client_id='X', client_secret='Y', symbol_id=1, account_id='Z', volume=100000); \
bot.simulate_trade_cycle()"
```

## Learning more

- Familiarise yourself with async programming and Twisted.
- Review SQLAlchemy's async session usage in `database.py` and `helpers.py`.
- Explore the cTrader Open API message formats for customizing trading logic.
