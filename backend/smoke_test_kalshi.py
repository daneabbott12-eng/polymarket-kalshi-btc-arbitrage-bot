"""Smoke test for the Kalshi DEMO (testnet) client.

Validates your demo credentials and, optionally, the full order lifecycle
(place -> cancel) using a resting order priced far from the market so it will not
fill. DEMO environment only - fake funds. No real money is ever involved.

Usage:
    # Read-only checks (host reachable, signing works, balance):
    python smoke_test_kalshi.py

    # List a few open demo markets (to find a --ticker):
    python smoke_test_kalshi.py --list-markets

    # Full lifecycle: place a 1-contract far-from-market order, then cancel it:
    python smoke_test_kalshi.py --place-test-order --ticker <TICKER>

Credentials (from the Kalshi DEMO dashboard) via environment or a .env file:
    KALSHI_API_KEY_ID   demo API key id
    KALSHI_PRIVATE_KEY  demo RSA private key, PEM format
"""
import os
import sys
import argparse

import requests

from clients.kalshi_client import KalshiDemoClient

# ASCII markers (Windows consoles default to cp1252 and choke on unicode ticks).
OK = "[OK]"
BAD = "[FAIL]"


def _load_dotenv():
    """Minimal .env loader so you don't have to export vars by hand. Only sets
    keys that aren't already in the environment; ignores comments/blank lines."""
    path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val.replace("\\n", "\n"))


def get_client():
    key_id = os.environ.get("KALSHI_API_KEY_ID")
    private_key = os.environ.get("KALSHI_PRIVATE_KEY")
    if not key_id or not private_key:
        print(f"{BAD} Missing credentials.")
        print("  Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY (from the Kalshi DEMO")
        print("  dashboard) in your environment or backend/.env, then re-run.")
        sys.exit(1)
    return KalshiDemoClient(key_id, private_key)


def check_auth(client):
    """Does a signed GET /portfolio/balance and classifies the result.

    Returns (reachable, authed). A well-formed signed request that the server
    rejects with 401/403 still proves reachability (and that signing works well
    enough to be processed) -- it just means the credentials aren't valid.
    """
    try:
        bal = client.get_balance()
        cents = bal.get("balance") if isinstance(bal, dict) else None
        pretty = f"${cents / 100:,.2f}" if isinstance(cents, (int, float)) else bal
        print(f"{OK} Auth OK (signed request accepted). Demo balance: {pretty}")
        return True, True
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code
        if code in (401, 403):
            print(f"{BAD} Reached the demo API, but it rejected the credentials ({code}).")
            print("  Check the key id, that the private key matches it, and your clock")
            print("  (the signature includes a millisecond timestamp; large skew fails).")
        else:
            print(f"{BAD} Reached the demo API but got HTTP {code}: {e}")
        return True, False
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        print(f"{BAD} Could not reach the demo API (network/DNS): {e}")
        return False, False
    except Exception as e:
        print(f"{BAD} Unexpected error during signed request: {e}")
        return False, False


def list_markets(client):
    try:
        data = client.get_markets(limit=10, status="open")
        markets = data.get("markets", []) if isinstance(data, dict) else []
        if not markets:
            print("  No open demo markets returned.")
            return
        print(f"{OK} {len(markets)} open demo markets (use one as --ticker):")
        for m in markets:
            print(f"    {m.get('ticker'):32} {m.get('title', '')[:50]}")
    except Exception as e:
        print(f"{BAD} Could not list markets: {e}")


def place_and_cancel(client, ticker):
    # Buy 1 'no' contract at 1 cent -- far below market, so it rests unfilled.
    print(f"  Placing 1x NO @ 1c on {ticker} (far from market; should NOT fill)...")
    try:
        resp = client.place_limit_order(
            ticker=ticker, side="no", action="buy", count=1,
            price_cents=1, client_order_id="smoke-test-1",
        )
    except Exception as e:
        print(f"{BAD} Order placement failed: {e}")
        return
    order = resp.get("order", resp) if isinstance(resp, dict) else resp
    order_id = order.get("order_id") if isinstance(order, dict) else None
    print(f"{OK} Order placed. order_id={order_id} status={order.get('status') if isinstance(order, dict) else '?'}")
    if not order_id:
        print(f"{BAD} No order_id returned; cannot auto-cancel. Check the demo UI.")
        return
    try:
        client.cancel_order(order_id)
        print(f"{OK} Order cancelled. Full place->cancel lifecycle works.")
    except Exception as e:
        print(f"{BAD} Cancel failed for {order_id}: {e} (cancel it manually in the demo UI).")


def main():
    parser = argparse.ArgumentParser(description="Kalshi DEMO client smoke test")
    parser.add_argument("--list-markets", action="store_true", help="list open demo markets")
    parser.add_argument("--place-test-order", action="store_true",
                        help="place a far-from-market test order and cancel it")
    parser.add_argument("--ticker", help="market ticker for --place-test-order")
    args = parser.parse_args()

    _load_dotenv()
    print("Kalshi DEMO smoke test (fake funds only)\n" + "-" * 42)
    client = get_client()

    reachable, authed = check_auth(client)

    if args.list_markets:
        print()
        list_markets(client)

    if args.place_test_order:
        print()
        if not authed:
            print(f"{BAD} Skipping order test - auth did not pass.")
        elif not args.ticker:
            print(f"{BAD} --place-test-order requires --ticker (try --list-markets first).")
        else:
            place_and_cancel(client, args.ticker)

    print("-" * 42)
    if reachable and authed:
        print(f"{OK} Ready: credentials valid against the Kalshi demo environment.")
    else:
        print(f"{BAD} Not ready - resolve the failures above before running TESTNET mode.")
        sys.exit(1)


if __name__ == "__main__":
    main()
