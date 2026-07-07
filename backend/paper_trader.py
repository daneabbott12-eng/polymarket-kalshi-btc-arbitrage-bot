"""Paper-trading ledger for simulated arbitrage fills.

Records simulated trades when a real, depth- and fee-validated opportunity is
detected, persists them to a JSON ledger, and settles them once the market's
hour has passed. No real orders are placed and no funds move -- this is purely
for testing the bot's decisions and tracking hypothetical P&L.

Each pair of opposing legs is constructed to return exactly $1.00 per contract
at resolution (that is the arbitrage thesis), so a trade entered for a positive
net margin has a deterministic expected profit of net_margin * size.
"""
import json
import os
import datetime

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "paper_trades.json")


def _parse_iso(ts):
    return datetime.datetime.fromisoformat(ts)


class PaperTrader:
    def __init__(self, path=LEDGER_PATH):
        self.path = path
        self.trades = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self.trades, f, indent=2)

    def _has_key(self, key):
        return any(t["key"] == key for t in self.trades)

    def record(self, *, window, settle_time, kalshi_strike, poly_leg, kalshi_leg,
               size, avg_poly_cost, avg_kalshi_cost, fee_per_contract, timestamp,
               slippage_per_leg=0.0, risk_adj_net_per_contract=None):
        """Record one simulated fill. Deduped by (window, strike, legs) so a
        persistent opportunity is only entered once per hourly market.

        Slippage is added to each leg's cost, so the net margin and cost basis are
        the realistic (post-slippage) figures. `risk_adj_net_per_contract`, if
        given, is the leg-risk-adjusted expectation and is tracked alongside."""
        key = f"{window}|{kalshi_strike}|{poly_leg}|{kalshi_leg}"
        if self._has_key(key):
            return None

        total_slippage = 2.0 * slippage_per_leg
        total_cost = avg_poly_cost + avg_kalshi_cost + total_slippage
        net_per_contract = 1.0 - total_cost - fee_per_contract
        cost_basis = (total_cost + fee_per_contract) * size

        if risk_adj_net_per_contract is None:
            risk_adj_net_per_contract = net_per_contract

        trade = {
            "key": key,
            "timestamp": timestamp,
            "window": window,             # the hourly market this belongs to
            "settle_time": settle_time,   # when it resolves (UTC ISO)
            "kalshi_strike": kalshi_strike,
            "poly_leg": poly_leg,
            "kalshi_leg": kalshi_leg,
            "size": round(size, 2),
            "avg_poly_cost": round(avg_poly_cost, 4),
            "avg_kalshi_cost": round(avg_kalshi_cost, 4),
            "slippage_per_leg": round(slippage_per_leg, 4),
            "fee_per_contract": round(fee_per_contract, 4),
            "cost_basis": round(cost_basis, 2),
            "net_margin_per_contract": round(net_per_contract, 4),
            "expected_net_pnl": round(net_per_contract * size, 2),
            "risk_adj_net_per_contract": round(risk_adj_net_per_contract, 4),
            "risk_adj_net_pnl": round(risk_adj_net_per_contract * size, 2),
            "status": "open",
            "realized_pnl": None,
        }
        self.trades.append(trade)
        self._save()
        return trade

    def settle_due(self, now_utc):
        """Mark open trades settled once their hour has passed. Because each
        trade is a guaranteed-$1 pair, realized P&L equals the expected P&L."""
        changed = False
        for t in self.trades:
            if t["status"] == "open" and now_utc >= _parse_iso(t["settle_time"]):
                t["status"] = "settled"
                t["realized_pnl"] = t["expected_net_pnl"]
                changed = True
        if changed:
            self._save()

    def summary(self):
        settled = [t for t in self.trades if t["status"] == "settled"]
        open_t = [t for t in self.trades if t["status"] == "open"]
        return {
            "total_trades": len(self.trades),
            "open": len(open_t),
            "settled": len(settled),
            "total_invested": round(sum(t["cost_basis"] for t in self.trades), 2),
            "expected_net_pnl": round(sum(t["expected_net_pnl"] for t in self.trades), 2),
            "risk_adj_net_pnl": round(sum(t.get("risk_adj_net_pnl", t["expected_net_pnl"]) for t in self.trades), 2),
            "realized_net_pnl": round(sum((t["realized_pnl"] or 0.0) for t in settled), 2),
        }

    def reset(self):
        self.trades = []
        self._save()
