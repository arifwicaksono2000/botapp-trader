# execution.py
import datetime as dt
import asyncio
import httpx
from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402
from twisted.internet.threads import deferToThread
from ..database import SessionSync
from ..models import Trades, TradeDetail

def handle_pnl_event(bot, msg):
    pnl_res = Protobuf.extract(msg)
    money_digits = pnl_res.moneyDigits
    # print(f"[DEBUG] UnrealizedPnLRes: {pnl_res}")

    for pnl_data in pnl_res.positionUnrealizedPnL:
        position_id = pnl_data.positionId
        unrealized_pnl = pnl_data.netUnrealizedPnL / (10 ** money_digits)
        gross_unrealized_pnl = pnl_data.grossUnrealizedPnL / (10 ** money_digits)

        if position_id in bot.positions:
            bot.positions[position_id]["unrealisedNetProfit"] = unrealized_pnl
            bot.positions[position_id]["grossUnrealisedProfit"] = gross_unrealized_pnl
            
            # Broadcast the update
            pos_data = bot.positions[position_id]
            actual_position_volume = pos_data["volume"] * 0.01
            display_lot = actual_position_volume / 100_000.0

            # display_lot = pos_data["volume"] / 100_000.0 # Standard lots

            current_balance_float = float(bot.positions[position_id]["total_balance"])
            halved_balance_float = current_balance_float / 2
            
            update_payload = {
                "positionId":    position_id,
                # "symbolId":      pos_data["symbolId"],
                "total_balance":   round(current_balance_float, 5),
                "lot":           display_lot,
                "entry_price":   round(pos_data["entry_price"], 5),
                # "price":         bot.latest_price, # You can use the latest mid-price for display
                "netUnrealisedPnL": round(unrealized_pnl, 2),
                "grossUnrealisedPnL": round(gross_unrealized_pnl, 2), # Added for completeness
                "status":        pos_data["status"],
            }

            deferToThread(_check_trade_status_on_pnl, bot, position_id, halved_balance_float, unrealized_pnl)

            print(f"[DEBUG] PnL: {update_payload}")
            asyncio.create_task(broadcast_position_update(update_payload))

async def broadcast_position_update(data):
    async with httpx.AsyncClient() as client:
        await client.post("http://localhost:9000/broadcast", json=data)


def _check_trade_status_on_pnl(bot, position_id, halved_balance, pnl):
    """
    Checks for liquidation or success conditions using ONLY in-memory data.
    If a condition is met, it triggers a background DB update.
    """
    trade_id = None
    trade_info = None
    position_side = None

    # 1. Find the trade and which side this position belongs to from memory
    for t_id, couple in bot.trade_couple.items():
        if couple.get("long_position_id") == position_id:
            trade_id = t_id
            trade_info = couple
            position_side = "long"
            break
        if couple.get("short_position_id") == position_id:
            trade_id = t_id
            trade_info = couple
            position_side = "short"
            break

    if not trade_id or trade_info.get(f"{position_side}_status") != "running":
        # Exit if trade not found or the position is not in a 'running' state in memory
        return

    ending_balance = float(trade_info["ending_balance"])
    new_status = None

    # 2. Check for Liquidation in memory
    if halved_balance + pnl <= 0:
        print(f"[!!!] LIQUIDATION DETECTED for position {position_id} in trade {trade_id}")
        new_status = 'liquidated'
        trade_info[f"{position_side}_status"] = new_status

    # 3. Check for Success in memory
    elif halved_balance + pnl > ending_balance:
        print(f"[$$$] SUCCESS DETECTED for position {position_id} in trade {trade_id}")
        new_status = 'successful'
        trade_info[f"{position_side}_status"] = new_status

    # 4. If a status change occurred, trigger the background DB update
    if new_status:
        deferToThread(_update_db_on_trade_event, trade_id, position_id, new_status, pnl)

def _update_db_on_trade_event(trade_id, position_id, new_status, pnl):
    """
    Updates the database in a separate thread after a success or liquidation event.
    """
    with SessionSync() as s:
        # Update the specific TradeDetail
        trade_detail = s.query(TradeDetail).filter_by(position_id=position_id).first()
        if not trade_detail or trade_detail.status != 'running':
            return # Already closed, do nothing

        trade_detail.status = new_status
        trade_detail.closed_at = dt.datetime.now(dt.timezone.utc)
        print(f"[DB UPDATE] Set TradeDetail for position {position_id} to '{new_status}'")

        # If the parent trade is now successful or fully liquidated, update it
        parent_trade = s.query(Trades).get(trade_id)
        if parent_trade and parent_trade.status == 'running':
            parent_trade.status = new_status # Set to 'successful' or 'liquidated'
            parent_trade.ending_balance = float(parent_trade.starting_balance) + pnl
            parent_trade.closed_at = dt.datetime.now(dt.timezone.utc)
            print(f"[DB UPDATE] Set parent Trade {trade_id} to '{new_status}'")

        s.commit()