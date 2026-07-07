"""Kalshi DEMO (testnet) client -- fake money only.

Talks to https://demo-api.kalshi.co, Kalshi's demo environment, which uses paper
funds. The host is fixed; there is intentionally no way to point this at the
production API. Going live requires a separate, deliberate implementation.

Auth/signing is shared via clients/kalshi_base.py.
Reference: https://trading-api.readme.io/reference/api-keys
"""
from .kalshi_base import KalshiSignedClient


class KalshiDemoClient(KalshiSignedClient):
    # Fixed to the demo host on purpose (paper funds). Not configurable.
    HOST = "https://demo-api.kalshi.co"

    # -- reads --------------------------------------------------------------
    def get_exchange_status(self):
        return self._request("GET", "/exchange/status")

    def get_balance(self):
        return self._request("GET", "/portfolio/balance")

    def get_markets(self, limit=10, status="open", series_ticker=None):
        params = f"?limit={int(limit)}&status={status}"
        if series_ticker:
            params += f"&series_ticker={series_ticker}"
        return self._request("GET", "/markets" + params)

    # -- writes (demo/paper funds only) -------------------------------------
    def cancel_order(self, order_id):
        return self._request("DELETE", f"/portfolio/orders/{order_id}")

    def place_limit_order(self, *, ticker, side, action, count, price_cents, client_order_id):
        """Place a limit order on the DEMO exchange.

        side: 'yes' | 'no'   action: 'buy' | 'sell'   price_cents: 1..99
        """
        if side not in ("yes", "no"):
            raise ValueError("side must be 'yes' or 'no'")
        if action not in ("buy", "sell"):
            raise ValueError("action must be 'buy' or 'sell'")
        body = {
            "ticker": ticker,
            "client_order_id": client_order_id,
            "side": side,
            "action": action,
            "count": int(count),
            "type": "limit",
        }
        # Kalshi expects the price on the matching side, in cents.
        body["yes_price" if side == "yes" else "no_price"] = int(price_cents)
        return self._request("POST", "/portfolio/orders", body)
