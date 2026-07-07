"""Shared RSA-PSS request signing for Kalshi API clients.

Kalshi signs each request with RSA-PSS(SHA-256) over the string
    <timestamp_ms> + <HTTP_METHOD> + <path>
using an API key id and RSA private key (PEM). Subclasses set HOST and expose
whatever endpoints they need. Requires the `cryptography` package.
"""
import base64
import json
import os
import time

import requests

PATH_PREFIX = "/trade-api/v2"


def resolve_pem(private_key_pem):
    """Accept either inline PEM text or a path to a .pem file."""
    if private_key_pem and "BEGIN" not in private_key_pem and os.path.isfile(private_key_pem):
        with open(private_key_pem) as f:
            return f.read()
    return private_key_pem


class KalshiSignedClient:
    HOST = None  # subclasses set this (demo vs production)

    def __init__(self, key_id, private_key_pem):
        if not key_id or not private_key_pem:
            raise ValueError(
                "Kalshi client needs an API key id and RSA private key "
                "(PEM text or a path to a .pem file)."
            )
        if not self.HOST:
            raise ValueError("Client subclass must set HOST.")
        self.key_id = key_id
        self._private_key_pem = resolve_pem(private_key_pem)

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
        url = self.HOST + PATH_PREFIX + endpoint
        headers = self._headers(method, sign_path)
        resp = requests.request(
            method, url, headers=headers,
            data=json.dumps(body) if body is not None else None, timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
