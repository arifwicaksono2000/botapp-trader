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
from decimal import Decimal

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

def _on_balance_fetched(balance, bot):
    """
    Callback executed after the account balance is fetched from the database.
    It sets the balance on the bot instance and then proceeds with the main logic.
    """
    print(f"[Info] Fetched current account balance: {balance}")
    bot.current_balance = balance  # Set the attribute here

    # --- START: This is the corrected startup logic ---

    # First, check the segment/trade state and create if necessary.
    # The function now returns the trade that should be active.
    active_trade = _get_or_create_segment_and_trade(bot)

    # If a new trade was just created, open its positions.
    # Otherwise, reconcile the state of existing trades.
    if active_trade and not bot.trade_couple.get(active_trade.id):
         print(f"[STARTUP] A new trade (ID: {active_trade.id}) was created. Opening initial positions.")
         deferToThread(_open_positions_for_trade, active_trade, bot)
    else:
        print("[STARTUP] Existing trades found. Proceeding with full reconciliation.")
        _reconcile_positions(bot)
    # --- END: Corrected startup logic ---

def _get_or_create_segment_and_trade(bot_instance):
    """
    This function's job is to ensure the database reflects the intended state
    by creating new segments or trades if conditions are met.
    It no longer opens positions directly.
    """
    pivot_segment = fetch_running_pivot_segment(bot_instance.account_pk)
    if pivot_segment is None:
        with SessionSync() as s:
            constant = s.query(Constant).where(
                Constant.variable == 'initial_level',
                Constant.is_active == True
            ).first()

            # Create a new pivot segment and its first trade
            milestone = s.query(Milestone).where(
                Milestone.id == int(constant.value)
            ).first()
        
        if not milestone: raise RuntimeError("No milestone found for current balance.")
        
        new_pivot = create_new_segment(
            subaccount_id=bot_instance.account_pk, 
            milestone_id=milestone.id,
            total_balance=milestone.starting_balance, 
            pair="EURUSD", 
            is_pivot=True
        )

        new_trade = create_trade(
            segment_id=new_pivot.id, 
            milestone_id=milestone.id,
            current_balance=milestone.starting_balance
        )

        return new_trade
    else:
        # --- 1. Check the Time Condition ---
        print(f"Detected Pivot Segment ID: {pivot_segment.uuid}")

        ### Every 19:00, we check if the segment should be extended.
        # pivot_open_date_aware = pivot_segment.opened_at.replace(tzinfo=timezone.utc)
        # target_datetime_utc = (pivot_open_date_aware + timedelta(days=1)).replace(
        #     hour=17, minute=0, second=0, microsecond=0
        # )   
        # time_condition_met = datetime.now(timezone.utc) >= target_datetime_utc

        ### Every 2 minutes, we check if the segment should be extended.
        # pivot_open_date_aware = pivot_segment.opened_at.replace(tzinfo=timezone.utc)
        # time_since_open = datetime.now(timezone.utc) - pivot_open_date_aware
        # time_condition_met = time_since_open.total_seconds() >= 120

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
        
        if balance_condition_met:
            print("Extending Segments. Creating a new one.")
            given_balance = pivot_segment.total_balance - Decimal(str(milestone_balance))
            curr_pivot_balance = Decimal(str(milestone_balance))

            # --- START: Add this block to update the database ---
            print(f"[DB UPDATE] Updating pivot segment {pivot_segment.id} balance to: {curr_pivot_balance}")
            pivot_segment.total_balance = curr_pivot_balance
            with SessionSync() as s:
                # Use merge() to update the existing detached object in the new session
                s.merge(pivot_segment)
                s.commit()
            # --- END: Block to update the database ---

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

            return new_trade # Return the new trade object

            # Immediately open the positions for the new trade we just created.
            # We run this in a thread to avoid blocking the main loop.
            # print(f"[Action] Triggering position opening for new Trade ID: {new_trade.id}")
            # deferToThread(_open_positions_for_trade, new_trade, bot_instance)

    return None # Signal that the DB state is ready

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
    Contains the core logic for comparing DB state vs. Server state
    based on the user's defined rules.
    """
    server_positions = {pos.positionId: pos for pos in reconcile_res.position}
    server_position_ids = set(server_positions.keys())
    print(f"[Reconcile] Server State: Found {len(server_positions)} open position(s). IDs: {server_position_ids}")

    with SessionSync() as s:
        running_trades = s.query(Trades).filter(Trades.status == 'running').all()
        print(f"[Reconcile] DB State: Found {len(running_trades)} 'running' trade(s).")

        # Get all position IDs from the DB that are supposed to be running
        db_details = s.query(TradeDetail).filter(TradeDetail.status == 'running').all()
        db_position_ids = {detail.position_id for detail in db_details}

        # --- Handle Zombie Positions (exist on server, not in our DB logic) ---
        zombie_ids = server_position_ids - db_position_ids
        if zombie_ids:
            print(f"[Action] Found {len(zombie_ids)} zombie position(s) to close: {zombie_ids}")
            for pos_id in zombie_ids:
                position_obj = server_positions[pos_id]
                close_position(bot, pos_id, position_obj.tradeData.volume)

        # --- Process each running trade from our database ---
        for trade in running_trades:
            details = s.query(TradeDetail).filter_by(trade_id=trade.id).all()
            
            # Determine the state for the current trade
            long_detail = next((d for d in details if d.position_type == 'long'), None)
            short_detail = next((d for d in details if d.position_type == 'short'), None)

            db_has_long = long_detail is not None
            db_has_short = short_detail is not None
            
            server_has_long = long_detail.position_id in server_position_ids if db_has_long else False
            server_has_short = short_detail.position_id in server_position_ids if db_has_short else False

            print(f"--- Checking Trade {trade.id}: DB(L:{db_has_long}, S:{db_has_short}) | Server(L:{server_has_long}, S:{server_has_short}) ---")

            # CASE 1: Healthy state. Everything exists.
            if db_has_long and db_has_short and server_has_long and server_has_short:
                print(f"[OK] Trade {trade.id} is healthy. Loading into memory.")
                # Load positions into memory so PnL updates work
                for detail in [long_detail, short_detail]:
                    pos = server_positions[detail.position_id]
                    segment = s.query(Segments).get(detail.segment_id)
                    bot.positions[pos.positionId] = {
                        "symbolId": pos.tradeData.symbolId, 
                        "volume": pos.tradeData.volume,
                        "entry_price": pos.price, 
                        "used_margin": pos.usedMargin, 
                        "swap": pos.swap,
                        "timestamp": datetime.now(timezone.utc).isoformat(), 
                        "status": "OPEN",
                        "tradeSide": pos.tradeData.tradeSide, 
                        "total_balance": segment.total_balance
                    }
                # Load trade couple into memory
                milestone = s.query(Milestone).get(trade.current_level_id)
                bot.trade_couple[trade.id] = {
                    "trade_id": trade.id, 
                    "ending_balance": milestone.ending_balance,
                    "resulted_balance": None,
                    "long_position_id": long_detail.position_id, 
                    "long_status": "running",
                    "short_position_id": short_detail.position_id, 
                    "short_status": "running"
                }
                continue # Move to the next trade

            # ALL OTHER CASES: Any mismatch requires a full reset for this trade.
            # This covers all the other scenarios you described.
            else:
                print(f"[MISMATCH] Trade {trade.id} is in a broken state. Resetting.")
                _reset_and_recreate_trade(bot, trade, server_positions, s)

def _reset_and_recreate_trade(bot, old_trade, server_positions, db_session):
    """
    Helper function to clean up a broken trade and start a new one.
    1. Closes any lingering server positions for the trade.
    2. Marks the old trade and its details as 'closed' in the DB.
    3. Creates a new trade record for the same segment.
    4. Opens new positions for the new trade.
    """
    print(f"--> Resetting Trade ID: {old_trade.id}")
    
    # 1. Close any lingering server positions
    old_details = db_session.query(TradeDetail).filter_by(trade_id=old_trade.id).all()
    for detail in old_details:
        if detail.position_id in server_positions:
            pos_to_close = server_positions[detail.position_id]
            print(f"--> Closing lingering server position: {pos_to_close.positionId}")
            close_position(bot, pos_to_close.positionId, pos_to_close.tradeData.volume)
        # Mark the detail as closed
        detail.status = 'closed'
        detail.closed_at = datetime.now(timezone.utc)

    # 2. Mark the parent trade as closed
    old_trade.status = 'closed'
    old_trade.closed_at = datetime.now(timezone.utc)
    
    # 3. Create a new trade for the same segment
    segment = db_session.query(Segments).get(old_trade.segment_id)
    new_trade = create_trade(
        segment_id=segment.id,
        milestone_id=old_trade.current_level_id,
        current_balance=segment.total_balance
    )
    print(f"--> Created new Trade ID: {new_trade.id} to replace the old one.")
    
    # Commit all DB changes (closing old, creating new)
    db_session.commit()
    
    # 4. Open fresh positions for the new trade
    # We defer this to a thread to avoid blocking the main loop
    deferToThread(_open_positions_for_trade, new_trade, bot)

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
    
    ending_balance = milestone.ending_balance
    lot_size = int(float(milestone.lot_size) * 100 * 100000)

    bot_instance.trade_couple[trade.id] = {
        "trade_id": trade.id,
        "ending_balance": ending_balance,
        "resulted_balance": None,
        "long_position_id": None, # This will be set at execution response
        "long_status": None,
        "short_position_id": None, # This will be set at execution response
        "short_status": None,
    }

    print(f"--- Opening positions for new Trade ID: {trade.id} with lot size {lot_size} ---")

    # Open LONG position
    bot_instance.client.send(ProtoOANewOrderReq(
        ctidTraderAccountId=bot_instance.account_id, symbolId=bot_instance.symbol_id,
        orderType=ProtoOAOrderType.MARKET, tradeSide=ProtoOATradeSide.Value("BUY"),
        volume=lot_size, clientOrderId=f"trade_{trade.id}_long_open"
    ))
    
    # Open SHORT position
    bot_instance.client.send(ProtoOANewOrderReq(
        ctidTraderAccountId=bot_instance.account_id, symbolId=bot_instance.symbol_id,
        orderType=ProtoOAOrderType.MARKET, tradeSide=ProtoOATradeSide.Value("SELL"),
        volume=lot_size, clientOrderId=f"trade_{trade.id}_short_open"
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
    # This callback will execute the status update after the close request is sent.
    d.addCallback(lambda _: _update_status_on_close(position_id))
    d.addErrback(lambda f: print("[✖] Close failed:", f))

def _update_status_on_close(position_id: int):
    """
    Updates the status of TradeDetail and parent Trade upon closing a position.
    """
    with SessionSync() as s:
        # 1. Find the TradeDetail
        trade_detail = s.query(TradeDetail).filter_by(position_id=position_id).first()
        if not trade_detail:
            print(f"[DB ERROR] Could not find TradeDetail for positionId: {position_id}")
            return

        # 2. Update TradeDetail status
        if trade_detail.position_type == 'long':
            trade_detail.status = 'closed'
        elif trade_detail.position_type == 'short':
            trade_detail.status = 'closed'

        print(f"[DB UPDATE] Updated TradeDetail {trade_detail.id} for Pos {position_id} to status '{trade_detail.status}'")

        # 3. Update parent Trade status
        parent_trade_id = trade_detail.trade_id
        parent_trade = s.query(Trades).get(parent_trade_id)
        if parent_trade:
            parent_trade.status = 'closed'
            print(f"[DB UPDATE] Updated parent Trade {parent_trade.id} to status 'closed'")

        s.commit()

def request_unrealized_pnl(bot):
    request = ProtoOAGetPositionUnrealizedPnLReq(ctidTraderAccountId=bot.account_id)
    bot.client.send(request)

def reconcile(bot):
    """
    Sends a reconcile request and returns a Deferred that will fire with the response.
    """
    d = Deferred()

    # Temporarily override the message handler to capture the specific response
    def custom_reconcile_handler(_, msg):
        if msg.payloadType == ProtoOAReconcileRes().payloadType:
            # When we get the response, fire the Deferred with the message payload
            d.callback(Protobuf.extract(msg))
            # IMPORTANT: Restore the original message handler immediately
            bot.client.setMessageReceivedCallback(lambda _, m: on_message(bot, m))

    bot.client.setMessageReceivedCallback(custom_reconcile_handler)
    bot.client.send(ProtoOAReconcileReq(ctidTraderAccountId=bot.account_id))
    return d