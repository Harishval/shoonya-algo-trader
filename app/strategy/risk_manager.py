"""Risk management module for controlling exposure and losses."""

import logging
from typing import Optional, List
from app.config import settings
from app.models.schemas import Position, OrderSide

logger = logging.getLogger(__name__)


class RiskManager:
    """Manages trading risk: position limits, daily loss limits, and stop-losses."""

    def __init__(self):
        self.capital = settings.capital
        self.max_loss_percent = settings.max_loss_percent
        self.target_profit_percent = settings.target_profit_percent
        self.max_open_positions = settings.max_open_positions
        self.trailing_sl_percent = 0.5  # trailing stop-loss percent

        # Daily tracking
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.daily_wins = 0
        self.daily_losses = 0
        self._daily_loss_hit = False
        self._daily_target_hit = False

    @property
    def max_loss_amount(self) -> float:
        return self.capital * (self.max_loss_percent / 100.0)

    @property
    def target_profit_amount(self) -> float:
        return self.capital * (self.target_profit_percent / 100.0)

    def can_take_new_trade(self, open_positions: List[Position]) -> bool:
        """Check if a new trade is allowed."""
        if self._daily_loss_hit:
            logger.warning("Daily loss limit hit — no new trades")
            return False

        if self._daily_target_hit:
            logger.info("Daily target reached — no new trades")
            return False

        if len(open_positions) >= self.max_open_positions:
            logger.warning("Max open positions (%d) reached", self.max_open_positions)
            return False

        return True

    def calculate_stop_loss(self, entry_price: float, side: OrderSide) -> float:
        """Calculate initial stop-loss price.

        For buying options, SL is set at a percentage below entry.
        For selling options, SL is set at a percentage above entry.
        """
        sl_percent = self.max_loss_percent / 100.0
        if side == OrderSide.BUY:
            return round(entry_price * (1 - sl_percent * 3), 2)  # wider SL for buys
        else:
            return round(entry_price * (1 + sl_percent * 2), 2)

    def calculate_target(self, entry_price: float, side: OrderSide) -> float:
        """Calculate target price for profit booking."""
        target_pct = self.target_profit_percent / 100.0
        if side == OrderSide.BUY:
            return round(entry_price * (1 + target_pct * 5), 2)  # aim for 10% on premium
        else:
            return round(entry_price * (1 - target_pct * 3), 2)  # aim for decay

    def calculate_trailing_sl(
        self, entry_price: float, current_price: float, current_sl: float, side: OrderSide
    ) -> float:
        """Update trailing stop-loss based on favorable price movement."""
        trail_pct = self.trailing_sl_percent / 100.0

        if side == OrderSide.BUY:
            if current_price > entry_price:
                profit_pct = (current_price - entry_price) / entry_price
                if profit_pct > 0.03:  # once 3% profit, start trailing
                    new_sl = current_price * (1 - trail_pct)
                    return round(max(current_sl, new_sl), 2)
        else:
            if current_price < entry_price:
                profit_pct = (entry_price - current_price) / entry_price
                if profit_pct > 0.03:
                    new_sl = current_price * (1 + trail_pct)
                    return round(min(current_sl, new_sl) if current_sl > 0 else new_sl, 2)

        return current_sl

    def should_exit(
        self, position: Position, current_price: float
    ) -> tuple[bool, str]:
        """Check if position should be exited (SL or target hit)."""
        if position.side == OrderSide.BUY:
            # Check stop-loss
            if position.stop_loss > 0 and current_price <= position.stop_loss:
                return True, "stop_loss"
            # Check target
            if position.target > 0 and current_price >= position.target:
                return True, "target"
        else:
            # Short position
            if position.stop_loss > 0 and current_price >= position.stop_loss:
                return True, "stop_loss"
            if position.target > 0 and current_price <= position.target:
                return True, "target"

        return False, ""

    def update_daily_pnl(self, pnl: float, is_win: bool):
        """Update daily P&L tracking."""
        self.daily_pnl += pnl
        self.daily_trades += 1
        if is_win:
            self.daily_wins += 1
        else:
            self.daily_losses += 1

        # Check daily limits
        if self.daily_pnl <= -self.max_loss_amount:
            self._daily_loss_hit = True
            logger.warning("DAILY LOSS LIMIT HIT: %.2f (limit: %.2f)",
                           self.daily_pnl, -self.max_loss_amount)

        if self.daily_pnl >= self.target_profit_amount:
            self._daily_target_hit = True
            logger.info("DAILY TARGET REACHED: %.2f (target: %.2f)",
                         self.daily_pnl, self.target_profit_amount)

    def reset_daily(self):
        """Reset daily counters (call at start of each trading day)."""
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.daily_wins = 0
        self.daily_losses = 0
        self._daily_loss_hit = False
        self._daily_target_hit = False
        logger.info("Daily risk counters reset")

    def update_config(
        self,
        target_profit_percent: Optional[float] = None,
        max_loss_percent: Optional[float] = None,
        max_open_positions: Optional[int] = None,
        trailing_sl_percent: Optional[float] = None,
    ):
        """Update risk parameters."""
        if target_profit_percent is not None:
            self.target_profit_percent = target_profit_percent
        if max_loss_percent is not None:
            self.max_loss_percent = max_loss_percent
        if max_open_positions is not None:
            self.max_open_positions = max_open_positions
        if trailing_sl_percent is not None:
            self.trailing_sl_percent = trailing_sl_percent
        logger.info("Risk config updated: target=%.1f%%, maxloss=%.1f%%, maxpos=%d, trail=%.1f%%",
                     self.target_profit_percent, self.max_loss_percent,
                     self.max_open_positions, self.trailing_sl_percent)

    def get_stats(self) -> dict:
        """Get current risk/performance stats."""
        win_rate = (self.daily_wins / self.daily_trades * 100) if self.daily_trades > 0 else 0
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_trades": self.daily_trades,
            "daily_wins": self.daily_wins,
            "daily_losses": self.daily_losses,
            "win_rate": round(win_rate, 1),
            "daily_loss_hit": self._daily_loss_hit,
            "daily_target_hit": self._daily_target_hit,
            "max_loss_amount": round(self.max_loss_amount, 2),
            "target_profit_amount": round(self.target_profit_amount, 2),
        }
