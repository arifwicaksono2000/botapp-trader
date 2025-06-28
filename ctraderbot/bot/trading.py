# file: ctraderbot/bot/trading.py

from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from ..helpers import *
from twisted.internet.threads import deferToThread
from ..database import SessionSync
from .event_handlers import on_message
from ctrader_open_api import Protobuf
from datetime import datetime, timedelta, timezone

def _on_balance_fetched(balance, bot):
    """
    Callback executed after the account balance is fetched from the database.
    It sets the balance on the bot instance and then proceeds with the main logic.
    """
    print(f"[Info] Fetched current account balance: {balance}")
    bot.current_balance = balance  # Set the attribute here

    # Now that the bot object has the balance, we can run the segment/trade logic
    d = deferToThread(_get_or_create_segment_and_trade, bot)
    d.addCallback(lambda _: _reconcile_positions(bot))
    d.addErrback(lambda failure: print(f"[DB ERROR] Segment management failed: {failure}"))

def _reconcile_positions(bot_instance):
    """
    Orchestrates the entire reconciliation process.
    1. Fetches server state (all open positions).
    2. Fetches DB state (all 'running' TradeDetails).
    3. Compares the two and issues commands to align the server state
       with the state intended by the database.
    """
    print("[Reconcile] Starting full state reconciliation...")

    # Create a Deferred to handle the asynchronous response from the server
    d = Deferred()
    d.addCallback(_on_reconcile_response, bot=bot_instance)
    d.addErrback(lambda failure: print(f"[ERROR] Reconcile request failed: {failure}"))

    # Temporarily override the message handler to catch the specific response
    def custom_message_handler(_, msg):
        if msg.payloadType == ProtoOAReconcileRes().payloadType:
            d.callback(Protobuf.extract(msg))
            # IMPORTANT: Restore the original message handler after we're done.
            bot_instance.client.setMessageReceivedCallback(lambda _, m: on_message(bot_instance, m))

    bot_instance.client.setMessageReceivedCallback(custom_message_handler)
    bot_instance.client.send(ProtoOAReconcileReq(ctidTraderAccountId=bot_instance.account_id))

def _on_reconcile_response(reconcile_res, bot):
    """
    Callback executed after receiving the server's state.
    Contains the core logic for comparing DB state vs. Server state.
    """
    # 1. Get the state from the cTrader Server
    server_positions = {pos.positionId: pos for pos in reconcile_res.position}
    server_position_ids = server_positions.keys()
    print(f"[Reconcile] Server State: Found {len(server_positions)} open position(s).")

    with SessionSync() as s:
        # 2. Get the state from our local Database
        db_running_details = s.query(TradeDetail).filter(TradeDetail.status == 'running').all()
        db_position_ids = {detail.position_id for detail in db_running_details}
        print(f"[Reconcile] Database State: Found {len(db_position_ids)} 'running' position(s).")

        # 3. ACTION: Close "zombie" positions (exist on server, not in DB)
        positions_to_close = server_position_ids - db_position_ids
        if positions_to_close:
            print(f"[Action] Found {len(positions_to_close)} zombie position(s) to close.")
            for pos_id in positions_to_close:
                # We need the full position object to get the volume for closing.
                position_obj = server_positions[pos_id]
                close_position(bot, pos_id, position_obj.tradeData.volume)
        else:
            print("[Reconcile] No zombie positions found on server.")

        # 4. ACTION: Open positions for new trades (exist in DB, not on server)
        running_trades = s.query(Trades).filter(Trades.status == 'running').all()
        print(f"[Reconcile] Checking status of {len(running_trades)} running trade(s) in DB.")

        for trade in running_trades:
            details_for_this_trade = s.query(TradeDetail).filter_by(trade_id=trade.id, status='running').all()
            
            has_long = any(d.position_type == 'long' and d.position_id in server_position_ids for d in details_for_this_trade)
            has_short = any(d.position_type == 'short' and d.position_id in server_position_ids for d in details_for_this_trade)

            # --- THIS IS THE NEW, CORRECTED LOGIC ---
            # Case 1: The trade is healthy (both positions are open).
            if has_long and has_short:
                print(f"--- Trade {trade.id} is healthy. Checking hold time... ---")
                # We can check the age of the first detail to determine the trade's age.
                first_detail = details_for_this_trade[0]
                opened_at_aware = first_detail.opened_at.replace(tzinfo=timezone.utc)
                time_since_open = datetime.now(timezone.utc) - opened_at_aware
                
                if time_since_open.total_seconds() >= bot.hold:
                    print(f"[Action] Trade {trade.id} has exceeded hold time ({bot.hold}s). Closing positions.")
                    for detail in details_for_this_trade:
                        position_obj = server_positions.get(detail.position_id)
                        if position_obj:
                            close_position(bot, detail.position_id, position_obj.tradeData.volume)
                else:
                    print(f"--- Trade {trade.id} is within hold time. No action taken. ---")
            
            # Case 2: The trade is missing one or both positions.
            else:
                print(f"--- Trade {trade.id} is missing positions (Long: {has_long}, Short: {has_short}). Taking action. ---")
                milestone = s.query(Milestone).get(trade.current_level_id)
                if not milestone:
                    print(f"[ERROR] Cannot find milestone for Trade {trade.id}. Skipping.")
                    continue
                lot_size = int(float(milestone.lot_size) * 100 * 100000)

                # Open only the missing LONG position
                if not has_long:
                    print(f"[Action] Opening missing LONG position for Trade {trade.id}")
                    bot.client.send(ProtoOANewOrderReq(
                        ctidTraderAccountId=bot.account_id, symbolId=bot.symbol_id, orderType=ProtoOAOrderType.MARKET,
                        tradeSide=ProtoOATradeSide.Value("BUY"), volume=lot_size, clientOrderId=f"trade_{trade.id}_long_open"
                        # tradeSide=ProtoOATradeSide.Value("BUY"), volume=lot_size, clientOrderId=f"trade_{trade.id}_long_reopen"
                    ))
                # Open only the missing SHORT position
                if not has_short:
                    print(f"[Action] Opening missing SHORT position for Trade {trade.id}")
                    bot.client.send(ProtoOANewOrderReq(
                        ctidTraderAccountId=bot.account_id, symbolId=bot.symbol_id, orderType=ProtoOAOrderType.MARKET,
                        tradeSide=ProtoOATradeSide.Value("SELL"), volume=lot_size, clientOrderId=f"trade_{trade.id}_short_open"
                        # tradeSide=ProtoOATradeSide.Value("SELL"), volume=lot_size, clientOrderId=f"trade_{trade.id}_short_reopen"
                    ))

        # Mark stale details as closed if their position ID is not on the server
        for detail in db_running_details:
            if detail.position_id not in server_position_ids:
                print(f"[DB Cleanup] Marking stale TradeDetail for position {detail.position_id} as closed.")
                detail.status = 'closed'
        s.commit()

def send_market_order(bot):
    """
    This is the main entry point from the bot's auth flow.
    It now kicks off the process by first fetching the account balance.
    """
    print("[Info] Fetching account balance to begin trade logic...")
    # Start the chain by fetching the balance from the DB in a thread
    d = deferToThread(fetch_account_balance, bot.account_pk)
    # When the balance is returned, the _on_balance_fetched callback will be executed
    d.addCallback(_on_balance_fetched, bot)
    d.addErrback(lambda failure: print(f"[DB ERROR] Failed to fetch account balance: {failure}"))

def _get_or_create_segment_and_trade(bot_instance):
    """
    This function's job is to ensure the database reflects the intended state
    by creating new segments or trades if conditions are met.
    It no longer opens positions directly.
    """
    with SessionSync() as s:
        pivot_segment = fetch_running_pivot_segment(bot_instance.account_pk)
        if pivot_segment is None:
            # Create a new pivot segment and its first trade
            milestone = s.query(Milestone).where(
                Milestone.starting_balance <= bot_instance.current_balance,
                Milestone.ending_balance >= bot_instance.current_balance
            ).first()
            if not milestone: raise RuntimeError("No milestone found for current balance.")
            
            new_pivot = create_new_segment(
                subaccount_id=bot_instance.account_pk, 
                milestone_id=milestone.id,
                total_balance=bot_instance.current_balance, 
                pair="EURUSD", 
                is_pivot=True
            )
            create_trade(
                segment_id=new_pivot.id, 
                milestone_id=milestone.id,
                current_balance=bot_instance.current_balance
            )
        else:
            # --- 1. Check the Time Condition ---
        
            # Get the pivot segment's opening date (e.g., 2025-06-20 10:00:00)
            # pivot_open_date = pivot_segment.opened_at
            pivot_open_date_aware = pivot_segment.opened_at.replace(tzinfo=timezone.utc)
            
            # Calculate the target date: the day after it opened
            target_datetime_utc = (pivot_open_date_aware + timedelta(days=1)).replace(
                hour=17, minute=0, second=0, microsecond=0
            )
            
            # Get the current time in UTC
            # now_utc = datetime.now(timezone.utc)
            
            time_condition_met = datetime.now(timezone.utc) >= target_datetime_utc

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

                new_segment = create_new_segment(
                    subaccount_id=bot_instance.account_pk,
                    milestone_id=milestone.id,
                    total_balance=given_balance,
                    pair="EURUSD"  # Assuming default
                )

                # Create the new trade record
                new_trade = create_trade(
                    segment_id=new_segment.id,
                    milestone_id=milestone.id,
                    current_balance=given_balance
                )

                # Immediately open the positions for the new trade we just created.
                # We run this in a thread to avoid blocking the main loop.
                print(f"[Action] Triggering position opening for new Trade ID: {new_trade.id}")
                deferToThread(_open_positions_for_trade, new_trade, bot_instance)

    return True # Signal that the DB state is ready

def _open_positions_for_trade(trade: Trades, bot_instance):
    """
    A dedicated function to open the hedging positions for a single, specific trade.
    """
    if not trade:
        return

    with SessionSync() as s:
        milestone = s.query(Milestone).get(trade.current_level_id)
        if not milestone:
            print(f"[ERROR] Cannot find milestone for Trade {trade.id}. Skipping.")
            return
        
        lot_size = int(float(milestone.lot_size) * 100 * 100000)
        print(f"--- Opening positions for new Trade ID: {trade.id} with lot size {lot_size} ---")

        # Open LONG position
        bot_instance.client.send(ProtoOANewOrderReq(
            ctidTraderAccountId=bot_instance.account_id, symbolId=bot_instance.symbol_id,
            orderType=ProtoOAOrderType.MARKET, tradeSide=ProtoOATradeSide.Value("BUY"),
            volume=lot_size, clientOrderId=f"trade_{trade.id}_long"
        ))
        # Open SHORT position
        bot_instance.client.send(ProtoOANewOrderReq(
            ctidTraderAccountId=bot_instance.account_id, symbolId=bot_instance.symbol_id,
            orderType=ProtoOAOrderType.MARKET, tradeSide=ProtoOATradeSide.Value("SELL"),
            volume=lot_size, clientOrderId=f"trade_{trade.id}_short"
        ))

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
    request = ProtoOAGetPositionUnrealizedPnLReq(ctidTraderAccountId=bot.account_id)
    bot.client.send(request)

def reconcile(bot):
    bot.client.send(ProtoOAReconcileReq(ctidTraderAccountId=bot.account_id))