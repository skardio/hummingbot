"""
Central ReasonCode taxonomy for decision tracking.

This module defines standard rejection reasons used across the trading pipeline.
Each code maps 1:1 to a specific rejection condition for clear observability.

Usage:
    from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage

    trace.reason_code = ReasonCode.RSI_OVERBOUGHT
    trace.stage = Stage.SMART_ENTRY
    trace.metadata["rsi_value"] = 75.3
"""

from enum import Enum


class Stage(str, Enum):
    """Pipeline stages for decision tracking"""
    SMART_ENTRY = "SMART_ENTRY"
    MTF = "MTF"
    RISK = "RISK"
    EXECUTION = "EXECUTION"
    REGIME = "REGIME"
    EXECUTOR_CREATE = "EXECUTOR_CREATE"  # US-004: Budget allocation stage


class ReasonCode(str, Enum):
    """
    Central taxonomy for rejection reasons (max 30 codes).

    Success:
        - trace.accepted = True (no reason_code needed)
        - EventLogger emits gate_passed event

    Rejection:
        - trace.accepted = False
        - trace.reason_code = one of the codes below
        - trace.stage = corresponding Stage
        - EventLogger emits gate_denied event

    Use trace.metadata dict for sub-categories (e.g., which MTF timeframe failed).
    """

    # ===== SMART_ENTRY (14 codes) =====
    RSI_OVERBOUGHT = "RSI_OVERBOUGHT"
    RSI_OVERSOLD = "RSI_OVERSOLD"
    RSI_EXTREME_BLOCK = "RSI_EXTREME_BLOCK"
    VWAP_DEVIATION_TOO_HIGH = "VWAP_DEVIATION_TOO_HIGH"
    WICK_RATIO_LOW = "WICK_RATIO_LOW"
    ATR_TOO_LOW = "ATR_TOO_LOW"
    ATR_TOO_HIGH = "ATR_TOO_HIGH"
    SPIKE_5M_EXCESSIVE = "SPIKE_5M_EXCESSIVE"
    ACCEL_FALLING_KNIFE = "ACCEL_FALLING_KNIFE"
    ACCEL_BLOWOFF = "ACCEL_BLOWOFF"
    TREND_24H_OUT_OF_RANGE = "TREND_24H_OUT_OF_RANGE"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    DEPTH_INSUFFICIENT = "DEPTH_INSUFFICIENT"
    ORDERBOOK_UNAVAILABLE = "ORDERBOOK_UNAVAILABLE"
    NO_PRICE_DATA = "NO_PRICE_DATA"  # Unable to fetch bid/ask prices
    NO_ORDERBOOK_DATA = "NO_ORDERBOOK_DATA"  # Orderbook snapshot unavailable
    STALE_PRICE = "STALE_PRICE"  # US-008: Price data too old
    STALE_ORDERBOOK = "STALE_ORDERBOOK"  # US-008: Orderbook data too old

    # ===== MTF (2 codes) =====
    MTF_INSUFFICIENT = "MTF_INSUFFICIENT"
    MTF_CRASH_DETECTED = "MTF_CRASH_DETECTED"

    # ===== RISK (6 codes) =====
    EXPOSURE_LIMIT = "EXPOSURE_LIMIT"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    COOLDOWN_EXIT = "COOLDOWN_EXIT"
    COOLDOWN_SWITCH = "COOLDOWN_SWITCH"
    COOLDOWN_LOSS_STREAK = "COOLDOWN_LOSS_STREAK"
    POSITION_LIMIT = "POSITION_LIMIT"

    # ===== EXECUTION (7 codes) =====
    BLACKLIST = "BLACKLIST"
    SLOT_FULL = "SLOT_FULL"
    ALREADY_TRADING = "ALREADY_TRADING"
    STARTUP_DELAY = "STARTUP_DELAY"
    NOT_TRADEABLE = "NOT_TRADEABLE"
    ORDERBOOK_ERROR = "ORDERBOOK_ERROR"
    INSUFFICIENT_BUDGET = "INSUFFICIENT_BUDGET"  # US-004: Not enough free capital

    # ===== REGIME (2 codes) =====
    REGIME_BTC_DUMP = "REGIME_BTC_DUMP"
    REGIME_DUMP_COOLDOWN = "REGIME_DUMP_COOLDOWN"


def get_stage_for_reason(reason: ReasonCode) -> Stage:
    """
    Map ReasonCode to Stage (helper for auto-classification).

    Args:
        reason: ReasonCode to classify

    Returns:
        Corresponding Stage enum value
    """
    smart_entry_codes = {
        ReasonCode.RSI_OVERBOUGHT, ReasonCode.RSI_OVERSOLD, ReasonCode.RSI_EXTREME_BLOCK,
        ReasonCode.VWAP_DEVIATION_TOO_HIGH, ReasonCode.WICK_RATIO_LOW,
        ReasonCode.ATR_TOO_LOW, ReasonCode.ATR_TOO_HIGH,
        ReasonCode.SPIKE_5M_EXCESSIVE, ReasonCode.ACCEL_FALLING_KNIFE, ReasonCode.ACCEL_BLOWOFF,
        ReasonCode.TREND_24H_OUT_OF_RANGE, ReasonCode.SPREAD_TOO_WIDE,
        ReasonCode.DEPTH_INSUFFICIENT, ReasonCode.ORDERBOOK_UNAVAILABLE,
        ReasonCode.NO_PRICE_DATA, ReasonCode.NO_ORDERBOOK_DATA,
        ReasonCode.STALE_PRICE, ReasonCode.STALE_ORDERBOOK,  # US-008
    }
    mtf_codes = {ReasonCode.MTF_INSUFFICIENT, ReasonCode.MTF_CRASH_DETECTED}
    risk_codes = {
        ReasonCode.EXPOSURE_LIMIT, ReasonCode.DAILY_LOSS_LIMIT,
        ReasonCode.COOLDOWN_EXIT, ReasonCode.COOLDOWN_SWITCH, ReasonCode.COOLDOWN_LOSS_STREAK,
        ReasonCode.POSITION_LIMIT,
    }
    execution_codes = {
        ReasonCode.BLACKLIST, ReasonCode.SLOT_FULL, ReasonCode.ALREADY_TRADING,
        ReasonCode.STARTUP_DELAY, ReasonCode.NOT_TRADEABLE, ReasonCode.ORDERBOOK_ERROR,
    }
    regime_codes = {ReasonCode.REGIME_BTC_DUMP, ReasonCode.REGIME_DUMP_COOLDOWN}

    if reason in smart_entry_codes:
        return Stage.SMART_ENTRY
    elif reason in mtf_codes:
        return Stage.MTF
    elif reason in risk_codes:
        return Stage.RISK
    elif reason in execution_codes:
        return Stage.EXECUTION
    elif reason in regime_codes:
        return Stage.REGIME
    else:
        return Stage.EXECUTION  # Default fallback
