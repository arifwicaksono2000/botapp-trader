# simple_bot.py
from ctrader_open_api import Client
from .event_handlers import register_callbacks

class SimpleBot:
    def __init__(self, client: Client, access_token, account_id, symbol_id, side, volume, hold):
        self.client = client
        self.access_token = access_token
        self.account_id = account_id
        self.symbol_id = symbol_id
        self.trade_side = side.upper()
        self.volume = volume * 100
        self.hold = hold
        self.open_position_id = None
        
        register_callbacks(self)

    def start(self):
        self.client.startService()
        from twisted.internet import reactor
        reactor.run()
