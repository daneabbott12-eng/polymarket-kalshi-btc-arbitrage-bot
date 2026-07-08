"""Assets the arbitrage detector covers.

Each has the same parallel structure on both venues: a Polymarket hourly
"<word>-up-or-down-..." event, a Kalshi hourly "KX<..>D" Above/Below series, and
a Kraken price feed for the "price to beat". Verified live for all five.

    name    : short display symbol
    poly    : Polymarket slug word
    kalshi  : Kalshi series prefix (lowercase; the event ticker upper-cases it)
    kraken  : Kraken ticker/OHLC pair (price to beat + current price)
    binance : Binance symbol (primary price source; falls back to Kraken)
"""
ASSETS = [
    {"name": "BTC",  "poly": "bitcoin",  "kalshi": "kxbtcd",  "kraken": "XBTUSDT",  "binance": "BTCUSDT"},
    {"name": "ETH",  "poly": "ethereum", "kalshi": "kxethd",  "kraken": "ETHUSDT",  "binance": "ETHUSDT"},
    {"name": "SOL",  "poly": "solana",   "kalshi": "kxsold",  "kraken": "SOLUSDT",  "binance": "SOLUSDT"},
    {"name": "XRP",  "poly": "xrp",      "kalshi": "kxxrpd",  "kraken": "XRPUSDT",  "binance": "XRPUSDT"},
    {"name": "DOGE", "poly": "dogecoin", "kalshi": "kxdoged", "kraken": "DOGEUSDT", "binance": "DOGEUSDT"},
]
