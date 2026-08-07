#!/usr/bin/env python3
"""
ATR Live Monitor — Real-time ATR% voor trading pairs.

Gebruik:
    python atr_live.py okx BTC-USDC
    python atr_live.py kraken-eur XBT/EUR
    python atr_live.py kraken-usd XBT/USD
    python atr_live.py bitget BTC-USDT
    python atr_live.py okx BTC-USDC --period 20 --refresh 60

Laat continu de ATR zien + of het genoeg is om te handelen na fees.
"""

import argparse
import sys
import time
from datetime import datetime

import requests

# ── Exchange configuratie ──────────────────────────────────────────────────────
# fee_rt_pct = round-trip (maker+maker, best case)
EXCHANGES = {
    "okx": {
        "name": "OKX EU",
        "fee_rt_pct": 0.40,   # 0.20% maker + 0.20% maker
        "multiplier": 2.0,
        "type": "okx",
    },
    "kraken-eur": {
        "name": "Kraken EUR",
        "fee_rt_pct": 0.40,   # 0.20% maker + 0.20% maker
        "multiplier": 2.0,
        "type": "kraken",
    },
    "kraken-usd": {
        "name": "Kraken USD",
        "fee_rt_pct": 0.40,
        "multiplier": 2.0,
        "type": "kraken",
    },
    "bitget": {
        "name": "Bitget",
        "fee_rt_pct": 0.20,   # 0.10% maker + 0.10% maker
        "multiplier": 2.0,
        "type": "bitget",
    },
}

# ── ATR berekening (zelfde formule als de bot) ─────────────────────────────────


def calculate_atr_pct(highs, lows, closes, period=14):
    """ATR(period) als % van huidige prijs. Formule: avg(True Range) / prijs × 100."""
    if len(closes) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(closes)):
        high_low = highs[i] - lows[i]
        high_close = abs(highs[i] - closes[i - 1])
        low_close = abs(lows[i] - closes[i - 1])
        true_ranges.append(max(high_low, high_close, low_close))

    if len(true_ranges) < period:
        return None

    atr = sum(true_ranges[-period:]) / period
    current_price = closes[-1]
    return (atr / current_price) * 100 if current_price > 0 else None


# ── Exchange API fetchers ──────────────────────────────────────────────────────

def _get(url, params, timeout=10):
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_okx(pair, period):
    """Haal candles + ticker + spread op van OKX."""
    limit = max(period + 5, 20)

    candles_data = _get(
        "https://www.okx.com/api/v5/market/candles",
        {"instId": pair, "bar": "1m", "limit": limit},
    )
    if candles_data.get("code") != "0":
        raise ValueError(f"OKX fout: {candles_data.get('msg')}")

    # OKX geeft nieuwste eerst terug → omkeren
    rows = list(reversed(candles_data["data"]))
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    closes = [float(r[4]) for r in rows]

    # Ticker voor spread
    ticker_data = _get(
        "https://www.okx.com/api/v5/market/ticker",
        {"instId": pair},
    )
    ticker = ticker_data["data"][0]
    bid = float(ticker["bidPx"])
    ask = float(ticker["askPx"])
    mid = (bid + ask) / 2
    spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 0.0
    price = float(ticker["last"])
    vol_24h = float(ticker.get("vol24h", 0)) * price / 1_000_000  # miljoen quote

    return highs, lows, closes, price, spread_pct, vol_24h


def _normalize_kraken_pair(pair):
    """Verwijder / en - voor de Kraken API."""
    return pair.replace("/", "").replace("-", "")


def fetch_kraken(pair, period):
    """Haal candles + ticker op van Kraken."""
    api_pair = _normalize_kraken_pair(pair)
    limit = max(period + 5, 20)

    candles_data = _get(
        "https://api.kraken.com/0/public/OHLC",
        {"pair": api_pair, "interval": 1, "count": limit},
    )
    if candles_data.get("error"):
        raise ValueError(f"Kraken fout: {candles_data['error']}")

    result = candles_data["result"]
    # Kraken geeft de pair-sleutel terug (kan afwijken, bv. XXBTZUSD i.p.v. XBTUSD)
    pair_key = next(k for k in result if k != "last")
    rows = result[pair_key]

    # Kraken formaat: [time, open, high, low, close, vwap, volume, count]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    closes = [float(r[4]) for r in rows]

    # Ticker
    ticker_data = _get(
        "https://api.kraken.com/0/public/Ticker",
        {"pair": api_pair},
    )
    ticker_result = ticker_data["result"]
    ticker_key = next(iter(ticker_result))
    t = ticker_result[ticker_key]
    bid = float(t["b"][0])
    ask = float(t["a"][0])
    mid = (bid + ask) / 2
    spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 0.0
    price = float(t["c"][0])
    vol_24h = float(t["v"][1]) * price / 1_000_000

    return highs, lows, closes, price, spread_pct, vol_24h


def fetch_bitget(pair, period):
    """Haal candles + ticker op van Bitget."""
    symbol = pair.replace("-", "").replace("/", "")
    limit = max(period + 5, 20)

    candles_data = _get(
        "https://api.bitget.com/api/v2/spot/market/candles",
        {"symbol": symbol, "granularity": "1min", "limit": limit},
    )
    rows = candles_data.get("data", [])
    if not rows:
        raise ValueError(f"Bitget: geen candle data voor {symbol}")

    # Bitget: [timestamp, open, high, low, close, vol, quoteVol]
    # Nieuwste eerst → omkeren
    rows = list(reversed(rows))
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    closes = [float(r[4]) for r in rows]

    # Ticker
    ticker_data = _get(
        "https://api.bitget.com/api/v2/spot/market/tickers",
        {"symbol": symbol},
    )
    t = ticker_data["data"][0]
    bid = float(t.get("buyOne", t.get("bidPr", 0)))
    ask = float(t.get("sellOne", t.get("askPr", 0)))
    mid = (bid + ask) / 2
    spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 0.0
    price = float(t["lastPr"])
    vol_24h = float(t.get("quoteVolume", 0)) / 1_000_000

    return highs, lows, closes, price, spread_pct, vol_24h


FETCHERS = {
    "okx": fetch_okx,
    "kraken": fetch_kraken,
    "bitget": fetch_bitget,
}


# ── Display ────────────────────────────────────────────────────────────────────

def progress_bar(value, target, width=24):
    """Toon hoe ver value van target is als ASCII balk."""
    pct = min(value / target, 1.0) if target > 0 else 0.0
    filled = int(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct * 100:.0f}%"


def clear_line():
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


def print_snapshot(exchange_cfg, pair, period, highs, lows, closes,
                   price, spread_pct, vol_24h, iteration):
    atr = calculate_atr_pct(highs, lows, closes, period)
    now = datetime.now().strftime("%H:%M:%S")

    required_atr = exchange_cfg["fee_rt_pct"] * exchange_cfg["multiplier"]

    if atr is None:
        status_line = f"  ⚠️  Onvoldoende data voor ATR({period})"
        bar = ""
    elif atr >= required_atr:
        ratio = atr / required_atr
        status_emoji = "✅"
        status_line = (
            f"  Status:   {status_emoji} HANDELEN OK — ATR {ratio:.1f}× boven target"
        )
        bar = progress_bar(atr, required_atr)
    else:
        ratio = atr / required_atr
        status_emoji = "❌"
        status_line = (
            f"  Status:   {status_emoji} ATR_TOO_LOW — {1 / ratio:.1f}× onder target"
        )
        bar = progress_bar(atr, required_atr)

    atr_str = f"{atr:.4f}%" if atr is not None else "n/a"

    print(
        f"\n[{now}]  #{iteration}"
        f"  Prijs: {price:>12,.4f}"
        f"  Spread: {spread_pct:.4f}%"
        f"  Vol24h: €{vol_24h:.1f}M"
    )
    print(
        f"  ATR({period}):  {atr_str:>8}  {bar}"
    )
    print(
        f"  Vereist: {required_atr:.3f}%"
        f"  (fees {exchange_cfg['fee_rt_pct']:.2f}% × {exchange_cfg['multiplier']:.1f})"
    )
    print(status_line)


def print_header(exchange_name, pair, period, refresh):
    width = 62
    print("=" * width)
    print(f"  ATR Live Monitor  |  {exchange_name}  |  {pair}")
    print(f"  ATR({period} × 1m candles)  |  refresh: {refresh}s  |  Ctrl+C om te stoppen")
    print("=" * width)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Real-time ATR monitor voor trading pairs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Voorbeelden:
  python atr_live.py okx BTC-USDC
  python atr_live.py kraken-eur XBT/EUR
  python atr_live.py kraken-usd XBT/USD
  python atr_live.py bitget BTC-USDT --refresh 30
  python atr_live.py okx ETH-USDC --period 20
""",
    )
    parser.add_argument(
        "exchange",
        choices=list(EXCHANGES.keys()),
        help="Exchange: okx | kraken-eur | kraken-usd | bitget",
    )
    parser.add_argument(
        "pair",
        help="Trading pair, bv. BTC-USDC of XBT/EUR",
    )
    parser.add_argument(
        "--period", "-p",
        type=int,
        default=14,
        help="ATR periode in candles (default: 14)",
    )
    parser.add_argument(
        "--refresh", "-r",
        type=int,
        default=30,
        help="Refresh interval in seconden (default: 30)",
    )
    args = parser.parse_args()

    exchange_cfg = EXCHANGES[args.exchange]
    fetcher = FETCHERS[exchange_cfg["type"]]

    print_header(exchange_cfg["name"], args.pair, args.period, args.refresh)

    iteration = 0
    while True:
        iteration += 1
        try:
            highs, lows, closes, price, spread_pct, vol_24h = fetcher(
                args.pair, args.period
            )
            print_snapshot(
                exchange_cfg, args.pair, args.period,
                highs, lows, closes, price, spread_pct, vol_24h,
                iteration,
            )
        except requests.exceptions.RequestException as e:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ⚠️  Netwerk fout: {e}")
        except ValueError as e:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ⚠️  {e}")
        except KeyboardInterrupt:
            print("\n\nGestopt.")
            sys.exit(0)

        # Countdown tot volgende refresh
        try:
            for remaining in range(args.refresh, 0, -1):
                sys.stdout.write(f"\r  Volgende update over {remaining:2d}s...  ")
                sys.stdout.flush()
                time.sleep(1)
            clear_line()
        except KeyboardInterrupt:
            print("\n\nGestopt.")
            sys.exit(0)


if __name__ == "__main__":
    main()
