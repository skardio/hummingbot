# momentum_indicators.py — pure functions for computing momentum metrics.
# No I/O. No exchange dependencies. All functions are deterministic.
import statistics
from typing import List, Optional

from multi_coin_grid_pro.signals.momentum_models import CandleSnapshot, OrderBookSnapshot

# ---------------------------------------------------------------------------
# Candle-based metrics
# ---------------------------------------------------------------------------


def price_change_pct(candles: List[CandleSnapshot], n_periods: int) -> Optional[float]:
    """Return (close_now - close_n_periods_ago) / close_n_periods_ago * 100.

    Returns None if fewer than n_periods+1 candles are available or
    if close_n_periods_ago is 0.  Candles are expected oldest-first.
    """
    if len(candles) < n_periods + 1:
        return None
    close_now = candles[-1].close
    close_ago = candles[-(n_periods + 1)].close
    if close_ago == 0:
        return None
    return (close_now - close_ago) / close_ago * 100.0


def volume_ratio(
    candles: List[CandleSnapshot],
    recent_n: int = 5,
    baseline_n: int = 15,
) -> Optional[float]:
    """Average volume of the last recent_n candles divided by the average
    volume of the preceding baseline_n candles.

    Returns None if fewer than (recent_n + baseline_n) candles are available
    or if the baseline average is 0.  Candles are expected oldest-first.
    """
    needed = recent_n + baseline_n
    if len(candles) < needed:
        return None
    recent = candles[-recent_n:]
    baseline = candles[-(recent_n + baseline_n): -recent_n]
    recent_avg = sum(c.volume for c in recent) / recent_n
    baseline_avg = sum(c.volume for c in baseline) / baseline_n
    if baseline_avg == 0:
        return None
    return recent_avg / baseline_avg


def volatility_pct(candles: List[CandleSnapshot], n: int = 15) -> Optional[float]:
    """Standard deviation of close-to-close returns (%) over the last n candles.

    Returns None if fewer than 2 candles are available.
    Candles are expected oldest-first.
    """
    if len(candles) < 2:
        return None
    recent = candles[-n:] if len(candles) >= n else candles
    returns = []
    for i in range(1, len(recent)):
        prev = recent[i - 1].close
        curr = recent[i].close
        if prev > 0:
            returns.append((curr - prev) / prev * 100.0)
    if len(returns) < 2:
        return None
    return statistics.stdev(returns)


# ---------------------------------------------------------------------------
# Orderbook-based metrics
# ---------------------------------------------------------------------------

def orderbook_depth_quote(ob: OrderBookSnapshot, depth: int = 20) -> Optional[float]:
    """Sum of (price × amount) for the top `depth` bid and ask levels combined.

    Returns None if the orderbook has no bids and no asks.
    """
    if not ob.bids and not ob.asks:
        return None
    total = 0.0
    for level in ob.bids[:depth]:
        total += level[0] * level[1]
    for level in ob.asks[:depth]:
        total += level[0] * level[1]
    return total


def orderbook_imbalance(ob: OrderBookSnapshot, depth: int = 20) -> Optional[float]:
    """bid_depth_quote / (bid_depth_quote + ask_depth_quote).

    Returns None if total depth is 0.
    """
    bid_depth = sum(level[0] * level[1] for level in ob.bids[:depth])
    ask_depth = sum(level[0] * level[1] for level in ob.asks[:depth])
    total = bid_depth + ask_depth
    if total == 0:
        return None
    return bid_depth / total


def estimate_slippage_pct(
    ob: OrderBookSnapshot,
    order_size_quote: float,
) -> Optional[float]:
    """Estimate market-buy slippage (%) for the given order size in quote currency.

    Walks ask levels to simulate a market buy of `order_size_quote` units.
    Returns (average_fill_price - best_ask) / best_ask * 100.
    Returns None if the orderbook has no asks or the order cannot be fully filled.
    Note: order_size_quote is treated as the pair's quote currency (e.g. EUR for
    EUR-denominated pairs). No cross-currency conversion is performed.
    """
    if not ob.asks:
        return None
    best_ask = ob.asks[0][0]
    if best_ask <= 0:
        return None
    remaining = order_size_quote
    total_base = 0.0
    for price, qty in ob.asks:
        level_quote = price * qty
        if level_quote >= remaining:
            total_base += remaining / price
            remaining = 0.0
            break
        total_base += qty
        remaining -= level_quote
    if remaining > 0 or total_base <= 0:
        return None
    avg_fill = order_size_quote / total_base
    return (avg_fill - best_ask) / best_ask * 100.0


# ---------------------------------------------------------------------------
# Apply helpers — write metrics into an EnrichedCandidate in-place
# ---------------------------------------------------------------------------

_MAX_CANDLE_AGE_SECONDS = 120  # 1m candles: nieuwste mag max 2 min oud zijn


def acceleration_score(
    price_change_1m_pct: Optional[float],
    price_change_3m_pct: Optional[float],
    price_change_5m_pct: Optional[float],
) -> float:
    """Compute momentum acceleration score (0.0 – 1.0).

    Returns 0.0 if any of the three deltas is None.
    Levels (evaluated top-down, first match wins):
      1.0  — accelerating: Δ1m ≥ 0.25% AND Δ3m ≥ 0.7% AND Δ5m ≥ 1.2%
      0.7  — stable:       Δ3m ≥ 0.7% AND Δ5m ≥ 1.2%
      0.4  — flattening:   Δ5m ≥ 1.2% only
      0.0  — otherwise
    """
    if price_change_1m_pct is None or price_change_3m_pct is None or price_change_5m_pct is None:
        return 0.0
    if price_change_5m_pct >= 1.2:
        if price_change_3m_pct >= 0.7:
            if price_change_1m_pct >= 0.25:
                return 1.0
            return 0.7
        return 0.4
    return 0.0


def apply_candle_metrics(candidate, candles: List[CandleSnapshot], now: float) -> None:
    """Compute all candle-based metrics and write them into the candidate.

    Skips all metrics if the newest candle is stale (>2 min old for 1m candles).
    Stale candles occur on low-volume pairs when the exchange returns cached data
    without advancing the candle timestamp — leaving price_change_* as None so
    the MISSING_PRICE_CHANGE_5M filter correctly rejects the pair.
    """
    if not candles:
        return
    newest_candle_age = now - candles[-1].timestamp
    if newest_candle_age > _MAX_CANDLE_AGE_SECONDS:
        return  # stale API data; leave metrics as None → MISSING_PRICE_CHANGE_5M
    p1m = price_change_pct(candles, 1)
    p3m = price_change_pct(candles, 3)
    p5m = price_change_pct(candles, 5)
    candidate.candles_fetched_at = now
    candidate.price_change_1m_pct = p1m
    candidate.price_change_3m_pct = p3m
    candidate.price_change_5m_pct = p5m
    candidate.price_change_15m_pct = price_change_pct(candles, 15)
    candidate.volume_ratio = volume_ratio(candles)
    candidate.volatility_pct = volatility_pct(candles)
    candidate.acceleration_score = acceleration_score(p1m, p3m, p5m)


def apply_orderbook_metrics(candidate, ob: OrderBookSnapshot, depth: int = 20) -> None:
    """Compute all orderbook-based metrics and write them into the candidate."""
    candidate.ob_fetched_at = ob.fetched_at
    candidate.orderbook_depth_quote = orderbook_depth_quote(ob, depth)
    candidate.orderbook_imbalance = orderbook_imbalance(ob, depth)
    candidate.slippage_100eur = estimate_slippage_pct(ob, 100.0)
    candidate.slippage_250eur = estimate_slippage_pct(ob, 250.0)
