"""Autonomous opportunity runner.

Continuously polls the arbitrage API, and for each newly-detected opportunity
that survives depth + fees + slippage (execution.is_arbitrage_at_size), it:
  1. Logs an alert (console + opportunities.log), and
  2. Hands it to the ExecutionEngine -- which DRY-RUNS by default and only places
     real orders if you have explicitly armed live trading with credentials.

Run headless (no dashboard needed):
    python auto_runner.py

Environment:
    ARB_API_BASE        base URL of the running backend (default http://localhost:8000)
    AUTO_POLL_SECONDS   poll interval in seconds (default 3)
    ARM_LIVE_TRADING    see execution_engine.py -- leave unset for safe DRY_RUN
"""
import os
import time
import json
import logging
import datetime
import urllib.request

from execution_engine import ExecutionEngine
from load_env import load_dotenv

load_dotenv()  # pull backend/.env into the environment before reading config

API_BASE = os.environ.get("ARB_API_BASE", "http://localhost:8000").rstrip("/")
POLL_SECONDS = float(os.environ.get("AUTO_POLL_SECONDS", "3"))
OPP_LOG_PATH = os.path.join(os.path.dirname(__file__), "opportunities.log")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("auto")


def fetch_arbitrage():
    with urllib.request.urlopen(f"{API_BASE}/arbitrage", timeout=20) as resp:
        return json.load(resp)


def actionable_opportunities(data):
    """Checks that survive the full model (depth + fees + slippage)."""
    out = []
    poly = data.get("polymarket") or {}
    window = poly.get("target_time_utc", "?")
    for c in data.get("checks", []):
        e = c.get("execution")
        if e and e.get("is_arbitrage_at_size"):
            out.append({
                "asset": c.get("asset", "?"),
                "window": window,
                "poly_leg": c["poly_leg"],
                "kalshi_leg": c["kalshi_leg"],
                "kalshi_strike": c["kalshi_strike"],
                "kalshi_ticker": c.get("kalshi_ticker"),
                "poly_token_id": c.get("poly_token_id"),
                "size": e["fill_size"],
                "avg_poly_cost": e["avg_poly_cost"],
                "avg_kalshi_cost": e["avg_kalshi_cost"],
                "net_margin_slipped": e["net_margin_slipped"],
                "risk_adj_net_margin": e["risk_adj_net_margin"],
                "total_net_pnl_slipped": e["total_net_pnl_slipped"],
            })
    return out


def alert(opp):
    msg = (
        f"OPPORTUNITY {opp['asset']} {opp['window']} | P-{opp['poly_leg']} + "
        f"K-{opp['kalshi_leg']}(${opp['kalshi_strike']:,.4f}) x{opp['size']:.0f} | "
        f"net(after slip) ${opp['net_margin_slipped']:+.4f}/ct  "
        f"risk-adj ${opp['risk_adj_net_margin']:+.4f}/ct  "
        f"est P&L ${opp['total_net_pnl_slipped']:+.2f}"
    )
    log.info(msg)
    with open(OPP_LOG_PATH, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat()} {msg}\n")


def main():
    engine = ExecutionEngine()
    status = engine.status()
    log.info("Auto-runner starting | mode=%s | poll=%.1fs | api=%s",
             status["mode"], POLL_SECONDS, API_BASE)
    if status["mode"] == "LIVE":
        log.warning("LIVE TRADING ARMED — real orders may be placed.")
    else:
        log.info("DRY_RUN — detections are logged only; no orders placed.")

    seen = set()
    while True:
        try:
            data = fetch_arbitrage()
            if data.get("errors"):
                log.debug("api errors: %s", data["errors"])
            for opp in actionable_opportunities(data):
                key = f"{opp['asset']}|{opp['window']}|{opp['kalshi_strike']}|{opp['poly_leg']}|{opp['kalshi_leg']}"
                if key in seen:
                    continue
                seen.add(key)
                alert(opp)
                result = engine.handle(opp)
                log.info("  -> %s (placed=%s)", result["mode"], result["placed"])
        except Exception as ex:  # keep the loop alive through transient errors
            log.warning("poll failed: %s", ex)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
