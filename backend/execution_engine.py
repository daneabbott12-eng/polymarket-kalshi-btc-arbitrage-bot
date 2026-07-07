"""Execution engine for the arbitrage bot.

Two modes:
  - DRY_RUN (default): logs the orders it *would* place. No credentials, no funds,
    no orders. This is what runs unless you deliberately arm live trading.
  - LIVE: only reachable when BOTH of these are true:
        1. ARM_LIVE_TRADING is set truthy, AND
        2. real API credentials are present in the environment.
    Even then, the actual order submission is intentionally left unimplemented
    (raises NotImplementedError) so that arming can never send a malformed or
    accidental real order. You must deliberately wire the official signed clients
    yourself before any real money can move.

Nothing in this module places a real trade as shipped. It is scaffolding with
safety rails, not a live trading button.
"""
import os
import logging

log = logging.getLogger("execution")


def _env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name, default):
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


class SafetyError(Exception):
    """Raised when a live order would violate a configured safety limit."""


class ExecutionEngine:
    def __init__(self):
        self.arm_flag = _env_bool("ARM_LIVE_TRADING", False)
        # "dry_run" (default) or "testnet". LIVE is a separate, harder gate below.
        self.execution_mode = os.environ.get("EXECUTION_MODE", "dry_run").strip().lower()
        # Position / risk limits (apply to the TESTNET and LIVE paths).
        self.max_order_contracts = _env_float("ARB_MAX_ORDER_CONTRACTS", 50.0)
        self.max_open_positions = int(_env_float("ARB_MAX_OPEN_POSITIONS", 5))

        # Credentials are only read for a presence check; never logged.
        self._kalshi_key_id = os.environ.get("KALSHI_API_KEY_ID")
        self._kalshi_private_key = os.environ.get("KALSHI_PRIVATE_KEY")
        self._poly_api_key = os.environ.get("POLYMARKET_API_KEY")
        self._poly_secret = os.environ.get("POLYMARKET_SECRET")
        self._poly_passphrase = os.environ.get("POLYMARKET_PASSPHRASE")
        self._poly_wallet_key = os.environ.get("POLYMARKET_WALLET_PRIVATE_KEY")

        self._open_positions = 0
        self._order_seq = 0

    def has_credentials(self):
        kalshi_ok = bool(self._kalshi_key_id and self._kalshi_private_key)
        poly_ok = bool(self._poly_wallet_key)  # testnet needs at least a wallet key
        return kalshi_ok and poly_ok

    @property
    def armed(self):
        """Live (real-money) trading is armed ONLY with the flag AND credentials."""
        return self.arm_flag and self.has_credentials()

    @property
    def mode(self):
        if self.armed:
            return "LIVE"
        if self.execution_mode == "testnet" and self.has_credentials():
            return "TESTNET"
        return "DRY_RUN"

    def status(self):
        return {
            "mode": self.mode,
            "armed": self.armed,
            "arm_flag": self.arm_flag,
            "execution_mode": self.execution_mode,
            "has_credentials": self.has_credentials(),
            "max_order_contracts": self.max_order_contracts,
            "max_open_positions": self.max_open_positions,
            "open_positions": self._open_positions,
        }

    def build_plan(self, opp):
        """Turn a detected opportunity into a two-leg order plan (capped to limits)."""
        size = min(opp["size"], self.max_order_contracts)
        return {
            "size": size,
            "poly": {
                "leg": opp["poly_leg"],
                "size": size,
                "limit_price": round(opp["avg_poly_cost"], 4),
            },
            "kalshi": {
                "leg": opp["kalshi_leg"],
                "strike": opp["kalshi_strike"],
                "size": size,
                "limit_price": round(opp["avg_kalshi_cost"], 4),
            },
        }

    def handle(self, opp):
        """Handle a detected opportunity. DRY_RUN unless testnet/live is enabled."""
        plan = self.build_plan(opp)
        mode = self.mode

        if mode == "DRY_RUN":
            log.warning(
                "DRY_RUN would execute: P-%s x%.0f @ $%.3f  +  K-%s($%s) x%.0f @ $%.3f",
                plan["poly"]["leg"], plan["size"], plan["poly"]["limit_price"],
                plan["kalshi"]["leg"], plan["kalshi"]["strike"], plan["size"],
                plan["kalshi"]["limit_price"],
            )
            return {"mode": "DRY_RUN", "plan": plan, "placed": False}

        self._check_safety(plan["size"])

        if mode == "TESTNET":
            # Places REAL orders on demo/testnet (fake funds). Safe to run.
            result = self._place_testnet_orders(plan, opp)
            self._open_positions += 1
            return {"mode": "TESTNET", "plan": plan, "placed": True, "result": result}

        # ----- LIVE PATH (real money: armed + credentials present) -----
        # Both raise NotImplementedError until YOU wire the signed clients, so an
        # armed-but-unfinished setup fails safe instead of sending bad orders.
        self._place_polymarket_order(plan["poly"])
        self._place_kalshi_order(plan["kalshi"])
        self._open_positions += 1
        return {"mode": "LIVE", "plan": plan, "placed": True}

    # -- testnet execution (fake funds) -------------------------------------
    def _next_client_order_id(self, opp):
        self._order_seq += 1
        return f"arb-{opp.get('kalshi_strike')}-{opp.get('poly_leg')}-{self._order_seq}"

    def _place_testnet_orders(self, plan, opp):
        from clients.kalshi_client import KalshiDemoClient
        from clients.polymarket_client import PolymarketTestnetClient

        if not opp.get("kalshi_ticker"):
            raise SafetyError("Missing kalshi_ticker on opportunity; cannot place order.")
        if not opp.get("poly_token_id"):
            raise SafetyError("Missing poly_token_id on opportunity; cannot place order.")

        kalshi = KalshiDemoClient(self._kalshi_key_id, self._kalshi_private_key)
        poly = PolymarketTestnetClient(wallet_private_key=self._poly_wallet_key)

        kalshi_res = kalshi.place_limit_order(
            ticker=opp["kalshi_ticker"],
            side=plan["kalshi"]["leg"].lower(),   # 'yes' | 'no'
            action="buy",
            count=int(plan["size"]),
            price_cents=round(plan["kalshi"]["limit_price"] * 100),
            client_order_id=self._next_client_order_id(opp),
        )
        poly_res = poly.place_limit_order(
            token_id=opp["poly_token_id"],
            side="BUY",
            size=plan["size"],
            price=plan["poly"]["limit_price"],
        )
        return {"kalshi": kalshi_res, "polymarket": poly_res}

    def _check_safety(self, size):
        if size <= 0:
            raise SafetyError("Refusing order: non-positive size")
        if size > self.max_order_contracts:
            raise SafetyError(f"Refusing order: size {size} exceeds ARB_MAX_ORDER_CONTRACTS")
        if self._open_positions >= self.max_open_positions:
            raise SafetyError("Refusing order: ARB_MAX_OPEN_POSITIONS reached")

    def _place_kalshi_order(self, order):
        raise NotImplementedError(
            "LIVE Kalshi order not wired. Integrate the official Kalshi API client "
            "with RSA request signing (using KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY) "
            "and submit a limit order here. Left unimplemented on purpose so that "
            "arming live trading cannot send a malformed or accidental real order."
        )

    def _place_polymarket_order(self, order):
        raise NotImplementedError(
            "LIVE Polymarket order not wired. Integrate py-clob-client with your API "
            "credentials + wallet signer (EIP-712) and submit a limit order here. "
            "Left unimplemented on purpose so that arming live trading cannot send a "
            "malformed or accidental real order."
        )
