import inspect

from sqlalchemy import JSON, Column, Index, Text

from hummingbot.model import HummingbotBase
from hummingbot.model.decimal_type_decorator import SqliteDecimal


class MarketData(HummingbotBase):
    __tablename__ = "MarketData"
    __table_args__ = (
        Index("timestamp", "exchange", "trading_pair"),
    )

    timestamp = Column(SqliteDecimal(18), primary_key=True, nullable=False)  # Increased from 6 to 18 for precision
    exchange = Column(Text, nullable=False)
    trading_pair = Column(Text, nullable=False)
    mid_price = Column(SqliteDecimal(18), nullable=False)  # Increased from 6 to 18 for precision
    best_bid = Column(SqliteDecimal(18), nullable=False)  # Increased from 6 to 18 for precision
    best_ask = Column(SqliteDecimal(18), nullable=False)  # Increased from 6 to 18 for precision
    order_book = Column(JSON)

    def __repr__(self) -> str:
        list_of_fields = [f"{name}: {value}" for name, value in inspect.getmembers(self) if isinstance(value, Column)]
        return ','.join(list_of_fields)
