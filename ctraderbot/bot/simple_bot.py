# simple_bot.py
from ctrader_open_api import Client
from .trading import request_unrealized_pnl
from .event_handlers import register_callbacks
from twisted.internet import reactor

class SimpleBot:
    def __init__(self, client: Client, access_token, account_id, symbol_id, hold):
        self.client = client
        self.access_token = access_token
        self.account_id = account_id
        self.symbol_id = symbol_id
        # self.trade_side = side.upper()
        # self.volume = volume * 100
        self.hold = hold
        self.open_position_id = None
        self.positions: dict[int, dict] = {}
        self.latest_price: float = 0.0  # latest bid/ask midpoint
        
        register_callbacks(self)

    def start(self):
        self.client.startService()
        reactor.run()
    
    def schedule_pnl_updates(self):
        """Schedules the bot to request PnL updates every 1 seconds."""
        request_unrealized_pnl(self)
        reactor.callLater(1, self.schedule_pnl_updates)
