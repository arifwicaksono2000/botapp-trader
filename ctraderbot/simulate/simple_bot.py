# simple_bot.py
from ctrader_open_api import Client
from ctraderbot.bot.event_handlers import register_callbacks
from ctraderbot.bot.event_handlers import on_message  # where you defined it

class SimpleBot:
    def __init__(self, client: Client, access_token, account_id, symbol_id, volume, hold):
        self.client = client
        self.access_token = access_token
        self.account_id = account_id
        self.symbol_id = symbol_id
        # self.trade_side = side.upper()
        self.volume = volume * 100
        # self.volume = volume * 100
        self.hold = hold
        self.open_position_id = None
        self.positions: dict[int, dict] = {}
        self.latest_price: float = 0.0  # latest bid/ask midpoint
        
        register_callbacks(self)

    def start(self):
        self.client.startService()
        from twisted.internet import reactor
        reactor.run()

    def simulate_trade_cycle(self):
        # 1) Pretend “connected” and get AppAuthRes
        fake_app = make_fake_auth_res(is_account=False)
        on_message(self, fake_app)

        # 2) Pretend “account authorized”
        fake_acc = make_fake_auth_res(is_account=True, trader_account_id=self.account_id)
        on_message(self, fake_acc)

        # 3) Bot.send_market_order() will run inside after_account_auth, but
        #    since market is “closed,” we never get a real ExecutionEvent. So:
        fake_buy_fill = make_fake_execution_event(
            trader_account_id=self.account_id,
            position_id=222222,
            volume=self.volume,
            price=1.30000,
            side_str="BUY"
        )
        on_message(self, fake_buy_fill)

        # 4) Simulate “server has closed that position 60s later”:
        fake_sell_fill = make_fake_execution_event(
            trader_account_id=self.account_id,
            position_id=222222,
            volume=self.volume,
            price=1.30500,
            side_str="SELL"
        )
        on_message(self, fake_sell_fill)
    
    # def print_positions(self):
    #     print("[POSITIONS]")
    #     for pos_id, data in self.positions.items():
    #         print(f" - ID {pos_id}: Sym={data['symbolId']}, Vol={data['volume']}, "
    #             f"PnL={data['unrealisedNetProfit']:.2f}, Margin={data['usedMargin']}")
