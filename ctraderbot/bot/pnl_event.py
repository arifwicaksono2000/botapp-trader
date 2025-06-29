# execution.py
import asyncio
import httpx
from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *       # noqa: F403,E402

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
            
            update_payload = {
                "positionId":    position_id,
                # "symbolId":      pos_data["symbolId"],
                "lot":           display_lot,
                "entry_price":   round(pos_data["entry_price"], 5),
                # "price":         bot.latest_price, # You can use the latest mid-price for display
                "netUnrealisedPnL": round(unrealized_pnl, 2),
                "grossUnrealisedPnL": round(gross_unrealized_pnl, 2), # Added for completeness
                "status":        pos_data["status"],
            }

            # with SessionSync() as s:
            #     tradeDetail = s.query(TradeDetail).filter_by(position_id=position_id).one()
            #     segment = s.query(Segments).filter_by(id=tradeDetail.segment_id).one()

            print(f"[DEBUG] PnL: {update_payload}")
            asyncio.create_task(broadcast_position_update(update_payload))

async def broadcast_position_update(data):
    async with httpx.AsyncClient() as client:
        await client.post("http://localhost:9000/broadcast", json=data)