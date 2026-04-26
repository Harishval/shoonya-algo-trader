"""Paper trading simulator that mimics the Shoonya broker interface."""

import logging
import uuid
import random
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from app.config import settings
from app.models.schemas import (
    Trade, Position, OrderSide, OptionType, OrderStatus,
    MarketData, OptionData,
)

logger = logging.getLogger(__name__)

# Simulated base prices for indices (updated to approximate market levels)
SIMULATED_PRICES = {
    "NIFTY": 23900.0,
    "BANKNIFTY": 55200.0,
    "FINNIFTY": 23500.0,
    "SENSEX": 76660.0,
    "BANKEX": 55000.0,
}

STRIKE_GAP = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "SENSEX": 100,
    "BANKEX": 100,
}

LOT_SIZE = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "SENSEX": 10,
    "BANKEX": 15,
}


class PaperBroker:
    """Simulates broker operations for paper trading."""

    def __init__(self):
        self.is_logged_in = False
        self._positions: Dict[str, Position] = {}
        self._trades: List[Trade] = []
        self._order_counter = 0
        self._capital = settings.capital
        self._used_margin = 0.0
        self._simulated_prices = dict(SIMULATED_PRICES)
        self._tick_count = 0
        self._price_trends: Dict[str, float] = {}  # momentum for each instrument

    def login(self) -> bool:
        """Simulate login (always succeeds)."""
        self.is_logged_in = True
        logger.info("Paper trading mode: login simulated")
        return True

    def get_underlying_ltp(self, instrument: str) -> Optional[float]:
        """Get simulated LTP with realistic price movement."""
        base = self._simulated_prices.get(instrument)
        if base is None:
            return None

        self._tick_count += 1

        # Create trending price movement
        if instrument not in self._price_trends:
            self._price_trends[instrument] = 0.0

        # Occasionally change trend direction
        if random.random() < 0.1:
            self._price_trends[instrument] = random.uniform(-0.3, 0.3)

        trend = self._price_trends[instrument]
        noise = random.gauss(0, base * 0.0005)  # 0.05% noise
        movement = trend + noise

        new_price = base + movement
        self._simulated_prices[instrument] = new_price
        return round(new_price, 2)

    def get_atm_strike(self, instrument: str, ltp: float) -> float:
        """Calculate ATM strike."""
        gap = STRIKE_GAP.get(instrument, 50)
        return round(ltp / gap) * gap

    def get_option_chain(self, instrument: str, expiry: str) -> List[OptionData]:
        """Generate a simulated option chain."""
        ltp = self.get_underlying_ltp(instrument)
        if ltp is None:
            return []

        atm = self.get_atm_strike(instrument, ltp)
        gap = STRIKE_GAP.get(instrument, 50)
        chain = []

        for i in range(-10, 11):
            strike = atm + (i * gap)
            diff = abs(ltp - strike) / ltp

            # Simulate realistic option premiums
            base_premium = max(5, ltp * 0.01 * (1 - diff * 5))
            time_value = random.uniform(5, 30)

            if strike < ltp:
                ce_price = max(5, (ltp - strike) + time_value + random.uniform(-3, 3))
                pe_price = max(2, time_value * (1 + diff * 3) + random.uniform(-2, 2))
            elif strike > ltp:
                ce_price = max(2, time_value * (1 + diff * 3) + random.uniform(-2, 2))
                pe_price = max(5, (strike - ltp) + time_value + random.uniform(-3, 3))
            else:
                ce_price = max(10, base_premium + random.uniform(-5, 5))
                pe_price = max(10, base_premium + random.uniform(-5, 5))

            opt = OptionData(
                strike=strike,
                ce_ltp=round(ce_price, 2),
                pe_ltp=round(pe_price, 2),
                ce_oi=random.randint(10000, 500000),
                pe_oi=random.randint(10000, 500000),
                ce_volume=random.randint(1000, 100000),
                pe_volume=random.randint(1000, 100000),
                ce_iv=round(random.uniform(10, 30), 2),
                pe_iv=round(random.uniform(10, 30), 2),
                ce_delta=round(max(0.01, min(0.99, 0.5 - (i * 0.05))), 3),
                pe_delta=round(max(-0.99, min(-0.01, -0.5 - (i * -0.05))), 3),
            )
            chain.append(opt)

        return chain

    def get_option_quote(
        self, instrument: str, strike: float, option_type: str, expiry: str
    ) -> Optional[Dict]:
        """Get simulated quote for a specific option."""
        ltp = self.get_underlying_ltp(instrument)
        if ltp is None:
            return None

        diff = abs(ltp - strike) / ltp

        if option_type == "CE":
            if strike < ltp:
                price = max(5, (ltp - strike) + random.uniform(5, 25))
            else:
                price = max(2, 30 * (1 - diff * 5) + random.uniform(-3, 3))
        else:
            if strike > ltp:
                price = max(5, (strike - ltp) + random.uniform(5, 25))
            else:
                price = max(2, 30 * (1 - diff * 5) + random.uniform(-3, 3))

        price = round(price, 2)
        spread = max(0.05, price * 0.01)

        exchange = "NFO" if instrument in ("NIFTY", "BANKNIFTY", "FINNIFTY") else "BFO"
        tsym = f"{instrument}{expiry}{int(strike)}{option_type}"

        return {
            "tsym": tsym,
            "token": str(random.randint(100000, 999999)),
            "exchange": exchange,
            "ltp": price,
            "bid": round(price - spread, 2),
            "ask": round(price + spread, 2),
            "oi": random.randint(10000, 500000),
            "volume": random.randint(1000, 100000),
        }

    def place_order(
        self,
        instrument: str,
        symbol: str,
        exchange: str,
        side: OrderSide,
        quantity: int,
        price: float = 0,
        order_type: str = "MKT",
    ) -> Optional[str]:
        """Simulate order placement with instant fill."""
        self._order_counter += 1
        order_id = f"PAPER-{self._order_counter:06d}"

        # Simulate fill with slight slippage
        if price <= 0:
            # Market order: use a simulated price
            fill_price = abs(random.gauss(50, 15))
        else:
            slippage = price * random.uniform(-0.005, 0.005)
            fill_price = price + slippage

        fill_price = round(max(0.5, fill_price), 2)

        # Track position
        key = symbol
        if key in self._positions:
            pos = self._positions[key]
            if pos.side == side:
                # Adding to position
                total_qty = pos.quantity + quantity
                pos.avg_price = (pos.avg_price * pos.quantity + fill_price * quantity) / total_qty
                pos.quantity = total_qty
            else:
                # Closing or reducing position
                if quantity >= pos.quantity:
                    pnl = (fill_price - pos.avg_price) * pos.quantity
                    if pos.side == OrderSide.SELL:
                        pnl = -pnl
                    del self._positions[key]
                else:
                    pnl = (fill_price - pos.avg_price) * quantity
                    if pos.side == OrderSide.SELL:
                        pnl = -pnl
                    pos.quantity -= quantity
        else:
            # New position
            parts = symbol.replace(instrument, "", 1)
            opt_type = OptionType.CE if "CE" in parts else OptionType.PE
            strike_str = parts.rstrip("CEPE")
            # Extract just the digits for strike
            import re
            strike_match = re.search(r'(\d+)', parts)
            strike_val = float(strike_match.group(1)) if strike_match else 0

            self._positions[key] = Position(
                symbol=symbol,
                instrument=instrument,
                option_type=opt_type,
                strike=strike_val,
                side=side,
                quantity=quantity,
                avg_price=fill_price,
                ltp=fill_price,
            )

        logger.info("Paper order filled: %s %s qty=%d @ %.2f, order_id=%s",
                     side.value, symbol, quantity, fill_price, order_id)
        return order_id

    def get_positions(self) -> List[Dict]:
        """Get current paper positions."""
        positions = []
        for sym, pos in self._positions.items():
            # Simulate LTP movement
            movement = random.uniform(-0.05, 0.05) * pos.avg_price
            pos.ltp = round(max(0.5, pos.avg_price + movement), 2)

            if pos.side == OrderSide.BUY:
                pos.pnl = round((pos.ltp - pos.avg_price) * pos.quantity, 2)
            else:
                pos.pnl = round((pos.avg_price - pos.ltp) * pos.quantity, 2)

            positions.append({
                "tsym": pos.symbol,
                "netqty": str(pos.quantity if pos.side == OrderSide.BUY else -pos.quantity),
                "avgprc": str(pos.avg_price),
                "lp": str(pos.ltp),
                "rpnl": str(pos.pnl),
                "urmtom": str(pos.pnl),
            })
        return positions

    def get_order_book(self) -> List[Dict]:
        """Get paper order book."""
        return []

    def get_limits(self) -> Optional[Dict]:
        """Get simulated account limits."""
        total_pnl = sum(p.pnl for p in self._positions.values())
        return {
            "stat": "Ok",
            "cash": str(self._capital + total_pnl),
            "marginused": str(self._used_margin),
            "payin": str(self._capital),
        }

    def get_current_expiry(self, instrument: str) -> str:
        """Get nearest expiry date."""
        today = datetime.now()
        if instrument in ("SENSEX", "BANKEX"):
            target_day = 4  # Friday
        else:
            target_day = 3  # Thursday

        days_ahead = target_day - today.weekday()
        if days_ahead < 0:
            days_ahead += 7
        elif days_ahead == 0:
            if today.hour < 15 or (today.hour == 15 and today.minute <= 30):
                days_ahead = 0
            else:
                days_ahead = 7

        expiry_date = today + timedelta(days=days_ahead)
        return expiry_date.strftime("%d%b%Y").upper()

    def get_all_trades(self) -> List[Trade]:
        """Get all paper trades."""
        return self._trades

    def get_open_positions(self) -> List[Position]:
        """Get list of open positions."""
        return list(self._positions.values())

    def get_total_pnl(self) -> float:
        """Get total P&L across all positions."""
        return sum(p.pnl for p in self._positions.values())
