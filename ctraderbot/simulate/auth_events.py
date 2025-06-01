import datetime as dt
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAPackage
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAAppAuthRes,
    ProtoOAAccountAuthRes,
    ProtoOAExecutionEvent,
    ProtoOATradeData,
    ProtoOAOrder,
    ProtoOADeal,
    ProtoOAPosition,
)
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoOATradeSide, ProtoOAExecutionType
from ctraderbot.bot.event_handlers import on_message  # where you defined it
from ctraderbot.bot.simple_bot import SimpleBot


def make_fake_auth_res(is_account=False, trader_account_id=None):
    """
    If is_account=False, produce a fake ProtoOAAppAuthRes (delivery as “app auth”).
    If is_account=True, produce a fake ProtoOAAccountAuthRes (delivery as “account auth”).
    """
    if not is_account:
        msg = ProtoOAAppAuthRes(
            # Normally the server would fill in some fields; but all we need 
            # is payloadType to match so your handler sees “App authenticated.”
        )
    else:
        msg = ProtoOAAccountAuthRes(
            ctidTraderAccountId=trader_account_id or "DUMMY_ACCOUNT_ID",
            # ... you can fill other fields as needed
        )
    pkg = ProtoOAPackage()
    pkg.payloadType = msg.payloadType
    pkg.payload = msg.SerializeToString()
    return pkg

def make_fake_execution_event(trader_account_id, position_id, volume, price, side_str="BUY"):
    # This is essentially the same code as above, slightly abbreviated
    ev = ProtoOAExecutionEvent(
        executionType=ProtoOAExecutionType.ORDER_FILLED,
        deal=ProtoOADeal(
            dealId=123456,
            positionId=position_id,
            executionPrice=price,
            volume=volume,
            commission=0.0,
        ),
        order=ProtoOAOrder(
            orderId=654321,
            ctidTraderAccountId=trader_account_id,
            tradeData=ProtoOATradeData(
                symbolId=1,
                tradeSide=ProtoOATradeSide.Value(side_str),
                volume=volume,
            ),
        ),
        position=ProtoOAPosition(
            positionId=position_id,
            tradeData=ProtoOATradeData(
                symbolId=1,
                tradeSide=ProtoOATradeSide.Value(side_str),
                volume=volume,
            ),
            usedMargin=100.0,
            swap=0.0,
            price=price,
            positionStatus=1,  # “OPEN”
        )
    )
    pkg = ProtoOAPackage()
    pkg.payloadType = ev.payloadType
    pkg.payload = ev.SerializeToString()
    return pkg

if __name__ == "__main__":
    # 1) Instantiate your Bot (normally your CLI would do this).
    bot = SimpleBot(
        client_id="DUMMY_CLIENT_ID",
        client_secret="DUMMY_CLIENT_SECRET",
        symbol_id=1,
        account_id="DUMMY_ACCOUNT_ID",
        volume=100000
    )

    # 2) Manually call the “connected” callback so it thinks it connected.
    # In most designs, on_connected(bot) will send your ApplicationAuthReq,
    # but since we’re faking the server, skip straight to delivering the fake
    # ProtoOAAppAuthRes:
    fake_app_auth = make_fake_auth_res(is_account=False)
    on_message(bot, fake_app_auth)

    # 3) Now simulate the “account auth” reply:
    fake_acc_auth = make_fake_auth_res(is_account=True, trader_account_id=bot.account_id)
    on_message(bot, fake_acc_auth)

    # 4) Your code (in after_account_auth) will call `send_market_order(bot)`.
    #    That normally sends two NewOrderReqs. But since we’re in “market closed”
    #    we never see real ExecutionEvents. Let’s fake one:
    fake_fill_1 = make_fake_execution_event(
        trader_account_id=bot.account_id,
        position_id=111111,   # pick any ID (the code uses bot.open_position_id later)
        volume=bot.volume,
        price=1.23456,
        side_str="BUY"
    )
    on_message(bot, fake_fill_1)

    # 5) Suppose your code wants to close after 60s. We can fast‐forward time by
    #    simply calling the “second” fill event immediately:
    fake_fill_2 = make_fake_execution_event(
        trader_account_id=bot.account_id,
        position_id=111111,   # same ID, meaning “same position now closed”
        volume=bot.volume,
        price=1.23500,
        side_str="SELL"
    )
    on_message(bot, fake_fill_2)

    # At this point your handle_execution logic should print exactly the same flow
    # you’d see in a live environment—first “Position opened … Hold 60s…” then
    # “Position 111111 closed.” Then reconcile is called, etc.

    print(">>> Simulation finished.")
