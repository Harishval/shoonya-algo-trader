"""Shoonya (Finvasia) broker integration using NorenRestApiPy."""

import logging
import pyotp
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from NorenRestApiPy.NorenApi import NorenApi

from app.config import settings
from app.models.schemas import (
    Trade, Position, OrderSide, OptionType, OrderStatus, MarketData, OptionData,
)

logger = logging.getLogger(__name__)

# Shoonya API endpoint
SHOONYA_HOST = "https://api.shoonya.com/NorenWClientTP/"

# Exchange mappings
EXCHANGE_MAP = {
    "NIFTY": "NFO",
    "BANKNIFTY": "NFO",
    "FINNIFTY": "NFO",
    "SENSEX": "BFO",
    "BANKEX": "BFO",
}

UNDERLYING_EXCHANGE = {
    "NIFTY": "NSE",
    "BANKNIFTY": "NSE",
    "FINNIFTY": "NSE",
    "SENSEX": "BSE",
    "BANKEX": "BSE",
}

UNDERLYING_TOKEN = {
    "NIFTY": "26000",
    "BANKNIFTY": "26009",
    "FINNIFTY": "26037",
    "SENSEX": "1",
    "BANKEX": "12",
}

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


class ShoonyaClient(NorenApi):
    """Custom Shoonya API client."""

    def __init__(self):
        super().__init__(
            host=SHOONYA_HOST,
            websocket="wss://api.shoonya.com/NorenWSTP/",
        )


class ShoonyaBroker:
    """Wrapper around Shoonya API for options trading."""

    def __init__(self):
        self.api = ShoonyaClient()
        self.is_logged_in = False
        self._ws_connected = False
        self._market_data: Dict[str, MarketData] = {}
        self._callbacks: Dict[str, Any] = {}

    def login(self) -> bool:
        """Login to Shoonya using TOTP."""
        try:
            totp = pyotp.TOTP(settings.shoonya_totp_secret)
            otp = totp.now()

            ret = self.api.login(
                userid=settings.shoonya_user_id,
                password=settings.shoonya_password,
                twoFA=otp,
                vendor_code=settings.shoonya_vendor_code,
                api_secret=settings.shoonya_api_secret,
                imei=settings.shoonya_imei,
            )

            if ret is not None and ret.get("stat") == "Ok":
                self.is_logged_in = True
                logger.info("Shoonya login successful for user %s", settings.shoonya_user_id)
                return True
            else:
                error_msg = ret.get("emsg", "Unknown error") if ret else "No response"
                logger.error("Shoonya login failed: %s", error_msg)
                return False
        except Exception as e:
            logger.error("Shoonya login exception: %s", e)
            return False

    def get_underlying_ltp(self, instrument: str) -> Optional[float]:
        """Get the last traded price of the underlying index."""
        try:
            exchange = UNDERLYING_EXCHANGE.get(instrument, "NSE")
            token = UNDERLYING_TOKEN.get(instrument)
            if not token:
                return None

            ret = self.api.get_quotes(exchange=exchange, token=token)
            if ret and ret.get("stat") == "Ok":
                return float(ret.get("lp", 0))
            return None
        except Exception as e:
            logger.error("Error fetching LTP for %s: %s", instrument, e)
            return None

    def get_atm_strike(self, instrument: str, ltp: float) -> float:
        """Calculate the ATM strike from LTP."""
        gap = STRIKE_GAP.get(instrument, 50)
        return round(ltp / gap) * gap

    def get_option_chain(self, instrument: str, expiry: str) -> List[OptionData]:
        """Fetch the option chain for an instrument."""
        try:
            exchange = EXCHANGE_MAP.get(instrument, "NFO")
            ltp = self.get_underlying_ltp(instrument)
            if ltp is None:
                return []

            atm = self.get_atm_strike(instrument, ltp)
            gap = STRIKE_GAP.get(instrument, 50)
            strikes_range = 10

            chain = []
            for i in range(-strikes_range, strikes_range + 1):
                strike = atm + (i * gap)
                opt = OptionData(strike=strike)

                for opt_type in ["CE", "PE"]:
                    tsym = self._build_option_symbol(instrument, strike, opt_type, expiry)
                    if tsym:
                        ret = self.api.searchscrip(exchange=exchange, searchtext=tsym)
                        if ret and isinstance(ret, list) and len(ret) > 0:
                            token = ret[0].get("token")
                            quote = self.api.get_quotes(exchange=exchange, token=token)
                            if quote and quote.get("stat") == "Ok":
                                price = float(quote.get("lp", 0))
                                oi = int(quote.get("oi", 0))
                                vol = int(quote.get("v", 0))
                                if opt_type == "CE":
                                    opt.ce_ltp = price
                                    opt.ce_oi = oi
                                    opt.ce_volume = vol
                                else:
                                    opt.pe_ltp = price
                                    opt.pe_oi = oi
                                    opt.pe_volume = vol
                chain.append(opt)

            return chain
        except Exception as e:
            logger.error("Error fetching option chain for %s: %s", instrument, e)
            return []

    def get_option_quote(
        self, instrument: str, strike: float, option_type: str, expiry: str
    ) -> Optional[Dict]:
        """Get quote for a specific option contract."""
        try:
            exchange = EXCHANGE_MAP.get(instrument, "NFO")
            tsym = self._build_option_symbol(instrument, strike, option_type, expiry)
            if not tsym:
                return None

            ret = self.api.searchscrip(exchange=exchange, searchtext=tsym)
            if ret and isinstance(ret, list) and len(ret) > 0:
                token = ret[0].get("token")
                tsym_actual = ret[0].get("tsym")
                quote = self.api.get_quotes(exchange=exchange, token=token)
                if quote and quote.get("stat") == "Ok":
                    return {
                        "tsym": tsym_actual,
                        "token": token,
                        "exchange": exchange,
                        "ltp": float(quote.get("lp", 0)),
                        "bid": float(quote.get("bp1", 0)),
                        "ask": float(quote.get("sp1", 0)),
                        "oi": int(quote.get("oi", 0)),
                        "volume": int(quote.get("v", 0)),
                    }
            return None
        except Exception as e:
            logger.error("Error getting option quote: %s", e)
            return None

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
        """Place an order via Shoonya."""
        try:
            buy_or_sell = "B" if side == OrderSide.BUY else "S"
            prd_type = "M"  # NRML for options

            ret = self.api.place_order(
                buy_or_sell=buy_or_sell,
                product_type=prd_type,
                exchange=exchange,
                tradingsymbol=symbol,
                quantity=quantity,
                discloseqty=0,
                price_type=order_type,
                price=price,
                trigger_price=None,
                retention="DAY",
                remarks="algo_trade",
            )

            if ret and ret.get("stat") == "Ok":
                order_id = ret.get("norenordno")
                logger.info("Order placed: %s %s %s qty=%d, order_id=%s",
                            buy_or_sell, symbol, order_type, quantity, order_id)
                return order_id
            else:
                error = ret.get("emsg", "Unknown") if ret else "No response"
                logger.error("Order failed: %s", error)
                return None
        except Exception as e:
            logger.error("Order placement exception: %s", e)
            return None

    def get_positions(self) -> List[Dict]:
        """Get current positions."""
        try:
            ret = self.api.get_positions()
            if ret and isinstance(ret, list):
                return ret
            return []
        except Exception as e:
            logger.error("Error fetching positions: %s", e)
            return []

    def get_order_book(self) -> List[Dict]:
        """Get order book."""
        try:
            ret = self.api.get_order_book()
            if ret and isinstance(ret, list):
                return ret
            return []
        except Exception as e:
            logger.error("Error fetching order book: %s", e)
            return []

    def get_limits(self) -> Optional[Dict]:
        """Get account limits/margins."""
        try:
            ret = self.api.get_limits()
            if ret and ret.get("stat") == "Ok":
                return ret
            return None
        except Exception as e:
            logger.error("Error fetching limits: %s", e)
            return None

    def get_current_expiry(self, instrument: str) -> str:
        """Get the nearest weekly expiry date string.

        Returns the date formatted as used by Shoonya symbol naming
        (e.g., '24APR2025' for NFO, '25424' for BFO compact).
        For simplicity we return 'DDMMMYYYY' format.
        """
        today = datetime.now()
        # Find next Thursday (weekday 3) for NSE, Friday for BSE
        if instrument in ("SENSEX", "BANKEX"):
            target_day = 4  # Friday
        else:
            target_day = 3  # Thursday

        days_ahead = target_day - today.weekday()
        if days_ahead < 0:
            days_ahead += 7
        elif days_ahead == 0:
            # If today is expiry day and market is still open, use today
            if today.hour < 15 or (today.hour == 15 and today.minute <= 30):
                days_ahead = 0
            else:
                days_ahead = 7

        expiry_date = today + timedelta(days=days_ahead)
        return expiry_date.strftime("%d%b%Y").upper()

    def _build_option_symbol(
        self, instrument: str, strike: float, option_type: str, expiry: str
    ) -> Optional[str]:
        """Build the trading symbol for an option contract.

        Shoonya symbols vary by exchange. We use searchscrip to confirm.
        """
        strike_str = str(int(strike))
        return f"{instrument}{expiry}{strike_str}{option_type}"

    def start_websocket(self, on_tick=None, on_order=None):
        """Start WebSocket connection for live data."""
        try:
            def _on_open():
                logger.info("WebSocket connected")
                self._ws_connected = True

            def _on_close():
                logger.info("WebSocket disconnected")
                self._ws_connected = False

            def _on_error(error):
                logger.error("WebSocket error: %s", error)

            ret = self.api.start_websocket(
                order_update_callback=on_order or (lambda msg: None),
                subscribe_callback=on_tick or (lambda msg: None),
                socket_open_callback=_on_open,
                socket_close_callback=_on_close,
                socket_error_callback=_on_error,
            )
            return ret
        except Exception as e:
            logger.error("WebSocket start error: %s", e)
            return None

    def subscribe(self, exchange: str, token: str):
        """Subscribe to a token for live data."""
        try:
            self.api.subscribe(f"{exchange}|{token}")
        except Exception as e:
            logger.error("Subscribe error: %s", e)

    def unsubscribe(self, exchange: str, token: str):
        """Unsubscribe from a token."""
        try:
            self.api.unsubscribe(f"{exchange}|{token}")
        except Exception as e:
            logger.error("Unsubscribe error: %s", e)
