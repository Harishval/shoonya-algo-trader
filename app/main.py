"""FastAPI application — API endpoints and WebSocket for the trading dashboard."""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings
from app.models.schemas import (
    TradingMode, StrategyState, StrategyConfig, DashboardData,
)
from app.strategy.risk_manager import RiskManager
from app.strategy.otm_strategy import DirectionalOTMStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Global state
broker = None
strategy = None
risk_manager = None
ws_clients: List[WebSocket] = []
_strategy_task = None


def init_broker():
    """Initialize the appropriate broker based on trading mode."""
    global broker, strategy, risk_manager

    if settings.trading_mode == "live":
        from app.broker.shoonya_broker import ShoonyaBroker
        broker = ShoonyaBroker()
        success = broker.login()
        if not success:
            logger.error("Live broker login failed — falling back to paper mode")
            from app.broker.paper_broker import PaperBroker
            broker = PaperBroker()
            broker.login()
    else:
        from app.broker.paper_broker import PaperBroker
        broker = PaperBroker()
        broker.login()

    risk_manager = RiskManager()
    strategy = DirectionalOTMStrategy(broker, risk_manager)
    logger.info("Broker initialized in %s mode", settings.trading_mode)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — start/stop background tasks."""
    init_broker()
    yield
    # Cleanup
    global _strategy_task
    if _strategy_task and not _strategy_task.done():
        _strategy_task.cancel()


app = FastAPI(title="Shoonya Algo Trader", version="1.0.0", lifespan=lifespan)


# ---------- WebSocket ----------

async def broadcast(data: dict):
    """Send data to all connected WebSocket clients."""
    dead = []
    message = json.dumps(data, default=str)
    for ws in ws_clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.remove(ws)


async def strategy_loop():
    """Background loop that ticks the strategy and broadcasts state."""
    while True:
        try:
            if strategy:
                if strategy.state == StrategyState.RUNNING:
                    state = strategy.tick()
                else:
                    state = strategy._get_state()

                # Build dashboard data
                market_data = {}
                option_chains = {}
                for inst in strategy.config.instruments:
                    ltp = broker.get_underlying_ltp(inst)
                    if ltp:
                        market_data[inst] = {"ltp": ltp, "instrument": inst}

                    expiry = broker.get_current_expiry(inst)
                    chain = broker.get_option_chain(inst, expiry)
                    if chain:
                        option_chains[inst] = [c.model_dump() for c in chain[:15]]

                dashboard = {
                    "type": "dashboard_update",
                    "timestamp": datetime.now().isoformat(),
                    "trading_mode": settings.trading_mode,
                    "strategy": state,
                    "market_data": market_data,
                    "option_chains": option_chains,
                    "risk": risk_manager.get_stats() if risk_manager else {},
                    "capital": settings.capital,
                }
                await broadcast(dashboard)

            await asyncio.sleep(2)  # tick every 2 seconds
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Strategy loop error: %s", e)
            await asyncio.sleep(5)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket endpoint for real-time dashboard updates."""
    await ws.accept()
    ws_clients.append(ws)
    logger.info("WebSocket client connected (total: %d)", len(ws_clients))

    global _strategy_task
    if _strategy_task is None or _strategy_task.done():
        _strategy_task = asyncio.create_task(strategy_loop())

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            await handle_ws_message(msg, ws)
    except WebSocketDisconnect:
        ws_clients.remove(ws)
        logger.info("WebSocket client disconnected (total: %d)", len(ws_clients))
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        if ws in ws_clients:
            ws_clients.remove(ws)


async def handle_ws_message(msg: dict, ws: WebSocket):
    """Handle commands from the dashboard."""
    action = msg.get("action")

    if action == "start":
        strategy.start()
        await ws.send_text(json.dumps({"type": "status", "message": "Strategy started"}))

    elif action == "stop":
        strategy.stop()
        await ws.send_text(json.dumps({"type": "status", "message": "Strategy stopped"}))

    elif action == "pause":
        strategy.pause()
        await ws.send_text(json.dumps({"type": "status", "message": "Strategy paused"}))

    elif action == "resume":
        strategy.resume()
        await ws.send_text(json.dumps({"type": "status", "message": "Strategy resumed"}))

    elif action == "exit_all":
        strategy.force_exit_all()
        await ws.send_text(json.dumps({"type": "status", "message": "All positions exited"}))

    elif action == "update_config":
        config_data = msg.get("config", {})
        new_config = StrategyConfig(**config_data)
        strategy.update_config(new_config)
        await ws.send_text(json.dumps({"type": "status", "message": "Config updated"}))

    elif action == "switch_mode":
        mode = msg.get("mode", "paper")
        settings.trading_mode = mode
        init_broker()
        await ws.send_text(json.dumps({
            "type": "status",
            "message": f"Switched to {mode} mode",
        }))

    elif action == "get_state":
        state = strategy._get_state() if strategy else {}
        await ws.send_text(json.dumps({
            "type": "state",
            "data": state,
        }, default=str))


# ---------- REST Endpoints ----------

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the dashboard."""
    dashboard_path = Path(__file__).parent / "dashboard" / "index.html"
    return FileResponse(dashboard_path)


@app.get("/api/status")
async def get_status():
    """Get current system status."""
    return {
        "trading_mode": settings.trading_mode,
        "strategy_state": strategy.state.value if strategy else "IDLE",
        "broker_connected": broker.is_logged_in if broker else False,
        "capital": settings.capital,
        "instruments": settings.instrument_list,
        "risk": risk_manager.get_stats() if risk_manager else {},
    }


class ConfigUpdate(BaseModel):
    target_profit_percent: float = 2.0
    max_loss_percent: float = 1.0
    otm_strike_offset: int = 2
    max_open_positions: int = 4
    trailing_sl_percent: float = 0.5
    instruments: List[str] = ["NIFTY", "SENSEX"]


@app.post("/api/config")
async def update_config(config: ConfigUpdate):
    """Update strategy configuration."""
    new_config = StrategyConfig(**config.model_dump())
    strategy.update_config(new_config)
    return {"status": "ok", "config": config.model_dump()}


@app.get("/api/trades")
async def get_trades():
    """Get trade history."""
    if strategy is None:
        return {"trades": []}
    state = strategy._get_state()
    return {
        "active": state.get("active_trades", []),
        "closed": state.get("closed_trades", []),
    }


@app.get("/api/option-chain/{instrument}")
async def get_option_chain(instrument: str):
    """Get option chain for an instrument."""
    if broker is None:
        return {"chain": []}
    expiry = broker.get_current_expiry(instrument.upper())
    chain = broker.get_option_chain(instrument.upper(), expiry)
    return {
        "instrument": instrument.upper(),
        "expiry": expiry,
        "chain": [c.model_dump() for c in chain],
    }
