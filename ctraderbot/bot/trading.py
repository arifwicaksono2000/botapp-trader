# trading.py
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
from twisted.internet import reactor
from ..helpers import *
from twisted.internet.threads import deferToThread
from datetime import datetime, timedelta, timezone

def _get_or_create_segment_and_trade(bot_instance):
    """
    Checks for an existing segment; if none exists, creates one.
    Then, creates a new trade record associated with the segment.
    This function is intended to be run in a thread.
    """
    # 1. Check for existing running pivot segment
    pivot_segment = fetch_running_pivot_segment(bot_instance.account_id)

    # 2. If not, create a new segment
    if pivot_segment is None:
        print("No existing segment pivot found. Creating a new one.")

        with SessionSync() as s:
            milestone = s.query(Milestone).where(
                Milestone.starting_balance <= bot_instance.current_balance,
                Milestone.ending_balance >= bot_instance.current_balance
            ).first()

        pivot_segment = create_new_segment(
            subaccount_id=bot_instance.account_pk,
            milestone_id=milestone.id,
            total_balance=bot_instance.current_balance,
            pair="EURUSD",  # Assuming default
            is_pivot=True
        )

        # 3. Create the trade row
        create_trade(
            segment_id=pivot_segment.id,
            milestone_id=milestone.id,
            current_balance=bot_instance.current_balance
        )
        
    else:
        # --- 1. Check the Time Condition ---
    
        # Get the pivot segment's opening date (e.g., 2025-06-20 10:00:00)
        pivot_open_date = pivot_segment.opened_at
        
        # Calculate the target date: the day after it opened
        target_date = pivot_open_date + timedelta(days=1)
        
        # Set the target time to 17:00 UTC on that target date
        # This creates the full timestamp for comparison (e.g., 2025-06-21 17:00:00)
        target_datetime_utc = target_date.replace(hour=17, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        
        # Get the current time in UTC
        now_utc = datetime.now(timezone.utc)
        
        time_condition_met = now_utc >= target_datetime_utc

        # --- 2. Check the Balance Condition ---
        
        with SessionSync() as s:
            initial_level = s.query(Constant).where(
                Constant.variable == 'initial_level',
                Constant.is_active == True,
            ).first()

            # Find the milestone that corresponds to the current balance
            milestone = s.query(Milestone).where(
                Milestone.id == initial_level.value
            ).first()
                
            milestone_balance = float(milestone.starting_balance)
            
            balance_condition_met = pivot_segment.total_balance >= (2 * milestone_balance)
        
        if time_condition_met and balance_condition_met:
            print("Extending Segments. Creating a new one.")
            given_balance = pivot_segment.total_balance - milestone_balance
            pivot_segment = create_new_segment(
                subaccount_id=bot_instance.account_pk,
                milestone_id=milestone.id,
                total_balance=given_balance,
                pair="EURUSD"  # Assuming default
            )

            # 3. Create the trade row
            create_trade(
                segment_id=pivot_segment.id,
                milestone_id=milestone.id,
                current_balance=given_balance
            )
    
    with SessionSync() as s:
        running_segments = s.query(Segments).where(
                Segments.status == 'running'
            ).all()
        
    return running_segments, bot_instance

def _on_segment_trade_result(result):
    """
    Callback executed after segment and trade are created.
    Opens the two hedging positions.
    """
    running_segments, bot = result
    for segment in running_segments:
        with SessionSync() as s:
            get_trade = s.query(Trades).where(
                Trades.segment_id == segment.id,
                Trades.status == 'running',
            ).order_by(desc(Trades.opened_at)).first()

            get_milestone = s.query(Milestone).where(
                Milestone.id == get_trade.current_level_id
            ).first()
        
        lot_size = int(get_milestone.lot_size * 100 * 100000)
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
            
# --- Main functions called by the bot ---

def send_market_order(bot):
    """
    Fetches milestone, then kicks off the chain of callbacks to create
    database records and send the hedging market orders.
    """
    d = deferToThread(_get_or_create_segment_and_trade, bot)
    # Pass the 'bot' instance to the callback using an additional argument
    d.addCallback(_on_segment_trade_result)
    d.addErrback(lambda failure: print(f"[DB error] Segment management failed: {failure}"))


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
