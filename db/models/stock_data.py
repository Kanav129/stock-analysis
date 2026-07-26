from dotenv import load_dotenv
from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base

load_dotenv()

Base = declarative_base()


class StockData(Base):
    __tablename__ = "stock_data"
    __table_args__ = (
        UniqueConstraint("ticker", "bar_ts", "bar_interval", name="uq_stock_data_ticker_ts_interval"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False)
    date = Column(Date, nullable=False)
    bar_ts = Column(DateTime(timezone=True), nullable=False)
    bar_interval = Column(String(8), nullable=False, default="1d")  # '1m'|'15m'|'30m'|'1h'|'1d'
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger)
