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
    Checks for liquidation or success conditions and updates the database.
    This function is designed to be run in a separate thread.
    """
    trade_id = None
    trade_info = None

    # 1. Find the trade_id and which side this position belongs to
    for t_id, couple in bot.trade_couple.items():
        if couple.get("long_position_id") == position_id:
            trade_id = t_id
            trade_info = couple
            break
        if couple.get("short_position_id") == position_id:
            trade_id = t_id
            trade_info = couple
            break

    if not trade_id:
        # This can happen briefly if a PnL event arrives before the trade_couple is updated
        return

    ending_balance = float(trade_info["ending_balance"])
    should_update_trade = False
    new_trade_status = None

    with SessionSync() as s:
        trade_detail = s.query(TradeDetail).filter_by(position_id=position_id).first()
        if not trade_detail or trade_detail.status != 'running':
            return # Skip if detail not found or already closed

        # 2. Check for Liquidation
        if halved_balance + pnl <= 0:
            print(f"[!!!] LIQUIDATION DETECTED for position {position_id} in trade {trade_id}")
            trade_detail.status = 'liquidated'
            
            # Check if the other position is also liquidated
            other_pos_liquidated = False
            if trade_detail.position_type == 'long':
                if trade_info.get("short_status") == 'liquidated':
                    other_pos_liquidated = True
            elif trade_detail.position_type == 'short':
                if trade_info.get("long_status") == 'liquidated':
                    other_pos_liquidated = True
            
            if other_pos_liquidated:
                should_update_trade = True
                new_trade_status = 'liquidated'

        # 3. Check for Success
        elif halved_balance + pnl > ending_balance:
            print(f"[$$$] SUCCESS DETECTED for position {position_id} in trade {trade_id}")
            trade_detail.status = 'successful'
            should_update_trade = True
            new_trade_status = 'successful'
        
        # 4. Update parent Trade if necessary
        if should_update_trade:
            parent_trade = s.query(Trades).get(trade_id)
            if parent_trade and parent_trade.status == 'running':
                parent_trade.status = new_trade_status
                parent_trade.ending_balance = float(parent_trade.starting_balance) + pnl
                parent_trade.closed_at = dt.datetime.now(dt.timezone.utc)

        s.commit()