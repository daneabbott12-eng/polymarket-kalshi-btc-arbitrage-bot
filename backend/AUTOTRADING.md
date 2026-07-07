# Auto-detection & execution

The bot can run headless, continuously detecting opportunities and (optionally,
and only if you deliberately arm it) executing them.

## Safety model — read this first

- **Default is DRY_RUN.** Nothing places a real order out of the box.
- Live trading requires **all** of the following, by design:
  1. `ARM_LIVE_TRADING=true`
  2. All exchange credentials present in the environment
  3. You implement the order-submission stubs in `execution_engine.py`
     (`_place_kalshi_order` / `_place_polymarket_order`), which currently raise
     `NotImplementedError` so an armed-but-unfinished setup **fails safe** instead
     of sending malformed orders.
- Position limits (`ARB_MAX_ORDER_CONTRACTS`, `ARB_MAX_OPEN_POSITIONS`) apply to
  the live path only.

If any of 1–3 is missing, the engine stays in DRY_RUN and places nothing.

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
