# execution.py
import datetime as dt
from twisted.internet.defer import ensureDeferred
from twisted.internet.threads import deferToThread
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *       # noqa: F403,E402
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
from ..helpers import *
from twisted.internet import reactor
from datetime import timezone
from ..database import SessionSync
from .trading import _get_or_create_segment_and_trade
import os
import requests
import mysql.connector
from datetime import datetime, timedelta
from ..settings import CLIENT_ID, CLIENT_SECRET, SYMBOL_ID

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
    update_parent_trade_status(trade_id, final_status)

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

    # 2. Clean up memory by removing the completed trade from the bot's state
    if closed_trade_id in bot.trade_couple:
        del bot.trade_couple[closed_trade_id]
        print(f"[INFO] Removed completed trade {closed_trade_id} from memory.")

    # 3. Trigger the creation of a new trade cycle
    print(f"[>>>] Account is clean. Starting new trade cycle for account {bot.account_pk}")
    _get_or_create_segment_and_trade(bot)

def close_all_positions(bot):
    """Close every open position we know about."""
    for position_id, info in list(bot.positions.items()):
        if info["status"] == "OPEN":
            from .trading import close_position
            close_position(bot, position_id)

def _handle_token_refresh(bot):
    """
    Runs the get_ctrader_refresh.py script to get a new token,
    then fetches it from the DB and re-authenticates.
    """
    print("[INFO] Attempting to refresh access token by running script...")
    try:
        # Run the external script to refresh the token
        process = subprocess.run(
            ["python", "setup/get_ctrader_refresh.py"],
            capture_output=True, text=True, check=True, timeout=30
        )
        print(f"[INFO] Refresh script output:\n{process.stdout}")

        # After script success, fetch the new token from the database
        # Note: fetch_access_token is async, so we need to handle it correctly in a thread
        from asgiref.sync import async_to_sync
        new_token = async_to_sync(fetch_access_token)()
        
        # Update the bot's in-memory token
        bot.access_token = new_token
        print("[SUCCESS] New access token fetched and updated in bot's memory.")
        
        # Reset the flag and restart the authentication process
        bot.is_refreshing_token = False
        on_connected(bot)

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"[!!!] FATAL: Token refresh script failed: {e.stderr}")
        if reactor.running:
            reactor.stop()
    except Exception as e:
        print(f"[!!!] FATAL: An unexpected error occurred during token refresh: {e}")
        if reactor.running:
            reactor.stop()

def should_refresh_token(error_code, bot):
    print(f"[WARN] Invalid/Expired token detected (Code: {error_code}).")
    
    # Prevent infinite refresh loops
    if bot.is_refreshing_token:
        print("[!!!] FATAL: Already attempting to refresh token. Shutting down to prevent loop.")
        if reactor.running: reactor.stop()
        return

    bot.is_refreshing_token = True
    token_url = "https://openapi.ctrader.com/apps/token"
    
    db = None # Initialize db connection to None
    try:
        # 1. Fetch the latest refresh token from your database
        db = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            database=os.getenv("DB_NAME")
        )
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT refresh_token FROM botcore_token WHERE is_used = TRUE ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()

        if not row:
            raise RuntimeError("No active refresh token found in the database.")

        refresh_token_val = row["refresh_token"]
        print(f"🔄 Using refresh token: ...{refresh_token_val[-6:]}")

        # 2. Request new access token
        resp = requests.post(token_url, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token_val,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }, timeout=15) # Add a timeout for safety

        resp.raise_for_status() # Raises an exception for bad status codes (4xx or 5xx)

        data = resp.json()
        if data.get("errorCode"):
            raise RuntimeError(f"cTrader API Error: {data['errorCode']} - {data.get('description')}")

        new_access_token = data["accessToken"]
        new_refresh_token = data["refreshToken"]
        expires_at = datetime.now() + timedelta(seconds=data["expires_in"])
        
        print("✅ Token refreshed successfully!")

        # 3. Store the new tokens
        cursor.execute("UPDATE botcore_token SET is_used = FALSE WHERE is_used = TRUE")
        cursor.execute("""
            INSERT INTO botcore_token (access_token, refresh_token, is_used, expires_at, created_at, user_id)
            VALUES (%s, %s, TRUE, %s, %s, 1)
        """, (new_access_token, new_refresh_token, expires_at, datetime.now()))
        db.commit()
        
        print("📦 New tokens saved to database.")
        return True # Indicate success

    except Exception as e:
        print(f"[!!!] HELPER ERROR: Direct token refresh failed: {e}")
        # Re-raise the exception to be caught by the calling function in event_handlers.py
        raise e
    finally:
        # Ensure the database connection is always closed
        if db and db.is_connected():
            cursor.close()
            db.close()