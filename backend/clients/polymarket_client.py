"""Polymarket CLOB TESTNET (Amoy) client scaffold -- no real-money path.

Wraps py-clob-client against the Amoy testnet (Polygon testnet, chain_id 80002).
It refuses to run against Polygon mainnet (137). Going live requires a separate,
deliberate implementation with its own review.

Requires:  pip install py-clob-client

Notes / caveats you must confirm before relying on this:
  - Polymarket's public liquidity is on mainnet; the Amoy testnet CLOB is for
    development and is typically empty. This scaffold gives you the correct call
    structure (auth, order construction, submit), not a liquid market to trade.
  - You need a funded Amoy test wallet (test USDC + test MATIC) and API creds
    derived from that wallet.
  - Confirm the current Amoy CLOB host in Polymarket's docs and pass it in; the
    default below is a placeholder that must be reviewed.
"""
AMOY_CHAIN_ID = 80002
POLYGON_MAINNET_CHAIN_ID = 137

# Placeholder -- confirm the current Amoy CLOB host in Polymarket's docs.
DEFAULT_TESTNET_HOST = "https://clob-testnet.polymarket.com"


class PolymarketTestnetClient:
    def __init__(self, *, wallet_private_key, host=DEFAULT_TESTNET_HOST,
                 chain_id=AMOY_CHAIN_ID, api_creds=None):
        if chain_id == POLYGON_MAINNET_CHAIN_ID:
            raise ValueError(
                "PolymarketTestnetClient is TESTNET-only; refusing Polygon mainnet "
                "(chain_id 137). Real-money trading must be implemented separately."
            )
        if not wallet_private_key:
            raise ValueError(
                "PolymarketTestnetClient needs POLYMARKET_WALLET_PRIVATE_KEY for a "
                "funded Amoy TEST wallet (test USDC/MATIC)."
            )
        self.host = host
        self.chain_id = chain_id
        self._wallet_private_key = wallet_private_key
        self._api_creds = api_creds
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from py_clob_client.client import ClobClient
        except ImportError as e:
            raise RuntimeError(
                "py-clob-client is not installed. Run: pip install py-clob-client"
            ) from e
        # Guard again in case host was overridden to a mainnet endpoint.
        if "polymarket.com" in self.host and "testnet" not in self.host and self.chain_id != AMOY_CHAIN_ID:
            raise ValueError("Refusing non-testnet host/chain combination.")
        self._client = ClobClient(
            self.host, key=self._wallet_private_key, chain_id=self.chain_id
        )
        # Derive/attach L2 API credentials for signed order posting.
        creds = self._api_creds or self._client.create_or_derive_api_creds()
        self._client.set_api_creds(creds)
        return self._client

    def place_limit_order(self, *, token_id, side, size, price):
        """Place a limit order on the Amoy TESTNET CLOB.

        side: 'BUY' | 'SELL'   size: shares   price: 0..1
        """
        client = self._get_client()  # raises a friendly error if lib/creds missing
        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.order_builder.constants import BUY, SELL
        order_args = OrderArgs(
            token_id=token_id,
            side=BUY if side.upper() == "BUY" else SELL,
            size=float(size),
            price=float(price),
        )
        signed = client.create_order(order_args)
        return client.post_order(signed)
