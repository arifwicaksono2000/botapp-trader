# execution.py
import datetime as dt
from twisted.internet.defer import ensureDeferred
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
# from ..helpers import insert_deal
from .trading import close_position, reconcile
from twisted.internet import reactor
from datetime import timezone

def handle_execution(bot, ev):
    print("[✓] Execution Event:")

    # Basic validation: Ensure event has a position and an order
    if not ev.HasField("position") or not ev.HasField("order"):
        print("[!] Execution event missing position or order data. Skipping.")
        return

    order = ev.order
    pos = ev.position
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
    # Only proceed with order-specific logic if the order was filled
    if execution_type != ProtoOAExecutionType.ORDER_FILLED:
        print(f"[i] Unhandled Execution Type '{ProtoOAExecutionType.Name(execution_type)}' for pid={pid}, coid={coid}")
        return

    # --- Logic for Opening Positions ---
    # Check if this is an opening order for our hedged pair
    if coid == "OPEN_LONG_1" or coid == "OPEN_SHORT_2":
        # A new open order will have a non-zero current_volume
        if current_volume > 0:
            if coid == "OPEN_LONG_1":
                bot.open_long_id = pid
                print(f"[→] Long-opened {pid}. Hold {bot.hold}s…")
            elif coid == "OPEN_SHORT_2":
                bot.open_short_id = pid
                print(f"[→] Short-opened {pid}. Hold {bot.hold}s…")
            
            # Schedule closure for both sides using their actual position IDs
            # Ensure close_position correctly identifies which position to close
            reactor.callLater(bot.hold, close_position, bot, pid, current_volume) # Pass current_volume for accurate closing
            return # Handled this event

    # --- Logic for Closing Positions (Full or Partial) ---
    # A position close event can be identified by volume reduction or ProtoOAPositionStatus.POSITION_STATUS_CLOSED
    # The 'pos.tradeData.volume == 0' is a reliable indicator for a FULL close of a position.
    
    # Check if this event marks a full closure of one of our tracked hedged positions
    is_long_closed = (pid == getattr(bot, "open_long_id", None) and side == ProtoOATradeSide.Value("SELL") and current_volume == 0)
    is_short_closed = (pid == getattr(bot, "open_short_id", None) and side == ProtoOATradeSide.Value("BUY") and current_volume == 0)

    if is_long_closed:
        bot.positions[pid]["status"] = "CLOSED" # Explicitly mark as closed in bot's state
        print(f"[✓] Closed Long {pid} (SELL order executed, remaining volume is 0)")
        # Proceed to reconcile if the other side is also closed
        if getattr(bot, "open_short_id", None) and bot.positions.get(bot.open_short_id, {}).get("status") == "CLOSED":
            print("[→] Both sides closed → reconciling now…")
            reconcile(bot)
        return

    if is_short_closed:
        bot.positions[pid]["status"] = "CLOSED" # Explicitly mark as closed in bot's state
        print(f"[✓] Closed Short {pid} (BUY order executed, remaining volume is 0)")
        # Proceed to reconcile if the other side is also closed
        if getattr(bot, "open_long_id", None) and bot.positions.get(bot.open_long_id, {}).get("status") == "CLOSED":
            print("[→] Both sides closed → reconciling now…")
            reconcile(bot)
        return

    # --- Handle Partial Fills / Unhandled Scenarios ---
    # If the volume is > 0 but it's not an opening event (i.e., it's a partial fill or adjustment)
    if current_volume > 0:
        # If it's not an opening, and not a full close, it's a partial close or update
        # You might want to update the 'bot.positions[pid]["volume"]' here if not already done
        # The .update() call at the beginning of the function already handles this for all `ProtoOAExecutionType`s
        print(f"[i] Partial fill or position update for pid={pid}, remaining volume={current_volume}, coid={coid}")
        return
    
    # Fallback for any other unhandled execution event
    print(f"[i] Unhandled ORDER_FILLED scenario for pid={pid}, coid={coid}, volume={current_volume}")


def close_all_positions(bot):
    """Close every open position we know about."""
    for position_id, info in list(bot.positions.items()):
        if info["status"] == "OPEN":
            close_position(bot, position_id)
