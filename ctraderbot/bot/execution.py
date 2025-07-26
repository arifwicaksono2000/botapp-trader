# execution.py
import datetime as dt
from twisted.internet.defer import ensureDeferred
from twisted.internet.threads import deferToThread
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
from ..helpers import *
from datetime import timezone
from ..database import SessionSync
# from .trading import _get_or_create_segment_and_trade


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
                    bot.positions[pid]["total_balance"] = segment.total_balance / 2

                # Create the TradeDetail record with the correct IDs
                deferToThread(
                    create_trade_detail,
                    trade_id=trade_id,
                    segment_id=segment_id,
                    position_id=pid,
                    side=ProtoOATradeSide.Name(side),
                    lot_size=current_volume / (100_000.0 * 100), # Convert to standard lots
                    entry_price=entry_price
                ).addErrback(lambda f: print(f"Failed to create TradeDetail for {pid}: {f}"))

                # print(f"[CLOSE POSITION SCHEDULED] Trade with id {trade_id} for coid {coid}")
                # from .trading import close_position
                # reactor.callLater(bot.hold, close_position, bot, pid, current_volume)
                
                # We only schedule a close for the initial positions, not re-opened ones.
                # You might want to add more sophisticated logic for re-opened positions here.
                # if "reopen" not in coid:
                #     print(f"[CLOSE POSITION SCHEDULED] Trade with id {trade_id} for coid {coid}")
                #     from .trading import close_position
                #     reactor.callLater(bot.hold, close_position, bot, pid, current_volume)
                
                return # Exit after handling the open event
            except (IndexError, ValueError) as e:
                print(f"[ERROR] Could not parse clientOrderId '{coid}': {e}")
                return

    # --- Logic for Closing Positions (Full or Partial) ---
    if pos.positionStatus == 2: # POSITION_STATUS_CLOSED
        print(f"[✓] Position {pid} is reported as CLOSED.")

        # Defer the entire closing workflow to a background thread
        deferToThread(
            _handle_closed_position_workflow,
            bot,
            pid,
            deal.executionPrice,
            deal.commission,
            pos.swap
        ).addErrback(lambda f: print(f"[!!!] Closed position workflow failed for {pid}: {f}"))
        
        return # End execution here, the thread will handle the rest

    # --- Fallback for any other unhandled scenario ---
    print(f"[i] Unhandled ORDER_FILLED scenario for pid={pid}, coid={coid}")

def _handle_closed_position_workflow(bot, closed_pid, exit_price, commission, swap):
    """
    Manages the full workflow after a position is confirmed closed.
    This runs in a background thread.
    """
    # 1. Find which trade this position belongs to
    trade_id = None
    trade_info = None
    closed_side = None

    # get which position is closed from coid
    for t_id, couple in bot.trade_couple.items():
        if couple.get("long_position_id") == closed_pid:
            trade_id, trade_info, closed_side = t_id, couple, "long"
            break
        if couple.get("short_position_id") == closed_pid:
            trade_id, trade_info, closed_side = t_id, couple, "short"
            break

    if not trade_id:
        print(f"[WARN] Could not find trade couple for closed position {closed_pid}. No action taken.")
        return

    # 2. Update the database for the single closed position
    final_status = trade_info.get(f"{closed_side}_status") # 'successful' or 'liquidated'
    update_trade_detail_on_close(closed_pid, exit_price, commission, swap, final_status)

    # 3. Check if both positions in the couple are now closed
    if closed_side == "long":
        other_side = "short"
    elif closed_side == "short":
        other_side = "long"
    else:
        print(f"[ERROR] Unknown closed side '{closed_side}' for position {closed_pid}. Cannot determine other side.")
        return

    other_pos_status = trade_info.get(f"{other_side}_status")

    if other_pos_status not in ['successful', 'liquidated', 'closed']:
        print(f"[INFO] Position {closed_pid} closed. Other side ({other_side}) is still running. Waiting...")
        return
    
    # 4. If both are closed, finalize the trade and start a new one
    print(f"[>>>] Both positions for trade {trade_id} are {other_pos_status}. Finalizing trade cycle.")
    
    # Update the parent Trade row status to successful/liquidated
    update_parent_trade_status(trade_id, final_status, trade_info["resulted_balance"])

    # 5. Reconcile to verify closure and clean up memory
    from .trading import reconcile
    d = reconcile(bot)
    d.addCallback(_after_reconcile_cleanup, bot=bot, closed_trade_id=trade_id, closed_trade_info=trade_info)
    d.addErrback(lambda f: print(f"[!!!] Reconcile after trade close failed: {f}"))

def _after_reconcile_cleanup(reconcile_res, bot, closed_trade_id, closed_trade_info):
    """
    Final step after reconciliation: verify closure, clean memory, and start new trade.
    """
    server_position_ids = {pos.positionId for pos in reconcile_res.position}
    
    # 1. Verify that the positions from the just-closed trade are truly gone
    long_pid = closed_trade_info.get("long_position_id")
    short_pid = closed_trade_info.get("short_position_id")

    if long_pid in server_position_ids or short_pid in server_position_ids:
        print(f"[!!!] CRITICAL WARNING: Positions for trade {closed_trade_id} still exist on server after close command!")
        from .trading import close_position

        # Fallback: Find the lingering position(s) and attempt to close them again.
        for pos in reconcile_res.position:
            # Check if this position is one of the ones that should have been closed.
            if pos.positionId == long_pid or pos.positionId == short_pid:
                print(f"--> Sending fallback CLOSE command for lingering position {pos.positionId}")
                volume_to_close = pos.tradeData.volume
                close_position(bot, pos.positionId, volume_to_close)

        return # Stop the process to prevent creating overlapping trades

    # 2. Clean up memory, Both positions are deleted immediately here
    if closed_trade_id in bot.trade_couple:
        del bot.trade_couple[closed_trade_id]
        print(f"[INFO] Removed completed trade {closed_trade_id} from memory.")
    
    # ---- START: NEW DELETION LOGIC ----
    if long_pid and long_pid in bot.positions:
        del bot.positions[long_pid]
        print(f"[INFO] Removed closed position {long_pid} from bot.positions.")

    if short_pid and short_pid in bot.positions:
        del bot.positions[short_pid]
        print(f"[INFO] Removed closed position {short_pid} from bot.positions.")
    # ---- END: NEW DELETION LOGIC ----

    # 3. Trigger the creation of a new trade cycle
    print(f"[>>>] Account is clean. Starting new trade cycle for account {bot.account_pk}")

    # Send a request to get the latest trader info, which includes the balance
    bot.client.send(ProtoOATraderReq(ctidTraderAccountId=bot.account_id))

    # Moved to trader response event handler
    # _get_or_create_segment_and_trade(bot)

def close_all_positions(bot):
    """Close every open position we know about."""
    for position_id, info in list(bot.positions.items()):
        if info["status"] == "OPEN":
            from .trading import close_position
            close_position(bot, position_id)
