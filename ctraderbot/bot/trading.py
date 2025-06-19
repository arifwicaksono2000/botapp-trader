# trading.py
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
from twisted.internet import reactor
from ..helpers import *
from twisted.internet.threads import deferToThread

def _get_or_create_segment_and_trade(bot_instance):
    """
    Checks for an existing segment; if none exists, creates one.
    Then, creates a new trade record associated with the segment.
    This function is intended to be run in a thread.
    """
    # 1. Check for existing segment
    latest_segment = fetch_latest_segment(bot_instance.account_id)

    # 2. If not, create a new segment
    if latest_segment is None:
        print("No existing segment found. Creating a new one.")
        latest_segment = create_new_segment(
            subaccount_id=bot_instance.account_pk,
            milestone_id=bot_instance.milestone.id,
            total_balance=bot_instance.current_balance,
            pair="EURUSD"  # Assuming default
        )

    # 3. Create the trade row
    trade = create_trade(
        segment_id=latest_segment.id,
        milestone_id=bot_instance.milestone.id,
        current_balance=bot_instance.current_balance
    )
    return latest_segment, trade, bot_instance

def _on_segment_trade_result(result):
    """
    Callback executed after segment and trade are created.
    Opens the two hedging positions.
    """
    segment, trade, bot = result
    bot.current_segment_id = segment.id
    bot.current_trade_id = trade.id
    print(f"Operating with Segment ID: {bot.current_segment_id} and Trade ID: {bot.current_trade_id}")

    lot_size = int(bot.milestone.lot_size * 100 * 100000)
    print(f"[LOT SIZE] Calculated volume: {lot_size}")

    # Open a LONG (BUY) position
    req_long = ProtoOANewOrderReq(
        ctidTraderAccountId=bot.account_id,
        symbolId=bot.symbol_id,
        orderType=ProtoOAOrderType.MARKET,
        tradeSide=ProtoOATradeSide.Value("BUY"),
        volume=lot_size,
        clientOrderId="OPEN_LONG_1"
    )
    bot.client.send(req_long)

    # Open a SHORT (SELL) position
    req_short = ProtoOANewOrderReq(
        ctidTraderAccountId=bot.account_id,
        symbolId=bot.symbol_id,
        orderType=ProtoOAOrderType.MARKET,
        tradeSide=ProtoOATradeSide.Value("SELL"),
        volume=lot_size,
        clientOrderId="OPEN_SHORT_2"
    )
    bot.client.send(req_short)

def _on_milestone_result(result, bot):
    """
    Callback executed after the milestone is fetched.
    It initiates the process to get/create the segment and trade.
    """
    balance, milestone = result
    if not milestone:
        print(f"[ERROR] No matching milestone row for balance {balance}. Halting.")
        reactor.stop()
        return

    bot.current_balance = balance
    bot.milestone = milestone
    print(f"[MILESTONE] ID: {milestone.id}, Lot Size: {milestone.lot_size}")

    # Defer the segment/trade creation logic to a thread
    d_segment = deferToThread(_get_or_create_segment_and_trade, bot)
    d_segment.addCallback(_on_segment_trade_result)
    d_segment.addErrback(lambda failure: print(f"[DB error] Segment/Trade creation failed: {failure}"))

# --- Main functions called by the bot ---

def send_market_order(bot):
    """
    Fetches milestone, then kicks off the chain of callbacks to create
    database records and send the hedging market orders.
    """
    d = deferToThread(fetch_milestone, bot.account_id)
    # Pass the 'bot' instance to the callback using an additional argument
    d.addCallback(_on_milestone_result, bot)
    d.addErrback(lambda failure: print(f"[DB error] Milestone fetch failed: {failure}"))


def close_position(bot, position_id, volume_to_close):
    if position_id is None:
        print("[!] No open position to close.")
        return

    print(f"[→] Scheduled close for position {position_id} with volume {volume_to_close}")
    req = ProtoOAClosePositionReq(
        ctidTraderAccountId=bot.account_id,
        positionId=position_id,
        volume=volume_to_close,
        # mode=ProtoOAClosePositionMode.MARKET  # or whatever mode you prefer
    )
    d = bot.client.send(req)
    d.addErrback(lambda f: print("[✖] Close failed:", f))

def request_unrealized_pnl(bot):
    """Sends a request to get the unrealized PnL for all open positions."""
    request = ProtoOAGetPositionUnrealizedPnLReq(ctidTraderAccountId=bot.account_id)
    bot.client.send(request)

def reconcile(bot):
    bot.client.send(ProtoOAReconcileReq(ctidTraderAccountId=bot.account_id))
