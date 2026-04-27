#!/usr/bin/env python3
"""Entry point to start the Shoonya Algo Trader."""

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from app.config import settings


def main():
    print("""
    ╔═══════════════════════════════════════════╗
    ║        SHOONYA ALGO TRADER v1.0           ║
    ║   Directional OTM Options Trading Bot     ║
    ╠═══════════════════════════════════════════╣
    ║  Mode     : {mode:<30s}║
    ║  Capital  : ₹{capital:<29s}║
    ║  Target   : {target}% daily{tpad}║
    ║  Max Loss : {loss}% daily{lpad}║
    ║  Instruments: {inst:<27s}║
    ╠═══════════════════════════════════════════╣
    ║  Dashboard: http://{host}:{port:<19}║
    ╚═══════════════════════════════════════════╝
    """.format(
        mode=settings.trading_mode.upper(),
        capital=f"{settings.capital:,.0f}",
        target=settings.target_profit_percent,
        tpad=" " * (24 - len(str(settings.target_profit_percent))),
        loss=settings.max_loss_percent,
        lpad=" " * (24 - len(str(settings.max_loss_percent))),
        inst=settings.instruments,
        host="localhost" if settings.host == "0.0.0.0" else settings.host,
        port=settings.port,
    ))

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
