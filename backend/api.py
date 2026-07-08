from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fetch_current_polymarket import fetch_polymarket_data_struct
from fetch_current_kalshi import fetch_kalshi_data_struct, get_orderbook_ask_ladders
from paper_trader import PaperTrader
from execution_engine import ExecutionEngine
from clients.kalshi_readonly_client import KalshiReadOnlyClient
from assets import ASSETS
import datetime
import math
import os
import time
from load_env import load_dotenv

load_dotenv()  # pull backend/.env into the environment before reading config

def _env_float(name, default):
    """Read a float from the environment, falling back to `default` if unset or
    unparseable. Lets the model be tuned without editing code (see .env.example)."""
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default

app = FastAPI()

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Minimum executable depth (contracts/shares fillable on BOTH legs) before we
# call something a real opportunity. A book can show a tempting ask with only a
# sliver of size behind it; below this floor the "arbitrage" isn't worth acting
# on and is usually just noise.
MIN_CONTRACTS = _env_float("ARB_MIN_CONTRACTS", 1.0)

# Trading fees. Polymarket charges no trading fee on CLOB fills. Kalshi charges a
# per-contract trading fee of ceil(0.07 * C * P * (1-P)) where P is the execution
# price in dollars -- largest near P=0.50, shrinking toward 0/1. Rate is a
# constant so it is easy to update if the published schedule changes.
# Ref: https://kalshi.com/docs/kalshi-fee-schedule.pdf
KALSHI_FEE_RATE = _env_float("ARB_KALSHI_FEE_RATE", 0.07)
POLYMARKET_FEE_RATE = _env_float("ARB_POLYMARKET_FEE_RATE", 0.0)

def kalshi_trading_fee(price, contracts=1.0):
    """Kalshi trading fee for `contracts` at execution `price` (dollars).

    Kalshi rounds the fee UP to the next cent per order, so even a single
    contract incurs at least $0.01 whenever the raw fee is > 0.
    """
    raw = KALSHI_FEE_RATE * contracts * price * (1.0 - price)
    return math.ceil(raw * 100.0) / 100.0

# Target trade size (contracts) for the realistic-fill analysis. The best ask is
# only the top of the book; filling a real order walks deeper and worse levels,
# so the average price -- and the true margin -- degrades with size. Used as the
# fixed default when no live balance is connected.
TARGET_CONTRACTS = _env_float("ARB_TARGET_CONTRACTS", 100.0)

# When a live balance IS connected, scale the target with buying power: deploy up
# to this fraction of available capital per opportunity (an arb pair costs ~$1 to
# enter). So the target grows as the account grows, up to a hard ceiling.
CAPITAL_FRACTION = _env_float("ARB_CAPITAL_FRACTION", 0.02)
MAX_TARGET_CONTRACTS = _env_float("ARB_MAX_TARGET_CONTRACTS", 1000.0)
EST_COST_PER_CONTRACT = 1.0  # $1 payoff pair; conservative sizing estimate

def compute_target_contracts(real_balance, committed):
    """Target contracts to size an opportunity for.

    Fixed default when no balance is connected; otherwise scales with available
    buying power (balance minus open commitments), clamped to [MIN, MAX]."""
    if real_balance is None:
        return TARGET_CONTRACTS
    available = max(0.0, real_balance - committed)
    scaled = available * CAPITAL_FRACTION / EST_COST_PER_CONTRACT
    return max(MIN_CONTRACTS, min(scaled, MAX_TARGET_CONTRACTS))

# Execution-risk model (slippage + leg risk). The order-book walk gives the price
# you would get if the book stood still and both legs filled instantly. Reality:
#  - SLIPPAGE_PER_LEG: the book moves between seeing a price and getting filled,
#    so you give up a little on each leg.
#  - LEG_FILL_PROBABILITY: the two legs are placed separately; sometimes only one
#    fills before the other moves or vanishes.
#  - LEG_RISK_LOSS: if a leg is left naked, you unwind it at a loss (spread +
#    adverse move) of roughly this much per contract.
# All tunable; defaults are deliberately conservative for a fast hourly market.
SLIPPAGE_PER_LEG = _env_float("ARB_SLIPPAGE_PER_LEG", 0.005)       # $ per leg (~0.5 cent)
LEG_FILL_PROBABILITY = _env_float("ARB_LEG_FILL_PROBABILITY", 0.90) # chance both legs fill
LEG_RISK_LOSS = _env_float("ARB_LEG_RISK_LOSS", 0.05)              # $ lost per naked leg

# "Fat edge" filter: only record/act on opportunities whose net-after-slippage
# margin is at least this ($/contract). Thin edges aren't worth the execution
# risk. Set to 0 to take every risk-adjusted-positive edge.
MIN_MARGIN = _env_float("ARB_MIN_MARGIN", 0.02)

def walk_book(ask_ladder, target_size):
    """Walk an ascending ask ladder to fill `target_size`.

    Returns (avg_price, filled_size, total_cost). If the book is thinner than
    the target, fills what it can and reports the smaller filled_size.
    """
    filled = 0.0
    cost = 0.0
    for price, size in ask_ladder:
        if filled >= target_size:
            break
        take = min(size, target_size - filled)
        filled += take
        cost += take * price
    avg_price = (cost / filled) if filled > 0 else 0.0
    return avg_price, filled, cost

def execution_at_size(poly_ladder, kalshi_ladder, target_size):
    """Compute the realistic paired fill for two ask ladders at a target size.

    You can only pair as many contracts as BOTH legs can fill, so the executable
    size is the smaller of the two. Prices are the volume-weighted average to
    fill that common size, and fees are charged on the Kalshi leg at its VWAP.
    """
    _, poly_fillable, _ = walk_book(poly_ladder, target_size)
    _, kalshi_fillable, _ = walk_book(kalshi_ladder, target_size)
    fill_size = min(poly_fillable, kalshi_fillable)

    if fill_size <= 0:
        return None

    avg_poly, _, _ = walk_book(poly_ladder, fill_size)
    avg_kalshi, _, _ = walk_book(kalshi_ladder, fill_size)
    total_cost = avg_poly + avg_kalshi
    fee_per_contract = kalshi_trading_fee(avg_kalshi) if avg_kalshi > 0 else 0.0
    net_margin = 1.0 - total_cost - fee_per_contract   # after fees, ideal fill

    # Layer in execution risk: slippage on each leg, then a probability-weighted
    # expectation that accounts for the chance the pair fails to complete.
    total_slippage = 2.0 * SLIPPAGE_PER_LEG
    net_margin_slipped = net_margin - total_slippage   # after fees + slippage
    risk_adj_net_margin = (
        LEG_FILL_PROBABILITY * net_margin_slipped
        - (1.0 - LEG_FILL_PROBABILITY) * LEG_RISK_LOSS
    )

    return {
        "target_size": target_size,
        "fill_size": fill_size,
        "avg_poly_cost": avg_poly,
        "avg_kalshi_cost": avg_kalshi,
        "total_cost_at_size": total_cost,
        "fee_per_contract": fee_per_contract,
        "net_margin_at_size": net_margin,               # per contract, after fees only
        "slippage_per_leg": SLIPPAGE_PER_LEG,
        "total_slippage": total_slippage,
        "net_margin_slipped": net_margin_slipped,       # after fees + slippage
        "fill_probability": LEG_FILL_PROBABILITY,
        "risk_adj_net_margin": risk_adj_net_margin,     # expected, after leg risk
        "total_net_pnl": net_margin * fill_size,        # ideal, over fillable size
        "total_net_pnl_slipped": net_margin_slipped * fill_size,
        "risk_adj_net_pnl": risk_adj_net_margin * fill_size,
        # A real edge must survive fees, slippage, AND the leg-risk haircut, with
        # enough depth. Gating on risk_adj (not just net-after-slippage) skips
        # thin edges that are positive on paper but losers once you weight in the
        # chance a leg hangs -- those aren't worth taking at any size.
        "is_arbitrage_at_size": risk_adj_net_margin > 0.0 and fill_size >= MIN_CONTRACTS,
    }

def evaluate_check(check):
    """Decide whether a check is a real, executable arbitrage opportunity.

    All conditions must hold:
    1. Both legs have a real, non-zero ask -- a leg priced at 0 means there is NO
       ask on that side of the book (no liquidity), not a free buy.
    2. There is enough depth to actually fill both legs (>= MIN_CONTRACTS). The
       executable size is the smaller of the two legs' available depth.
    3. The margin is still positive AFTER trading fees. Gross margin is
       (1.00 - total_cost); fees are charged on each leg. A trade that clears
       $1.00 gross can easily be a loser once Kalshi's fee is paid.
    """
    poly_cost = check["poly_cost"]
    kalshi_cost = check["kalshi_cost"]
    both_legs_tradeable = poly_cost > 0.0 and kalshi_cost > 0.0
    has_depth = check.get("max_size", 0.0) >= MIN_CONTRACTS

    # Per-contract economics (Kalshi fee on its leg; Polymarket leg is fee-free).
    gross_margin = 1.00 - check["total_cost"]
    kalshi_fee = kalshi_trading_fee(kalshi_cost) if kalshi_cost > 0.0 else 0.0
    poly_fee = POLYMARKET_FEE_RATE * poly_cost
    fees = kalshi_fee + poly_fee
    net_margin = gross_margin - fees

    check["gross_margin"] = gross_margin
    check["fees"] = fees
    check["net_margin"] = net_margin
    # `margin` now reflects the fee-adjusted (net) profit per contract.
    check["margin"] = net_margin

    if both_legs_tradeable and has_depth and net_margin > 0.0:
        check["is_arbitrage"] = True
    return check["is_arbitrage"]

# Single shared paper-trading ledger for the process.
PT = PaperTrader()
# Execution engine (DRY_RUN unless explicitly armed with credentials).
ENGINE = ExecutionEngine()

def compute_asset_checks(asset_name, poly_data, kalshi_data):
    """Best-ask arbitrage checks for one asset. Returns a list of tagged checks
    (no side effects); the caller aggregates across assets."""
    poly_strike = poly_data.get('price_to_beat')
    if poly_strike is None:
        return []
    poly_prices = poly_data.get('prices', {})
    poly_up_cost = poly_prices.get('Up', 0.0)
    poly_down_cost = poly_prices.get('Down', 0.0)
    poly_sizes = poly_data.get('sizes', {})
    poly_up_size = poly_sizes.get('Up', 0.0)
    poly_down_size = poly_sizes.get('Down', 0.0)
    poly_token_ids = poly_data.get('token_ids', {})

    kalshi_markets = sorted(kalshi_data.get('markets', []), key=lambda x: x['strike'])
    if not kalshi_markets:
        return []

    # Select the ~9 markets closest to the poly strike (price to beat).
    closest_idx = min(range(len(kalshi_markets)),
                      key=lambda i: abs(kalshi_markets[i]['strike'] - poly_strike))
    selected = kalshi_markets[max(0, closest_idx - 4):closest_idx + 5]

    def new_check(km):
        return {
            "asset": asset_name,
            "kalshi_strike": km['strike'],
            "kalshi_yes": km['yes_ask'] / 100.0,
            "kalshi_no": km['no_ask'] / 100.0,
            "type": "", "poly_leg": "", "kalshi_leg": "",
            "poly_cost": 0, "kalshi_cost": 0, "total_cost": 0,
            "poly_size": 0, "kalshi_size": 0, "max_size": 0,
            "gross_margin": 0, "fees": 0, "net_margin": 0,
            "is_arbitrage": False, "margin": 0,
            "execution": None, "paper_trade_recorded": False,
            "kalshi_ticker": km.get("ticker"), "poly_token_id": None,
        }

    def set_legs(check, poly_leg, kalshi_leg, poly_cost, kalshi_cost, poly_size, kalshi_size):
        check["poly_leg"] = poly_leg
        check["kalshi_leg"] = kalshi_leg
        check["poly_cost"] = poly_cost
        check["kalshi_cost"] = kalshi_cost
        check["total_cost"] = poly_cost + kalshi_cost
        check["poly_size"] = poly_size
        check["kalshi_size"] = kalshi_size
        check["poly_token_id"] = poly_token_ids.get(poly_leg)
        check["max_size"] = min(poly_size, kalshi_size)

    checks = []
    for km in selected:
        ks = km['strike']
        kyc = km['yes_ask'] / 100.0
        knc = km['no_ask'] / 100.0
        kys = km.get('yes_ask_size', 0.0)
        kns = km.get('no_ask_size', 0.0)
        if poly_strike > ks:
            c = new_check(km); c["type"] = "Poly > Kalshi"
            set_legs(c, "Down", "Yes", poly_down_cost, kyc, poly_down_size, kys)
            evaluate_check(c); checks.append(c)
        elif poly_strike < ks:
            c = new_check(km); c["type"] = "Poly < Kalshi"
            set_legs(c, "Up", "No", poly_up_cost, knc, poly_up_size, kns)
            evaluate_check(c); checks.append(c)
        else:
            c1 = new_check(km); c1["type"] = "Equal"
            set_legs(c1, "Down", "Yes", poly_down_cost, kyc, poly_down_size, kys)
            evaluate_check(c1); checks.append(c1)
            c2 = new_check(km); c2["type"] = "Equal"
            set_legs(c2, "Up", "No", poly_up_cost, knc, poly_up_size, kns)
            evaluate_check(c2); checks.append(c2)
    return checks

@app.get("/arbitrage")
def get_arbitrage_data():
    response = {
        "timestamp": datetime.datetime.now().isoformat(),
        "polymarket": None,
        "kalshi": None,
        "checks": [],
        "opportunities": [],
        "errors": [],
        "assets": [],
    }

    # Fetch + compute per asset (each independent; one asset failing is skipped).
    poly_books_by_asset = {}
    window = None
    settle_time = None
    for asset in ASSETS:
        name = asset["name"]
        poly_data, poly_err = fetch_polymarket_data_struct(
            asset["poly"], asset["kalshi"], asset["kraken"], asset["binance"])
        kalshi_data, kalshi_err = fetch_kalshi_data_struct(
            asset["poly"], asset["kalshi"], asset["kraken"], asset["binance"])
        if poly_err:
            response["errors"].append(f"{name} poly: {poly_err}")
        if kalshi_err:
            response["errors"].append(f"{name} kalshi: {kalshi_err}")
        if not poly_data or not kalshi_data or poly_data.get("price_to_beat") is None:
            continue

        response["checks"].extend(compute_asset_checks(name, poly_data, kalshi_data))
        poly_books_by_asset[name] = poly_data.get("books", {})
        response["assets"].append(name)

        # First successful asset provides the market-card data + the hourly window
        # (all assets share the same target hour for dedup/settlement).
        if response["polymarket"] is None:
            response["polymarket"] = poly_data
            response["kalshi"] = kalshi_data
            target = poly_data["target_time_utc"]
            if isinstance(target, str):
                target = datetime.datetime.fromisoformat(target)
            window = target.isoformat()
            settle_time = (target + datetime.timedelta(hours=1)).isoformat()

    response["opportunities"] = [c for c in response["checks"] if c["is_arbitrage"]]
    if window is None:
        return response  # nothing fetched this poll

    # Realistic at-size execution: walk the order books for the most competitive
    # tradeable markets ACROSS ALL ASSETS (lowest combined best-ask cost). Capped
    # at a few markets to bound API calls. If a live account is connected, cap
    # paper sizes to available balance (real balance - open commitments).
    real_balance = get_real_balance_dollars()
    target_contracts = compute_target_contracts(real_balance, PT.committed_capital())

    tradeable = [c for c in response["checks"] if c["poly_cost"] > 0 and c["kalshi_cost"] > 0]
    tradeable.sort(key=lambda c: c["total_cost"])
    for check in tradeable[:6]:
        ticker = check.get("kalshi_ticker")
        if not ticker:
            continue
        ladders, _ = get_orderbook_ask_ladders(ticker)
        kalshi_ladder = ladders["yes"] if check["kalshi_leg"] == "Yes" else ladders["no"]
        poly_ladder = poly_books_by_asset.get(check["asset"], {}).get(check["poly_leg"], [])
        execu = execution_at_size(poly_ladder, kalshi_ladder, target_contracts)
        if not execu:
            continue
        check["execution"] = execu
        # Fat-edge + risk-adjusted gate: only act on edges >= MIN_MARGIN that are
        # also positive after the leg-risk haircut.
        if not execu["is_arbitrage_at_size"] or execu["net_margin_slipped"] < MIN_MARGIN:
            continue

        cost_per_contract = (execu["avg_poly_cost"] + execu["avg_kalshi_cost"]
                             + execu["total_slippage"] + execu["fee_per_contract"])
        size, capped = cap_size_to_budget(
            execu["fill_size"], cost_per_contract, real_balance, PT.committed_capital()
        )
        execu["capped_by_balance"] = capped
        if size < MIN_CONTRACTS:
            continue  # can't afford even one contract right now

        trade = PT.record(
            window=f"{check['asset']}:{window}", settle_time=settle_time,
            kalshi_strike=check["kalshi_strike"],
            poly_leg=check["poly_leg"], kalshi_leg=check["kalshi_leg"],
            size=size,
            avg_poly_cost=execu["avg_poly_cost"],
            avg_kalshi_cost=execu["avg_kalshi_cost"],
            fee_per_contract=execu["fee_per_contract"],
            slippage_per_leg=execu["slippage_per_leg"],
            risk_adj_net_per_contract=execu["risk_adj_net_margin"],
            timestamp=response["timestamp"],
        )
        check["paper_trade_recorded"] = trade is not None

    # Settle any paper trades whose hour has passed, and attach a summary.
    PT.settle_due(datetime.datetime.now(datetime.timezone.utc))
    summary = PT.summary()
    if real_balance is not None:
        summary["real_balance"] = round(real_balance, 2)
        summary["committed_capital"] = round(PT.committed_capital(), 2)
        summary["available_capital"] = round(real_balance - PT.committed_capital(), 2)
    response["paper"] = summary

    return response

@app.get("/paper/trades")
def get_paper_trades():
    return {"trades": PT.trades, "summary": PT.summary()}

@app.get("/paper/summary")
def get_paper_summary():
    return PT.summary()

@app.post("/paper/reset")
def reset_paper_trades():
    PT.reset()
    return {"status": "ok", "summary": PT.summary()}

@app.get("/auto/status")
def auto_status():
    """Execution mode for the auto-runner: DRY_RUN unless live trading is armed."""
    return ENGINE.status()

def _get_kalshi_readonly():
    """Build a read-only production client from KALSHI_PROD_* creds, or None."""
    kid = os.environ.get("KALSHI_PROD_API_KEY_ID")
    pem = os.environ.get("KALSHI_PROD_PRIVATE_KEY")
    if not kid or not pem:
        return None
    return KalshiReadOnlyClient(kid, pem)

# Cache the real balance so the 1s /arbitrage polling doesn't hammer production.
_balance_cache = {"value": None, "ts": 0.0}
BALANCE_TTL_SECONDS = 30.0

def cap_size_to_budget(fill_size, cost_per_contract, real_balance, committed):
    """Cap a fill size to what the real balance can afford after open positions.

    Returns (size, capped). If no balance is known, returns the size unchanged.
    """
    if real_balance is None or cost_per_contract <= 0:
        return fill_size, False
    available = max(0.0, real_balance - committed)
    affordable = available / cost_per_contract
    size = min(fill_size, affordable)
    return size, size < fill_size

def get_real_balance_dollars():
    """Real Kalshi balance in dollars (cached), or None if no prod account."""
    client = _get_kalshi_readonly()
    if client is None:
        return None
    now = time.time()
    if _balance_cache["value"] is not None and now - _balance_cache["ts"] < BALANCE_TTL_SECONDS:
        return _balance_cache["value"]
    try:
        bal = client.get_balance()
        cents = bal.get("balance") if isinstance(bal, dict) else None
        value = cents / 100.0 if isinstance(cents, (int, float)) else None
        _balance_cache["value"] = value
        _balance_cache["ts"] = now
        return value
    except Exception:
        return _balance_cache["value"]  # fall back to last known good

@app.get("/account/kalshi")
def kalshi_account():
    """Read-only view of your LIVE Kalshi account (balance + open positions).

    Uses the KalshiReadOnlyClient, which has no order methods -- this endpoint
    cannot place or cancel anything. Returns {connected: false} if no prod creds.
    """
    client = _get_kalshi_readonly()
    if client is None:
        return {"connected": False, "reason": "No KALSHI_PROD_* credentials configured."}
    try:
        bal = client.get_balance()
        cents = bal.get("balance") if isinstance(bal, dict) else None
        pos = client.get_positions()
        positions = pos.get("market_positions", []) if isinstance(pos, dict) else []
        held = [p for p in positions if p.get("position")]
        return {
            "connected": True,
            "read_only": True,
            "balance_dollars": round(cents / 100.0, 2) if isinstance(cents, (int, float)) else None,
            "positions": held[:50],
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}

@app.post("/paper/simulate")
def simulate_paper_trade():
    """Record one illustrative paper trade for testing the ledger + settlement,
    since genuine live arbitrage is rare. Clearly tagged as SIMULATED; settles a
    few seconds out so the next poll flips it to 'settled'."""
    now = datetime.datetime.now(datetime.timezone.utc)
    # Model the same slippage + leg-risk the live path uses, so the demo trade is
    # realistic. Gross here is 1 - (0.41+0.55) - 0.02 fee = 0.02/contract.
    net_slipped = 1.0 - (0.41 + 0.55) - 0.02 - 2.0 * SLIPPAGE_PER_LEG
    risk_adj = LEG_FILL_PROBABILITY * net_slipped - (1.0 - LEG_FILL_PROBABILITY) * LEG_RISK_LOSS
    trade = PT.record(
        window="SIMULATED-" + now.isoformat(),
        settle_time=(now + datetime.timedelta(seconds=5)).isoformat(),
        kalshi_strike=63000, poly_leg="Up", kalshi_leg="No", size=75,
        avg_poly_cost=0.41, avg_kalshi_cost=0.55, fee_per_contract=0.02,
        slippage_per_leg=SLIPPAGE_PER_LEG, risk_adj_net_per_contract=risk_adj,
        timestamp=now.isoformat(),
    )
    return {"status": "ok", "trade": trade, "summary": PT.summary()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
