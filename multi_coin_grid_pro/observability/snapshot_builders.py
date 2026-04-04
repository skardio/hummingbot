"""
AI-F1: Snapshot builders — extract feature dictionaries from controller state.

Each builder returns a plain dict suitable for DecisionSnapshot fields.
Kept separate from the controller to avoid coupling and simplify testing.
"""

import time
from typing import Any, Dict, List, Optional


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert Decimal/int/None to float safely."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def build_market_features(
    symbol: str,
    trend_calculator,
    candle_calc=None,
    last_entry_indicators: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Extract market features for *symbol* from trend calculator + indicators.

    Returns dict with keys: trend_1h, trend_4h, trend_24h, consensus_trend,
    volatility, rsi, atr_pct, vwap_deviation_pct, spread_pct, etc.
    """
    features: Dict[str, Any] = {"symbol": symbol}

    if not trend_calculator:
        return features

    trend = trend_calculator.get_trend(symbol)
    if not trend:
        return features

    features["trend_pct"] = _safe_float(getattr(trend, "trend_pct", None))
    features["consensus_trend_pct"] = _safe_float(getattr(trend, "consensus_trend_pct", None))
    features["trend_1h"] = _safe_float(getattr(trend, "trend_60m", None))
    features["trend_4h"] = _safe_float(getattr(trend, "trend_240m", None))
    features["trend_24h"] = _safe_float(getattr(trend, "trend_1440m", None))
    features["volatility"] = _safe_float(getattr(trend, "volatility", None))
    features["data_points"] = len(getattr(trend, "price_history", []))

    # SmartEntry indicators cached per symbol by the controller
    if last_entry_indicators:
        ind = last_entry_indicators.get(symbol, {})
        features["rsi"] = _safe_float(ind.get("rsi"))
        features["atr_pct"] = _safe_float(ind.get("atr_pct"))
        features["vwap_deviation_pct"] = _safe_float(ind.get("vwap_deviation_pct"))
        features["wick_ratio"] = _safe_float(ind.get("wick_ratio"))
        features["change_5m_pct"] = _safe_float(ind.get("change_5m_pct"))

    return features


def build_strategy_state(
    active_coins: Dict[str, str],
    max_slots: int,
    monitored_coins: List[str],
    config,
) -> Dict[str, Any]:
    """
    Capture strategy state at decision time.
    """
    return {
        "active_coins": list(active_coins.keys()),
        "slots_used": len(active_coins),
        "max_slots": max_slots,
        "monitored_coins_count": len(monitored_coins),
        "trend_min_change_pct": _safe_float(getattr(config, "trend_min_change_pct", None)),
        "use_smart_entry_filter": getattr(config, "use_smart_entry_filter", False),
        "use_multi_timeframe": getattr(config, "use_multi_timeframe", False),
    }


def build_bot_state(
    bot_start_time: float,
    circuit_breaker_active: bool,
    api_error_paused: bool,
    warmup_complete: bool = True,
    paper_trading: bool = False,
) -> Dict[str, Any]:
    """
    Capture bot operational state.
    """
    return {
        "uptime_sec": time.time() - bot_start_time,
        "circuit_breaker_active": circuit_breaker_active,
        "api_error_paused": api_error_paused,
        "warmup_complete": warmup_complete,
        "paper_trading": paper_trading,
    }


def build_risk_context(risk_manager, drawdown_tracker=None) -> Dict[str, Any]:
    """
    Capture risk manager state.
    """
    ctx: Dict[str, Any] = {}
    if risk_manager:
        ctx["daily_loss_pct"] = _safe_float(getattr(risk_manager, "daily_loss_pct", None))
        ctx["remaining_daily_budget"] = _safe_float(
            getattr(risk_manager, "remaining_daily_notional", None)
        )
    if drawdown_tracker:
        ctx["drawdown_daily_pct"] = _safe_float(getattr(drawdown_tracker, "daily_drawdown_pct", None))
        ctx["drawdown_weekly_pct"] = _safe_float(getattr(drawdown_tracker, "weekly_drawdown_pct", None))
    return ctx


def build_rotation_context(
    from_coin: Optional[str],
    to_coin: str,
    from_trend_pct: float,
    to_trend_pct: float,
    hold_time_sec: float,
    switch_cost: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Capture rotation-specific features.
    """
    return {
        "from_coin": from_coin,
        "to_coin": to_coin,
        "from_trend_pct": from_trend_pct,
        "to_trend_pct": to_trend_pct,
        "trend_difference_pct": to_trend_pct - from_trend_pct,
        "hold_time_sec": hold_time_sec,
        "switch_cost": _safe_float(switch_cost),
    }


def build_filter_checks_from_trace(trace) -> List[Dict[str, Any]]:
    """
    Convert PairDecisionTrace.checks to a list of plain dicts.
    """
    if not trace or not getattr(trace, "checks", None):
        return []
    return [c.to_dict() for c in trace.checks]
