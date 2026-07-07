"""Smoke test for the Polymarket TESTNET (Amoy) client.

Validates, as far as each layer allows, that you can talk to the Amoy testnet
CLOB with your test wallet. TESTNET only - fake funds. No real money is ever
involved (the client refuses Polygon mainnet).

IMPORTANT CAVEATS (read these):
  - Requires `pip install py-clob-client`.
  - The Amoy CLOB host in clients/polymarket_client.py is a PLACEHOLDER you must
    confirm against Polymarket's current docs; if it is wrong, the health/auth
    checks will fail on connection.
  - Amoy testnet typically has little or no liquidity, so a paired arbitrage
    fill is not realistic there - this validates auth + order plumbing, not a
    tradeable market.

Usage:
    # Checks: wallet key format, lib, address, CLOB health, API-cred derivation
    python smoke_test_polymarket.py

    # Also place a far-from-market test order on a token, then cancel it:
    python smoke_test_polymarket.py --place-test-order --token-id <TOKEN_ID>

Credentials via environment or backend/.env:
    POLYMARKET_WALLET_PRIVATE_KEY   private key of a funded Amoy TEST wallet
"""
import os
import re
import sys
import argparse

from clients.polymarket_client import PolymarketTestnetClient

OK = "[OK]"
BAD = "[FAIL]"
WARN = "[!]"


def _load_dotenv():
    path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def check_key_format(key):
    """Sanity-check the private key shape without any crypto library."""
    if not key:
        print(f"{BAD} Missing POLYMARKET_WALLET_PRIVATE_KEY.")
        print("  Set it (private key of a funded Amoy TEST wallet) in the")
        print("  environment or backend/.env, then re-run.")
        return False
    hexpart = key[2:] if key.lower().startswith("0x") else key
    if not re.fullmatch(r"[0-9a-fA-F]{64}", hexpart):
        print(f"{BAD} POLYMARKET_WALLET_PRIVATE_KEY doesn't look like a 32-byte hex key")
        print("  (expected 64 hex chars, optionally 0x-prefixed).")
        return False
    print(f"{OK} Wallet key format looks valid (32-byte hex).")
    return True


def main():
    parser = argparse.ArgumentParser(description="Polymarket TESTNET client smoke test")
    parser.add_argument("--place-test-order", action="store_true",
                        help="place a far-from-market test order and cancel it")
    parser.add_argument("--token-id", help="CLOB token id for --place-test-order")
    args = parser.parse_args()

    _load_dotenv()
    print("Polymarket TESTNET (Amoy) smoke test - fake funds only\n" + "-" * 54)

    key = os.environ.get("POLYMARKET_WALLET_PRIVATE_KEY")
    if not check_key_format(key):
        sys.exit(1)

    client = PolymarketTestnetClient(wallet_private_key=key)
    print(f"    host={client.host}  chain_id={client.chain_id} (Amoy testnet)")
    print(f"    {WARN} confirm the host above matches Polymarket's current Amoy docs.")

    # 1. Library + wallet address (no network) --------------------------------
    try:
        address = client.wallet_address()
        print(f"{OK} py-clob-client present; wallet address: {address}")
    except RuntimeError as e:
        print(f"{BAD} {e}")
        sys.exit(1)
    except Exception as e:
        print(f"{BAD} Could not derive wallet address: {e}")
        sys.exit(1)

    healthy = False
    authed = False

    # 2. CLOB health (network, no auth) ---------------------------------------
    try:
        client.server_ok()
        print(f"{OK} CLOB host reachable (health check passed).")
        healthy = True
    except Exception as e:
        print(f"{BAD} CLOB health check failed: {e}")
        print("  Likely the placeholder host is wrong or Amoy CLOB is unreachable.")

    # 3. API credential derivation (auth) -------------------------------------
    if healthy:
        try:
            client._get_client()  # derives + sets L2 API creds
            print(f"{OK} Derived L2 API credentials (auth works).")
            authed = True
        except Exception as e:
            print(f"{BAD} API credential derivation failed: {e}")

    # 4. Optional order lifecycle ---------------------------------------------
    if args.place_test_order:
        print()
        if not authed:
            print(f"{BAD} Skipping order test - auth did not pass.")
        elif not args.token_id:
            print(f"{BAD} --place-test-order requires --token-id.")
        else:
            place_and_cancel(client, args.token_id)

    print("-" * 54)
    if authed:
        print(f"{OK} Ready: wallet + Amoy CLOB auth working. (Liquidity may still be nil.)")
    else:
        print(f"{BAD} Not fully validated - resolve the failures above before TESTNET mode.")
        sys.exit(1)


def place_and_cancel(client, token_id):
    # Buy 1 share at $0.01 -- far below market, so it rests unfilled.
    print(f"  Placing BUY 1 @ $0.01 on token {token_id} (far from market)...")
    try:
        resp = client.place_limit_order(token_id=token_id, side="BUY", size=1, price=0.01)
    except Exception as e:
        print(f"{BAD} Order placement failed: {e}")
        return
    order_id = resp.get("orderID") or resp.get("order_id") if isinstance(resp, dict) else None
    print(f"{OK} Order submitted. response={resp}")
    if not order_id:
        print(f"{WARN} No order id parsed from response; cancel manually if it rested.")
        return
    try:
        client.cancel_order(order_id)
        print(f"{OK} Order cancelled. Full place->cancel lifecycle works.")
    except Exception as e:
        print(f"{BAD} Cancel failed for {order_id}: {e} (cancel it manually).")


if __name__ == "__main__":
    main()
