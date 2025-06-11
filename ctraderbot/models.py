"""ORM models used by the bot, reconfigured based on Django model definitions."""
from __future__ import annotations
import datetime as dt
from datetime import timezone

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

# API tokens for bot connection
class TokenDB(Base):
    __tablename__ = "botcore_token"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("auth_user.id"), nullable=False)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text)
    is_used = Column(Boolean, default=False)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=dt.datetime.now(timezone.utc))

    def __str__(self):
        return f"Token {self.id}"

# Subaccounts management
class Subaccount(Base):
    __tablename__ = "botcore_subaccount"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("auth_user.id"), nullable=False)
    name = Column(String(100))
    platform = Column(String(20), default="ctrader")
    account_id = Column(String(50), unique=True)
    balance = Column(DECIMAL(15, 4))
    is_default = Column(Boolean, default=False)

    def __str__(self):
        return f"{self.name} ({self.platform})"

# Milestone checkpoints for hedging strategy
class Milestone(Base):
    __tablename__ = "botcore_milestone"

    id = Column(Integer, primary_key=True)
    starting_balance = Column(DECIMAL(15, 4))
    loss = Column(DECIMAL(15, 4))
    profit_goal = Column(DECIMAL(15, 4))
    lot_size = Column(DECIMAL(10, 4))
    ending_balance = Column(DECIMAL(15, 4))

    def __str__(self):
        return f"Milestone Level {self.id}"

# History records for each hedging trade session
class Segment(Base):
    __tablename__ = "botcore_segment"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True, index=True)
    subaccount_id = Column(Integer, ForeignKey("botcore_subaccount.id"), nullable=True)
    total_positions = Column(Integer)
    total_balance = Column(DECIMAL(15, 4))
    pair = Column(String(10), default="EURUSD")
    opened_at = Column(DateTime, default=dt.datetime.now(timezone.utc))
    closed_at = Column(DateTime, nullable=True)
    status = Column(String(10), default='running')

    def __str__(self):
        return f"Hedging Session {self.id} ({self.pair})"

# Model for tracking a full trade cycle (e.g., from one balance level to the next)
class Trade(Base):
    __tablename__ = "botcore_trade"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True, index=True)
    segment_id = Column(Integer, ForeignKey("botcore_segment.id"), nullable=True)
    curr_active = Column(String(10))  # 'L', 'S', 'B', 'N'
    current_level_id = Column(Integer, ForeignKey("botcore_milestone.id"), nullable=True)
    achieved_level_id = Column(Integer, ForeignKey("botcore_milestone.id"), nullable=True)
    starting_balance = Column(DECIMAL(15, 4))
    profit_goal = Column(DECIMAL(15, 4))
    ending_balance = Column(DECIMAL(15, 4))
    opened_at = Column(DateTime, default=dt.datetime.now(timezone.utc))
    closed_at = Column(DateTime, nullable=True)
    status = Column(String(10), default='running')
    
    def __str__(self):
        return f"Trades Balance {self.starting_balance}"

# Individual trade details (always pairs of Long & Short)
class TradeDetail(Base):
    __tablename__ = "botcore_tradedetail"

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True, index=True)
    trade_id = Column(Integer, ForeignKey("botcore_trade.id"), nullable=False)
    segment_id = Column(Integer, ForeignKey("botcore_segment.id"), nullable=True)
    position_id = Column(BigInteger)
    position_type = Column(String(10))  # 'long' or 'short'
    entry_price = Column(DECIMAL(20, 10))
    exit_price = Column(DECIMAL(20, 10), nullable=True)
    pips = Column(DECIMAL(10, 2), nullable=True)
    is_liquidated = Column(Boolean, default=False)
    lot_size = Column(DECIMAL(10, 2))
    opened_at = Column(DateTime, default=dt.datetime.now(timezone.utc))
    closed_at = Column(DateTime, nullable=True)

    def __str__(self):
        return f"{self.position_type.title()} | {self.entry_price} ({'Closed' if self.closed_at else 'Open'})"

# General purpose constants for the bot
class Constant(Base):
    __tablename__ = "botcore_constant"

    id = Column(Integer, primary_key=True)
    variable = Column(Text)
    value = Column(Text)
    
    def __str__(self):
        return f"Defined Variable {self.variable}"