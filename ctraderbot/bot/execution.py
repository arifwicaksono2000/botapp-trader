# execution.py
import datetime as dt
from twisted.internet.defer import ensureDeferred
from twisted.internet.threads import deferToThread
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
# from ..helpers import insert_deal
# from .trading import close_position, reconcile
from ..helpers import *
from twisted.internet import reactor
from datetime import timezone
from ..database import SessionSync

def handle_execution(bot, ev):
    print("[✓] Execution Event:")

    # Basic validation: Ensure event has a position and an order
    if not ev.HasField("position") or not ev.HasField("order"):
        print("[!] Execution event missing position or order data. Skipping.")
        return

    order = ev.order
    pos = ev.position
    deal = ev.deal
    pid = pos.positionId
    coid = order.clientOrderId # clientOrderId can be empty, but it's always there
    side = order.tradeData.tradeSide         # 1 = BUY, 2 = SELL (ProtoOATradeSide.BUY/SELL)
    entry_price = pos.price
    used_margin = pos.usedMargin
    current_volume = pos.tradeData.volume # This is the key for full/partial closes
    execution_type = ev.executionType # ProtoOAExecutionType enum

    # --- Store/Update Position State in bot.positions ---
    # Always update the latest state of the position in bot.positions.
    # This ensures your bot's internal state accurately reflects what cTrader reports.
    
    # Initialize position data if it's new
    if pid not in bot.positions:
        bot.positions[pid] = {}

    bot.positions[pid].update({
        "symbolId": pos.tradeData.symbolId,
        "volume": current_volume, # Use current_volume from event
        "entry_price": entry_price,
        "used_margin": used_margin,
        "swap": pos.swap,
        "timestamp": dt.datetime.now(timezone.utc).isoformat(), # Use timezone.utc
        "status": "OPEN", # Default to OPEN; will update to CLOSED if volume is 0 below
        "tradeSide": side, # Crucial for PnL calculation later
        "clientOrderId": coid,
        "type": order.orderType # Store order type (MARKET, LIMIT, etc.)
    })
    
    # Determine the actual status based on `pos.positionStatus`
    # ProtoOAPositionStatus.POSITION_STATUS_OPEN = 1
    # ProtoOAPositionStatus.POSITION_STATUS_CLOSED = 2
    if pos.positionStatus == 2: # ProtoOAPositionStatus.POSITION_STATUS_CLOSED
        bot.positions[pid]["status"] = "CLOSED"
    elif pos.positionStatus == 1: # ProtoOAPositionStatus.POSITION_STATUS_OPEN
        bot.positions[pid]["status"] = "OPEN" # Redundant with default, but explicit

    # --- Logging the Position State ---
    print(f"[TRACK] Pos {pid} | Side={ProtoOATradeSide.Name(side)} " # Use ProtoOATradeSide.Name for readability
          f"| Vol {current_volume} | Entry={entry_price} | "
          f"Margin={used_margin} | Status={bot.positions[pid]['status']} | coid={coid}")


    # --- Handle Execution Types ---
    if execution_type != ProtoOAExecutionType.ORDER_FILLED:
        print(f"[i] Unhandled Execution Type '{ProtoOAExecutionType.Name(execution_type)}' for pid={pid}, coid={coid}")
        return

    # --- Logic for Opening Positions ---
    if coid.startswith("trade_"):
        print(f"[COID] Trade with coid {coid}")
        if current_volume > 0:
            try:
                # Parse the clientOrderId (e.g., "trade_1_long_reopen")
                parts = coid.split('_')
                
                # --- START: ADD THIS NEW BLOCK ---
                trade_id = int(parts[1])
                position_type = parts[2] # This will be 'long' or 'short'

                # Update the trade_couple dictionary with the new position ID
                if trade_id in bot.trade_couple:
                    if position_type == 'long':
                        bot.trade_couple[trade_id]['long_position_id'] = pid
                        bot.trade_couple[trade_id]['long_status'] = 'running'
                    elif position_type == 'short':
                        bot.trade_couple[trade_id]['short_position_id'] = pid
                        bot.trade_couple[trade_id]['short_status'] = 'running'
                    print(f"[INFO] Updated trade_couple for trade {trade_id} with new position {pid}")
                # --- END: ADD THIS NEW BLOCK ---
                
                # Find the segment_id from the parent trade
                with SessionSync() as s:
                    trade = s.query(Trades).get(trade_id)
                    if not trade:
                        print(f"[ERROR] Could not find parent Trade with id {trade_id} for coid {coid}")
                        return
                    segment_id = trade.segment_id

                    segment = s.query(Segments).get(segment_id)
                    bot.positions[pid]["total_balance"] = segment.total_balance

                # Create the TradeDetail record with the correct IDs
                deferToThread(
                    create_trade_detail,
                    trade_id=trade_id,
                    segment_id=segment_id,
                    position_id=pid,
                    side=ProtoOATradeSide.Name(side),
                    lot_size=current_volume / 100.0,
                    entry_price=entry_price
                ).addErrback(lambda f: print(f"Failed to create TradeDetail for {pid}: {f}"))

                # print(f"[CLOSE POSITION SCHEDULED] Trade with id {trade_id} for coid {coid}")
                # from .trading import close_position
                # reactor.callLater(bot.hold, close_position, bot, pid, current_volume)
                
                # We only schedule a close for the initial positions, not re-opened ones.
                # You might want to add more sophisticated logic for re-opened positions here.
                if "reopen" not in coid:
                    print(f"[CLOSE POSITION SCHEDULED] Trade with id {trade_id} for coid {coid}")
                    from .trading import close_position
                    reactor.callLater(bot.hold, close_position, bot, pid, current_volume)
                
                return # Exit after handling the open event
            except (IndexError, ValueError) as e:
                print(f"[ERROR] Could not parse clientOrderId '{coid}': {e}")
                return

    # --- Logic for Closing Positions (Full or Partial) ---
    if pos.positionStatus == 2: # POSITION_STATUS_CLOSED
        print(f"[✓] Position {pid} is reported as CLOSED.")
        
        # Update our database records to reflect the closure
        deferToThread(
            update_trade_on_close,
            position_id=pid, 
            exit_price=deal.executionPrice,
            commission=deal.commission, 
            swap=pos.swap
        ).addErrback(lambda f: print(f"[DB ERROR] Failed to update closed position {pid}: {f}"))
        
        # After closing, we reconcile to ensure the bot's state is aligned.
        # You could add logic here to check if the other leg of the hedge is also closed
        # before reconciling, if desired.
        from .trading import reconcile
        reconcile(bot)
        return

    # --- Fallback for any other unhandled scenario ---
    print(f"[i] Unhandled ORDER_FILLED scenario for pid={pid}, coid={coid}")


def close_all_positions(bot):
    """Close every open position we know about."""
    for position_id, info in list(bot.positions.items()):
        if info["status"] == "OPEN":
            from .trading import close_position
            close_position(bot, position_id)
