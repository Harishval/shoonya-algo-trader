"""Directional OTM options trading strategy.

Strategy Logic:
1. Monitor underlying (Nifty/Sensex) price action
2. Detect direction using multiple indicators:
   - Short-term momentum (price change over N ticks)
   - VWAP-style bias (above/below moving average)
   - Breakout detection (new high/low in lookback period)
3. Buy OTM CE when bullish, OTM PE when bearish
4. Book profits quickly at target, cut losses at SL
5. Trail stop-loss once in profit
6. Re-enter on new signals after exit
"""

import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from collections import deque

from app.config import settings
from app.models.schemas import (
    Trade, Position, OrderSide, OptionType, OrderStatus,
    Signal, StrategyState, StrategyConfig,
)
from app.strategy.risk_manager import RiskManager

logger = logging.getLogger(__name__)

LOT_SIZE = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "SENSEX": 10,
    "BANKEX": 15,
}

STRIKE_GAP = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "SENSEX": 100,
    "BANKEX": 100,
}


class DirectionalOTMStrategy:
    """Directional OTM options buying strategy targeting quick profits."""

    def __init__(self, broker, risk_manager: RiskManager):
        self.broker = broker
        self.risk = risk_manager
        self.state = StrategyState.IDLE
        self.config = StrategyConfig(
            instruments=settings.instrument_list,
            target_profit_percent=settings.target_profit_percent,
            max_loss_percent=settings.max_loss_percent,
            otm_strike_offset=settings.otm_strike_offset,
            max_open_positions=settings.max_open_positions,
        )

        # Price history for each instrument
        self._price_history: Dict[str, deque] = {}
        self._lookback = 20  # number of ticks for indicators
        self._ema_short = 5
        self._ema_long = 15

        # Active trades
        self._active_trades: Dict[str, Trade] = {}
        self._closed_trades: List[Trade] = []
        self._trade_counter = 0

        # PnL history for charting
        self._pnl_history: List[dict] = []

        # Signal state
        self._last_signals: Dict[str, Signal] = {}

    def start(self):
        """Start the strategy."""
        self.state = StrategyState.RUNNING
        self.risk.reset_daily()
        logger.info("Strategy STARTED for instruments: %s", self.config.instruments)

    def stop(self):
        """Stop the strategy."""
        self.state = StrategyState.STOPPED
        logger.info("Strategy STOPPED")

    def pause(self):
        """Pause the strategy."""
        self.state = StrategyState.PAUSED
        logger.info("Strategy PAUSED")

    def resume(self):
        """Resume the strategy."""
        self.state = StrategyState.RUNNING
        logger.info("Strategy RESUMED")

    def update_config(self, new_config: StrategyConfig):
        """Update strategy configuration."""
        self.config = new_config
        self.risk.update_config(
            target_profit_percent=new_config.target_profit_percent,
            max_loss_percent=new_config.max_loss_percent,
            max_open_positions=new_config.max_open_positions,
            trailing_sl_percent=new_config.trailing_sl_percent,
        )
        logger.info("Strategy config updated")

    def tick(self) -> Dict:
        """Main strategy loop — called on each tick/interval.

        Returns a dictionary with current state for the dashboard.
        """
        if self.state != StrategyState.RUNNING:
            return self._get_state()

        results = {}
        for instrument in self.config.instruments:
            try:
                result = self._process_instrument(instrument)
                results[instrument] = result
            except Exception as e:
                logger.error("Error processing %s: %s", instrument, e)
                results[instrument] = {"error": str(e)}

        # Record PnL snapshot
        total_pnl = self.risk.daily_pnl + sum(
            t.pnl or 0 for t in self._active_trades.values()
        )
        self._pnl_history.append({
            "timestamp": datetime.now().isoformat(),
            "pnl": round(total_pnl, 2),
        })

        return self._get_state()

    def _process_instrument(self, instrument: str) -> Dict:
        """Process a single instrument: check signals, manage positions."""
        # Get current price
        ltp = self.broker.get_underlying_ltp(instrument)
        if ltp is None:
            return {"error": "No LTP available"}

        # Update price history
        if instrument not in self._price_history:
            self._price_history[instrument] = deque(maxlen=100)
        self._price_history[instrument].append(ltp)

        # Calculate signal
        signal = self._calculate_signal(instrument, ltp)
        self._last_signals[instrument] = signal

        # Get current expiry
        expiry = self.broker.get_current_expiry(instrument)

        # Manage existing positions
        self._manage_positions(instrument, expiry)

        # Check for new entry
        open_positions = list(self._active_trades.values())
        instrument_positions = [t for t in open_positions if t.instrument == instrument]

        if (
            signal != Signal.NEUTRAL
            and self.risk.can_take_new_trade(open_positions)
            and len(instrument_positions) < 2  # max 2 per instrument
        ):
            self._enter_trade(instrument, signal, ltp, expiry)

        return {
            "ltp": ltp,
            "signal": signal.value,
            "active_trades": len(instrument_positions),
        }

    def _calculate_signal(self, instrument: str, current_price: float) -> Signal:
        """Calculate trading signal based on price action indicators."""
        history = self._price_history.get(instrument, deque())
        if len(history) < self._ema_long:
            return Signal.NEUTRAL

        prices = list(history)

        # EMA calculation
        ema_short = self._calc_ema(prices, self._ema_short)
        ema_long = self._calc_ema(prices, self._ema_long)

        # Momentum: price change over last N ticks
        momentum = (prices[-1] - prices[-self._ema_short]) / prices[-self._ema_short] * 100

        # Breakout: new high/low in lookback
        recent = prices[-self._lookback:] if len(prices) >= self._lookback else prices
        is_high = current_price >= max(recent)
        is_low = current_price <= min(recent)

        # Signal logic
        bullish_count = 0
        bearish_count = 0

        # EMA crossover
        if ema_short > ema_long:
            bullish_count += 1
        elif ema_short < ema_long:
            bearish_count += 1

        # Momentum
        if momentum > 0.05:
            bullish_count += 1
        elif momentum < -0.05:
            bearish_count += 1

        # Breakout
        if is_high:
            bullish_count += 1
        elif is_low:
            bearish_count += 1

        # Strong signal needs at least 2 confirmations
        if bullish_count >= 2:
            return Signal.BULLISH
        elif bearish_count >= 2:
            return Signal.BEARISH
        else:
            return Signal.NEUTRAL

    def _calc_ema(self, prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average."""
        if len(prices) < period:
            return sum(prices) / len(prices)

        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period

        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema

        return ema

    def _enter_trade(
        self, instrument: str, signal: Signal, underlying_ltp: float, expiry: str
    ):
        """Enter a new directional OTM trade."""
        gap = STRIKE_GAP.get(instrument, 50)
        atm = round(underlying_ltp / gap) * gap
        offset = self.config.otm_strike_offset

        if signal == Signal.BULLISH:
            # Buy OTM Call
            strike = atm + (offset * gap)
            option_type = OptionType.CE
        else:
            # Buy OTM Put
            strike = atm - (offset * gap)
            option_type = OptionType.PE

        # Get option quote
        quote = self.broker.get_option_quote(instrument, strike, option_type.value, expiry)
        if quote is None:
            logger.warning("No quote for %s %s %s", instrument, strike, option_type.value)
            return

        entry_price = quote["ltp"]
        if entry_price <= 0:
            return

        lot_size = LOT_SIZE.get(instrument, 25)
        quantity = lot_size  # 1 lot

        # Check if premium cost is within capital limits
        premium_cost = entry_price * quantity
        if premium_cost > self.risk.capital * 0.1:  # max 10% of capital per trade
            logger.warning("Premium too high: %.2f (limit: %.2f)",
                           premium_cost, self.risk.capital * 0.1)
            return

        # Calculate SL and target
        stop_loss = self.risk.calculate_stop_loss(entry_price, OrderSide.BUY)
        target = self.risk.calculate_target(entry_price, OrderSide.BUY)

        # Place order
        symbol = quote["tsym"]
        exchange = quote["exchange"]
        order_id = self.broker.place_order(
            instrument=instrument,
            symbol=symbol,
            exchange=exchange,
            side=OrderSide.BUY,
            quantity=quantity,
            price=entry_price,
            order_type="MKT",
        )

        if order_id:
            self._trade_counter += 1
            trade_id = f"T-{self._trade_counter:06d}"
            trade = Trade(
                trade_id=trade_id,
                timestamp=datetime.now(),
                instrument=instrument,
                symbol=symbol,
                option_type=option_type,
                strike=strike,
                side=OrderSide.BUY,
                quantity=quantity,
                entry_price=entry_price,
                status=OrderStatus.OPEN,
                stop_loss=stop_loss,
                target=target,
            )
            self._active_trades[trade_id] = trade
            logger.info(
                "ENTRY: %s %s %s @ %.2f | SL: %.2f | Target: %.2f | Signal: %s",
                instrument, strike, option_type.value, entry_price,
                stop_loss, target, signal.value,
            )

    def _manage_positions(self, instrument: str, expiry: str):
        """Check and manage existing positions — SL, target, trailing SL."""
        trades_to_close = []

        for trade_id, trade in self._active_trades.items():
            if trade.instrument != instrument or trade.status != OrderStatus.OPEN:
                continue

            # Get current option price
            quote = self.broker.get_option_quote(
                trade.instrument, trade.strike, trade.option_type.value, expiry
            )
            if quote is None:
                continue

            current_price = quote["ltp"]

            # Update trailing SL
            new_sl = self.risk.calculate_trailing_sl(
                trade.entry_price, current_price, trade.stop_loss, trade.side
            )
            if new_sl != trade.stop_loss:
                trade.stop_loss = new_sl
                logger.debug("Trailing SL updated for %s: %.2f", trade_id, new_sl)

            # Check exit conditions
            should_exit, reason = self.risk.should_exit(
                Position(
                    symbol=trade.symbol,
                    instrument=trade.instrument,
                    option_type=trade.option_type,
                    strike=trade.strike,
                    side=trade.side,
                    quantity=trade.quantity,
                    avg_price=trade.entry_price,
                    ltp=current_price,
                    stop_loss=trade.stop_loss,
                    target=trade.target,
                ),
                current_price,
            )

            if should_exit:
                trades_to_close.append((trade_id, current_price, reason))

        # Close trades
        for trade_id, exit_price, reason in trades_to_close:
            self._exit_trade(trade_id, exit_price, reason)

    def _exit_trade(self, trade_id: str, exit_price: float, reason: str):
        """Exit an active trade."""
        trade = self._active_trades.get(trade_id)
        if trade is None:
            return

        # Place exit order
        exchange = "NFO" if trade.instrument in ("NIFTY", "BANKNIFTY", "FINNIFTY") else "BFO"
        order_id = self.broker.place_order(
            instrument=trade.instrument,
            symbol=trade.symbol,
            exchange=exchange,
            side=OrderSide.SELL,  # exit buy position
            quantity=trade.quantity,
            price=exit_price,
            order_type="MKT",
        )

        if order_id:
            pnl = (exit_price - trade.entry_price) * trade.quantity
            trade.exit_price = exit_price
            trade.pnl = round(pnl, 2)
            trade.status = OrderStatus.COMPLETE
            trade.exit_timestamp = datetime.now()

            is_win = pnl > 0
            self.risk.update_daily_pnl(pnl, is_win)

            self._closed_trades.append(trade)
            del self._active_trades[trade_id]

            logger.info(
                "EXIT [%s]: %s %s %s @ %.2f → %.2f | PnL: %.2f | Daily: %.2f",
                reason.upper(), trade.instrument, trade.strike,
                trade.option_type.value, trade.entry_price, exit_price,
                pnl, self.risk.daily_pnl,
            )

    def force_exit_all(self):
        """Force exit all open positions."""
        for trade_id, trade in list(self._active_trades.items()):
            expiry = self.broker.get_current_expiry(trade.instrument)
            quote = self.broker.get_option_quote(
                trade.instrument, trade.strike, trade.option_type.value, expiry
            )
            if quote:
                self._exit_trade(trade_id, quote["ltp"], "force_exit")
            else:
                self._exit_trade(trade_id, trade.entry_price * 0.9, "force_exit_estimated")

    def _get_state(self) -> Dict:
        """Get complete strategy state for the dashboard."""
        active = [t.model_dump() for t in self._active_trades.values()]
        closed = [t.model_dump() for t in self._closed_trades[-50:]]  # last 50
        risk_stats = self.risk.get_stats()

        # Convert datetime objects for JSON serialization
        for trade_list in [active, closed]:
            for t in trade_list:
                for key in ["timestamp", "exit_timestamp"]:
                    if t.get(key) and isinstance(t[key], datetime):
                        t[key] = t[key].isoformat()

        return {
            "state": self.state.value,
            "active_trades": active,
            "closed_trades": closed,
            "signals": {k: v.value for k, v in self._last_signals.items()},
            "risk": risk_stats,
            "pnl_history": self._pnl_history[-100:],
            "config": self.config.model_dump(),
        }

    def get_active_positions(self) -> List[Position]:
        """Get active positions as Position objects."""
        positions = []
        for trade in self._active_trades.values():
            positions.append(Position(
                symbol=trade.symbol,
                instrument=trade.instrument,
                option_type=trade.option_type,
                strike=trade.strike,
                side=trade.side,
                quantity=trade.quantity,
                avg_price=trade.entry_price,
                ltp=trade.entry_price,  # updated in manage_positions
                stop_loss=trade.stop_loss,
                target=trade.target,
            ))
        return positions
