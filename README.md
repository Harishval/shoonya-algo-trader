# Shoonya Algo Trader

An AI-powered algorithmic trading system for Indian stock market options (Nifty & Sensex) using the **Shoonya (Finvasia)** broker API.

## Features

- **Directional OTM Options Trading** — Buys Out-of-The-Money Calls/Puts based on real-time price action signals
- **Multi-Indicator Signal Engine** — Uses EMA crossover, momentum, and breakout detection for trade entries
- **Automatic Risk Management** — Stop-loss, trailing stop-loss, target profit, and daily loss limits
- **Paper Trading Mode** — Full simulation with realistic price movements for risk-free testing
- **Live Trading Mode** — Direct integration with Shoonya broker via API
- **Real-Time Dashboard** — Beautiful web UI with live P&L chart, option chain, positions, and trade history
- **WebSocket Updates** — Sub-second dashboard updates via WebSocket
- **Configurable Strategy** — Adjust target %, loss %, OTM offset, instruments, and more from the dashboard

## Strategy Overview

The bot implements a **directional OTM options buying** strategy:

1. **Signal Detection**: Monitors Nifty/Sensex price action using:
   - Short-term EMA (5) vs Long-term EMA (15) crossover
   - Price momentum over recent ticks
   - Breakout detection (new highs/lows)

2. **Entry**: When 2+ indicators align:
   - **Bullish Signal** → Buy OTM Call options
   - **Bearish Signal** → Buy OTM Put options

3. **Exit**: Automatic exits via:
   - **Target Hit** → Book profit at configured target %
   - **Stop-Loss Hit** → Cut losses at configured SL %
   - **Trailing Stop-Loss** → Lock in profits as price moves favorably

4. **Risk Controls**:
   - Daily P&L limits (both profit target and max loss)
   - Maximum concurrent positions
   - Per-trade capital limits (max 10% of capital per trade)

## Quick Start

### Prerequisites
- Python 3.9+
- Shoonya trading account (for live trading)

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd shoonya-algo-trader

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### Configuration

```bash
# Copy the example environment file
cp .env.example .env
```

Edit `.env` with your settings:

```env
# For paper trading (no credentials needed)
TRADING_MODE=paper
CAPITAL=100000
TARGET_PROFIT_PERCENT=2.0
MAX_LOSS_PERCENT=1.0
INSTRUMENTS=NIFTY,SENSEX

# For live trading (fill in your Shoonya credentials)
SHOONYA_USER_ID=your_user_id
SHOONYA_PASSWORD=your_password
SHOONYA_TOTP_SECRET=your_totp_secret
SHOONYA_VENDOR_CODE=your_vendor_code
SHOONYA_API_SECRET=your_api_secret
```

### Run

```bash
python run.py
```

Open your browser at **http://localhost:8000** to access the dashboard.

## Dashboard

The web dashboard provides:

| Section | Description |
|---------|-------------|
| **Controls** | Start/Stop/Pause strategy, Exit all positions |
| **Performance** | Daily P&L, win rate, trade counts, capital |
| **Market Signals** | Real-time Nifty/Sensex LTP with signal indicators |
| **P&L Chart** | Live profit/loss chart over time |
| **Active Positions** | Current open trades with SL/target levels |
| **Option Chain** | Real-time option chain for selected instrument |
| **Trade History** | Completed trades with entry/exit prices and P&L |
| **Configuration** | Adjust all strategy parameters on the fly |
| **Activity Log** | Real-time log of all system events |

### Paper vs Live Trading

Toggle between **Paper** and **Live** mode directly from the dashboard header:

- **Paper Mode**: Uses simulated prices — perfect for testing strategies risk-free
- **Live Mode**: Connects to Shoonya API — trades with real money ⚠️

## Getting Shoonya API Credentials

1. Open a trading account at [shoonya.com](https://shoonya.com)
2. Navigate to **API** section in your account settings
3. Generate your **API Key** (api_secret) and note your **Vendor Code**
4. Set up TOTP:
   - Enable 2FA on your Shoonya account
   - Save the TOTP secret key (used for `SHOONYA_TOTP_SECRET`)

## Project Structure

```
shoonya-algo-trader/
├── app/
│   ├── main.py              # FastAPI server + WebSocket
│   ├── config.py            # Environment-based configuration
│   ├── broker/
│   │   ├── shoonya_broker.py  # Shoonya API integration
│   │   └── paper_broker.py    # Paper trading simulator
│   ├── strategy/
│   │   ├── otm_strategy.py    # Directional OTM strategy engine
│   │   └── risk_manager.py    # Risk management & limits
│   ├── models/
│   │   └── schemas.py         # Pydantic data models
│   └── dashboard/
│       └── index.html         # Web dashboard UI
├── run.py                   # Application entry point
├── requirements.txt         # Python dependencies
├── .env.example             # Example configuration
└── README.md
```

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_MODE` | `paper` | `paper` for simulation, `live` for real trading |
| `CAPITAL` | `100000` | Trading capital in INR |
| `TARGET_PROFIT_PERCENT` | `2.0` | Daily profit target (%) |
| `MAX_LOSS_PERCENT` | `1.0` | Daily maximum loss limit (%) |
| `MAX_OPEN_POSITIONS` | `4` | Maximum concurrent trades |
| `OTM_STRIKE_OFFSET` | `2` | Number of strikes away from ATM |
| `INSTRUMENTS` | `NIFTY,SENSEX` | Comma-separated instrument list |

## Risk Disclaimer

⚠️ **This software is for educational purposes only.** Options trading involves substantial risk of loss. Past performance does not guarantee future results. Always paper trade first and understand the risks before using live money.

## License

MIT
