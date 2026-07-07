"""Kalshi PRODUCTION read-only client.

Talks to the LIVE Kalshi API (real account), but exposes ONLY read (GET)
endpoints -- balance and positions. There is deliberately no order-placement or
cancel method on this class, so connecting your real account here cannot place,
modify, or cancel any order. It is a viewer, not a trader.

Use your production API credentials (KALSHI_PROD_API_KEY_ID /
KALSHI_PROD_PRIVATE_KEY). These are kept separate from the demo trading
credentials so they never reach any order-placing code path.
"""
from .kalshi_base import KalshiSignedClient


class KalshiReadOnlyClient(KalshiSignedClient):
    HOST = "https://api.elections.kalshi.com"

    def get_balance(self):
        return self._request("GET", "/portfolio/balance")

    def get_positions(self, limit=100):
        return self._request("GET", f"/portfolio/positions?limit={int(limit)}")

    # No place_limit_order / cancel_order here, on purpose.
