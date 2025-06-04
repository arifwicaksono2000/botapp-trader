"""ORM models used by the bot."""
from __future__ import annotations
import datetime as dt

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    BigInteger,
    Text,
    String,
    ForeignKey,
    DECIMAL,
)
from sqlalchemy.orm import relationship
from .database import Base


class TokenDB(Base):
    __tablename__ = "botcore_token"

    id = Column(Integer, primary_key=True)
    # user_id = Column(Integer, ForeignKey("auth_user.id"), nullable=False)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text)
    is_used = Column(Boolean, default=False)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    # user = relationship("User")


# class DealLog(Base):
#     __tablename__ = "botcore_deallog"

#     id = Column(Integer, primary_key=True)
#     deal_id = Column(BigInteger)
#     position_id = Column(BigInteger)
#     order_id = Column(BigInteger)
#     side = Column(Text)
#     volume = Column(BigInteger)
#     price = Column(Float)
#     commission = Column(Float)
#     swap = Column(Float)
#     used_margin = Column(Float)
#     execution_type = Column(Integer)
#     timestamp = Column(DateTime, default=dt.datetime.utcnow)


class Subaccount(Base):
    __tablename__ = "botcore_subaccount"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("auth_user.id"), nullable=False)
    name = Column(String(100))
    platform = Column(String(20), default="ctrader")
    account_id = Column(String(50), unique=True)
    balance = Column(DECIMAL(15, 4))
    is_default = Column(Boolean, default=False)

    # user = relationship("User")


class Milestone(Base):
    __tablename__ = "botcore_milestone"

    id = Column(Integer, primary_key=True)
    starting_balance = Column(DECIMAL(15, 4))
    loss = Column(DECIMAL(15, 4))
    profit_goal = Column(DECIMAL(15, 4))
    lot_size = Column(DECIMAL(10, 4))
    ending_balance = Column(DECIMAL(15, 4))


class Segment(Base):
    __tablename__ = "botcore_segment"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True)
    subaccount_id = Column(Integer, ForeignKey("botcore_subaccount.id"), nullable=True)
    milestone_id = Column(Integer, ForeignKey("botcore_milestone.id"), nullable=True)
    total_positions = Column(Integer)
    total_balance = Column(DECIMAL(15, 4))
    pair = Column(String(10), default="EURUSD")
    opened_at = Column(DateTime, default=dt.datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

#     subaccount = relationship("Subaccount")
#     milestone = relationship("Milestone")


class Trade(Base):
    __tablename__ = "botcore_trade"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True)
    curr_active = Column(String(10))  # 'L' or 'S'
    current_level = Column(Integer)
    achieved_level = Column(Integer)
    starting_balance = Column(DECIMAL(15, 4))
    profit_goal = Column(DECIMAL(15, 4))
    ending_balance = Column(DECIMAL(15, 4))
    opened_at = Column(DateTime, default=dt.datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)


class TradeDetail(Base):
    __tablename__ = "botcore_tradedetail"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True)
    trade_id = Column(Integer, ForeignKey("botcore_trade.id"))
    position_type = Column(String(10))  # 'long' or 'short'
    entry_price = Column(DECIMAL(20, 10))
    exit_price = Column(DECIMAL(20, 10), nullable=True)
    pips = Column(DECIMAL(10, 2), nullable=True)
    latest_balance = Column(DECIMAL(15, 2), nullable=True)
    is_liquidated = Column(Boolean, default=False)
    lot_size = Column(DECIMAL(10, 2))
    response = Column(Text)
    opened_at = Column(DateTime, default=dt.datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

#     trade = relationship("Trade", backref="details")
