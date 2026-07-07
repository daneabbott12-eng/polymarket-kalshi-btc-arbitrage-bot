from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fetch_current_polymarket import fetch_polymarket_data_struct
from fetch_current_kalshi import fetch_kalshi_data_struct
import datetime
import math

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
MIN_CONTRACTS = 1.0

# Trading fees. Polymarket charges no trading fee on CLOB fills. Kalshi charges a
# per-contract trading fee of ceil(0.07 * C * P * (1-P)) where P is the execution
# price in dollars -- largest near P=0.50, shrinking toward 0/1. Rate is a
# constant so it is easy to update if the published schedule changes.
# Ref: https://kalshi.com/docs/kalshi-fee-schedule.pdf
KALSHI_FEE_RATE = 0.07
POLYMARKET_FEE_RATE = 0.0

def kalshi_trading_fee(price, contracts=1.0):
    """Kalshi trading fee for `contracts` at execution `price` (dollars).

    Kalshi rounds the fee UP to the next cent per order, so even a single
    contract incurs at least $0.01 whenever the raw fee is > 0.
    """
    raw = KALSHI_FEE_RATE * contracts * price * (1.0 - price)
    return math.ceil(raw * 100.0) / 100.0

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

@app.get("/arbitrage")
def get_arbitrage_data():
    # Fetch Data
    poly_data, poly_err = fetch_polymarket_data_struct()
    kalshi_data, kalshi_err = fetch_kalshi_data_struct()
    
    response = {
        "timestamp": datetime.datetime.now().isoformat(),
        "polymarket": poly_data,
        "kalshi": kalshi_data,
        "checks": [],
        "opportunities": [],
        "errors": []
    }
    
    if poly_err:
        response["errors"].append(poly_err)
    if kalshi_err:
        response["errors"].append(kalshi_err)
        
    if not poly_data or not kalshi_data:
        return response

    # Logic
    poly_strike = poly_data['price_to_beat']
    poly_up_cost = poly_data['prices'].get('Up', 0.0)
    poly_down_cost = poly_data['prices'].get('Down', 0.0)

    # Depth (shares) available at the best ask on each Polymarket leg
    poly_sizes = poly_data.get('sizes', {})
    poly_up_size = poly_sizes.get('Up', 0.0)
    poly_down_size = poly_sizes.get('Down', 0.0)

    if poly_strike is None:
        response["errors"].append("Polymarket Strike is None")
        return response

    kalshi_markets = kalshi_data.get('markets', [])
    
    # Ensure sorted by strike
    kalshi_markets.sort(key=lambda x: x['strike'])
    
    # Find index closest to poly_strike
    closest_idx = 0
    min_diff = float('inf')
    for i, m in enumerate(kalshi_markets):
        diff = abs(m['strike'] - poly_strike)
        if diff < min_diff:
            min_diff = diff
            closest_idx = i
            
    # Select 4 below and 4 above (approx 8-9 markets total)
    # If closest is at index C, we want [C-4, C+5] roughly
    start_idx = max(0, closest_idx - 4)
    end_idx = min(len(kalshi_markets), closest_idx + 5) # +5 to include the closest and 4 above
    
    selected_markets = kalshi_markets[start_idx:end_idx]
    
    for km in selected_markets:
        kalshi_strike = km['strike']
        kalshi_yes_cost = km['yes_ask'] / 100.0
        kalshi_no_cost = km['no_ask'] / 100.0
        kalshi_yes_size = km.get('yes_ask_size', 0.0)
        kalshi_no_size = km.get('no_ask_size', 0.0)

        # Only check markets within range (removed previous hardcoded range check)

        check_data = {
            "kalshi_strike": kalshi_strike,
            "kalshi_yes": kalshi_yes_cost,
            "kalshi_no": kalshi_no_cost,
            "type": "",
            "poly_leg": "",
            "kalshi_leg": "",
            "poly_cost": 0,
            "kalshi_cost": 0,
            "total_cost": 0,
            "poly_size": 0,
            "kalshi_size": 0,
            "max_size": 0,
            "gross_margin": 0,
            "fees": 0,
            "net_margin": 0,
            "is_arbitrage": False,
            "margin": 0
        }

        def set_legs(check, poly_leg, kalshi_leg, poly_cost, kalshi_cost, poly_size, kalshi_size):
            check["poly_leg"] = poly_leg
            check["kalshi_leg"] = kalshi_leg
            check["poly_cost"] = poly_cost
            check["kalshi_cost"] = kalshi_cost
            check["total_cost"] = poly_cost + kalshi_cost
            check["poly_size"] = poly_size
            check["kalshi_size"] = kalshi_size
            # Executable depth is limited by the smaller of the two legs
            check["max_size"] = min(poly_size, kalshi_size)

        if poly_strike > kalshi_strike:
            check_data["type"] = "Poly > Kalshi"
            set_legs(check_data, "Down", "Yes", poly_down_cost, kalshi_yes_cost, poly_down_size, kalshi_yes_size)

        elif poly_strike < kalshi_strike:
            check_data["type"] = "Poly < Kalshi"
            set_legs(check_data, "Up", "No", poly_up_cost, kalshi_no_cost, poly_up_size, kalshi_no_size)

        elif poly_strike == kalshi_strike:
            # Check 1
            check1 = check_data.copy()
            check1["type"] = "Equal"
            set_legs(check1, "Down", "Yes", poly_down_cost, kalshi_yes_cost, poly_down_size, kalshi_yes_size)

            if evaluate_check(check1):
                response["opportunities"].append(check1)
            response["checks"].append(check1)

            # Check 2
            check2 = check_data.copy()
            check2["type"] = "Equal"
            set_legs(check2, "Up", "No", poly_up_cost, kalshi_no_cost, poly_up_size, kalshi_no_size)

            if evaluate_check(check2):
                response["opportunities"].append(check2)
            response["checks"].append(check2)
            continue # Skip adding the base check_data

        if evaluate_check(check_data):
            response["opportunities"].append(check_data)

        response["checks"].append(check_data)
        
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
