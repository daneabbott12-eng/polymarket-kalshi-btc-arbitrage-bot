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
        # Position / risk limits (apply to the LIVE path).
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

    def has_credentials(self):
        kalshi_ok = bool(self._kalshi_key_id and self._kalshi_private_key)
        poly_ok = bool(
            self._poly_api_key and self._poly_secret
            and self._poly_passphrase and self._poly_wallet_key
        )
        return kalshi_ok and poly_ok

    @property
    def armed(self):
        """Live trading is armed ONLY with both the explicit flag and credentials."""
        return self.arm_flag and self.has_credentials()

    def status(self):
        return {
            "mode": "LIVE" if self.armed else "DRY_RUN",
            "armed": self.armed,
            "arm_flag": self.arm_flag,
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
        """Handle a detected opportunity. Dry-run unless explicitly armed."""
        plan = self.build_plan(opp)

        if not self.armed:
            log.warning(
                "DRY_RUN would execute: P-%s x%.0f @ $%.3f  +  K-%s($%s) x%.0f @ $%.3f",
                plan["poly"]["leg"], plan["size"], plan["poly"]["limit_price"],
                plan["kalshi"]["leg"], plan["kalshi"]["strike"], plan["size"],
                plan["kalshi"]["limit_price"],
            )
            return {"mode": "DRY_RUN", "plan": plan, "placed": False}

        # ----- LIVE PATH (armed + credentials present) -----
        self._check_safety(plan["size"])
        # Both raise NotImplementedError until YOU wire the signed clients, so an
        # armed-but-unfinished setup fails safe instead of sending bad orders.
        self._place_polymarket_order(plan["poly"])
        self._place_kalshi_order(plan["kalshi"])
        self._open_positions += 1
        return {"mode": "LIVE", "plan": plan, "placed": True}

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
