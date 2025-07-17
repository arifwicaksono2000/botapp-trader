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
            halved_balance_float = current_balance_float
            # halved_balance_float = current_balance_float / 2
            
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
        from .trading import close_position
        print(f"--> Triggering CLOSE for position {position_id} due to status: {new_status}")
        # We need the volume to close the position, get it from bot.positions
        volume_to_close = bot.positions[position_id].get("volume", 0)
        if volume_to_close > 0:
            close_position(bot, position_id, volume_to_close)