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
)

from .database import Base


class TokenDB(Base):
    __tablename__ = "botcore_token"

    id = Column(Integer, primary_key=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text)
    is_used = Column(Boolean, default=False)
    expired_at = Column(DateTime)
    created_at = Column(DateTime, default=dt.datetime.utcnow)


class DealLog(Base):
    __tablename__ = "botcore_deallog"

    id = Column(Integer, primary_key=True)
    deal_id = Column(BigInteger)
    position_id = Column(BigInteger)
    order_id = Column(BigInteger)
    side = Column(Text)
    volume = Column(BigInteger)
    price = Column(Float)
    commission = Column(Float)
    swap = Column(Float)
    used_margin = Column(Float)
    execution_type = Column(Integer)
    timestamp = Column(DateTime, default=dt.datetime.utcnow)