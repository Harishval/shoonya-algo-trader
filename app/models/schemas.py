"""Data models for the trading application."""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class StrategyState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


class Signal(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Trade(BaseModel):
    trade_id: str
    timestamp: datetime
    instrument: str
    symbol: str
    option_type: OptionType
    strike: float
    side: OrderSide
    quantity: int
    entry_price: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    status: OrderStatus = OrderStatus.OPEN
    stop_loss: float = 0.0
    target: float = 0.0
    exit_timestamp: Optional[datetime] = None


class Position(BaseModel):
    symbol: str
    instrument: str
    option_type: OptionType
    strike: float
    side: OrderSide
    quantity: int
    avg_price: float
    ltp: float = 0.0
    pnl: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0


class OptionData(BaseModel):
    strike: float
    ce_ltp: float = 0.0
    pe_ltp: float = 0.0
    ce_oi: int = 0
    pe_oi: int = 0
    ce_volume: int = 0
    pe_volume: int = 0
    ce_iv: float = 0.0
    pe_iv: float = 0.0
    ce_delta: float = 0.0
    pe_delta: float = 0.0


class MarketData(BaseModel):
    instrument: str
    ltp: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    timestamp: datetime = datetime.now()


class DashboardData(BaseModel):
    trading_mode: TradingMode
    strategy_state: StrategyState
    capital: float
    used_margin: float = 0.0
    daily_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    open_positions: List[Position] = []
    recent_trades: List[Trade] = []
    market_data: dict = {}
    option_chain: dict = {}
    signals: dict = {}
    pnl_history: List[dict] = []


class StrategyConfig(BaseModel):
    target_profit_percent: float = 2.0
    max_loss_percent: float = 1.0
    otm_strike_offset: int = 2
    max_open_positions: int = 4
    trailing_sl_percent: float = 0.5
    reentry_enabled: bool = True
    instruments: List[str] = ["NIFTY", "SENSEX"]
