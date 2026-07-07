"""Kalshi DEMO (testnet) client -- fake money only.

Talks to https://demo-api.kalshi.co, Kalshi's demo environment, which uses paper
funds. The host is fixed; there is intentionally no way to point this at the
production API. Going live requires a separate, deliberate implementation.

Auth: each request is signed with RSA-PSS(SHA-256) over the string
    <timestamp_ms> + <HTTP_METHOD> + <path>
using your demo API key id and RSA private key (PEM). Get both from the Kalshi
demo dashboard (Account -> API Keys). Requires the `cryptography` package.

Reference: https://trading-api.readme.io/reference/api-keys
"""
import base64
import json
import os
import time

import requests

# Fixed to the demo host on purpose (paper funds). Not configurable.
DEMO_HOST = "https://demo-api.kalshi.co"
PATH_PREFIX = "/trade-api/v2"


class KalshiDemoClient:
    def __init__(self, key_id, private_key_pem):
        if not key_id or not private_key_pem:
            raise ValueError(
                "KalshiDemoClient needs KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY "
                "(RSA private key in PEM form, or a path to a .pem file) from the "
                "Kalshi DEMO dashboard."
            )
        self.key_id = key_id
        # Accept either inline PEM or a path to a .pem file.
        if "BEGIN" not in private_key_pem and os.path.isfile(private_key_pem):
            with open(private_key_pem) as f:
                private_key_pem = f.read()
        self._private_key_pem = private_key_pem

    # -- signing ------------------------------------------------------------
    def _load_key(self):
        from cryptography.hazmat.primitives import serialization
        return serialization.load_pem_private_key(
            self._private_key_pem.encode(), password=None
        )

    def _sign(self, timestamp_ms, method, path):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        message = f"{timestamp_ms}{method}{path}".encode()
        signature = self._load_key().sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode()

    def _headers(self, method, sign_path):
        ts = str(int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": self._sign(ts, method, sign_path),
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }

    def _request(self, method, endpoint, body=None):
        # `endpoint` is relative to PATH_PREFIX, e.g. "/portfolio/balance" or
        # "/markets?limit=10". Kalshi signs the PATH ONLY (no query string).
        path_only = endpoint.split("?", 1)[0]
        sign_path = PATH_PREFIX + path_only
        url = DEMO_HOST + PATH_PREFIX + endpoint
        headers = self._headers(method, sign_path)
        resp = requests.request(
            method, url, headers=headers,
            data=json.dumps(body) if body is not None else None, timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    # -- api ----------------------------------------------------------------
    def get_exchange_status(self):
        return self._request("GET", "/exchange/status")

    def get_balance(self):
        return self._request("GET", "/portfolio/balance")

    def get_markets(self, limit=10, status="open", series_ticker=None):
        params = f"?limit={int(limit)}&status={status}"
        if series_ticker:
            params += f"&series_ticker={series_ticker}"
        return self._request("GET", "/markets" + params)

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
