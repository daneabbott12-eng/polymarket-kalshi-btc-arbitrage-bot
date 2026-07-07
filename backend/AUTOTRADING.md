# Auto-detection & execution

The bot can run headless, continuously detecting opportunities and (optionally,
and only if you deliberately arm it) executing them.

## Execution modes

| Mode | How to select | What it does | Money |
|------|---------------|--------------|-------|
| `DRY_RUN` | default | detect + log intended orders only | none |
| `TESTNET` | `EXECUTION_MODE=testnet` + demo creds | places REAL orders on demo/testnet | fake |
| `LIVE` | `ARM_LIVE_TRADING=true` + creds + you wire the stubs | places real orders | **REAL** |

## Safety model — read this first

- **Default is DRY_RUN.** Nothing places any order out of the box.
- **TESTNET** places orders against Kalshi's demo API and Polymarket's Amoy
  testnet using `clients/kalshi_client.py` / `clients/polymarket_client.py`.
  Fake funds only — the clients are hard-wired to demo/testnet hosts and refuse
  Polygon mainnet. Falls back to DRY_RUN if credentials are missing.
- **LIVE (real money)** requires **all** of, by design:
  1. `ARM_LIVE_TRADING=true`
  2. All exchange credentials present
  3. You implement the order-submission stubs in `execution_engine.py`
     (`_place_kalshi_order` / `_place_polymarket_order`), which currently raise
     `NotImplementedError` so an armed-but-unfinished setup **fails safe**.
- Position limits (`ARB_MAX_ORDER_CONTRACTS`, `ARB_MAX_OPEN_POSITIONS`) apply to
  the TESTNET and LIVE paths.

## Validate your Kalshi demo credentials first

Before running TESTNET mode, confirm your demo keys work:

```bash
cd backend
python smoke_test_kalshi.py                       # host + signing + balance
python smoke_test_kalshi.py --list-markets        # find a ticker
python smoke_test_kalshi.py --place-test-order --ticker <TICKER>   # place + cancel
```

`[OK] Auth OK ... Demo balance: $X` means you're ready. A `401` means the demo
API is reachable but rejected the credentials (check key id / private key / clock
skew). The order test places a 1-contract order priced far from the market so it
rests without filling, then cancels it.

And for the Polymarket Amoy testnet leg (`pip install py-clob-client` first):

```bash
python smoke_test_polymarket.py                                  # key + lib + address + health + auth
python smoke_test_polymarket.py --place-test-order --token-id <TOKEN_ID>
```

It checks the wallet key format, derives your wallet address, health-checks the
CLOB, and derives API creds. Note: the Amoy CLOB host in
`clients/polymarket_client.py` is a **placeholder** - the health check will fail
until you set the correct host from Polymarket's docs, and Amoy liquidity is
typically nil.

## Running on testnet (fake funds)

1. `pip install -r requirements.txt` (adds `cryptography`) and
   `pip install py-clob-client` (for the Polymarket leg).
2. Get **Kalshi demo** API credentials (key id + RSA private key) from the demo
   dashboard, and a funded **Amoy** test wallet (test USDC/MATIC).
3. Put them in `.env`, set `EXECUTION_MODE=testnet`. Run `smoke_test_kalshi.py`
   above to confirm the Kalshi leg before going further.
4. Confirm the current Amoy CLOB host in Polymarket's docs and update
   `clients/polymarket_client.py` (`DEFAULT_TESTNET_HOST` is a placeholder).
5. Run the backend + `python auto_runner.py`. The header badge turns amber
   (`Auto: TESTNET`); detected opportunities are placed on the demo/testnet books.

## Run the auto-runner (detection + alerts, DRY_RUN)

Start the backend, then in another shell:

```bash
cd backend
python auto_runner.py
```

It polls `ARB_API_BASE` (default `http://localhost:8000`) every `AUTO_POLL_SECONDS`
(default 3), and for each new opportunity that survives depth + fees + slippage it:
- logs an alert to the console and to `backend/opportunities.log`, and
- hands it to the execution engine (DRY_RUN → logs the intended orders only).

The dashboard header shows the current mode (`Auto: DRY-RUN` or a red
`⚠ LIVE TRADING`), also available at `GET /auto/status`.

## Arming live trading (advanced, at your own risk)

1. Copy `.env.example` to `.env` and fill in the exchange credentials.
2. Implement the two order-submission methods in `execution_engine.py` using the
   official clients (Kalshi REST + RSA signing; Polymarket `py-clob-client` with
   an EIP-712 wallet signer).
3. Set `ARM_LIVE_TRADING=true` and appropriate `ARB_MAX_*` limits.
4. Load the env and run. The header badge turns red; orders become real.

Nothing in this repo trades real money until you complete step 2 yourself.
