"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Shoonya API credentials
    shoonya_user_id: str = ""
    shoonya_password: str = ""
    shoonya_totp_secret: str = ""
    shoonya_vendor_code: str = ""
    shoonya_api_secret: str = ""
    shoonya_imei: str = "abc1234"

    # Trading configuration
    trading_mode: str = "paper"  # "paper" or "live"
    capital: float = 100000.0
    max_loss_percent: float = 1.0
    target_profit_percent: float = 2.0
    max_open_positions: int = 4
    otm_strike_offset: int = 2  # number of strikes away from ATM

    # Instruments
    instruments: str = "NIFTY,SENSEX"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def instrument_list(self) -> List[str]:
        return [i.strip() for i in self.instruments.split(",")]

    @property
    def max_loss_amount(self) -> float:
        return self.capital * (self.max_loss_percent / 100.0)

    @property
    def target_profit_amount(self) -> float:
        return self.capital * (self.target_profit_percent / 100.0)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
