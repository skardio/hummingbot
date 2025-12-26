"""
Configuration loader for Hybrid Grid Bot v2.0
"""
import logging
from pathlib import Path
from typing import Any, Dict

import yaml

from multi_coin_grid_pro.core.performance_tracker import PerformanceConfig
from multi_coin_grid_pro.filters.market_regime_filter import MarketRegimeConfig
from multi_coin_grid_pro.filters.time_based_filter import TimeBasedConfig

logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    """
    Load YAML configuration file

    Args:
        path: Path to config file (relative or absolute)

    Returns:
        Dictionary containing configuration

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If YAML is invalid
    """
    config_path = Path(path)

    if not config_path.exists():
        # Try relative to multi_coin_grid_pro/config/
        alt_path = Path(__file__).parent.parent / "config" / path
        if alt_path.exists():
            config_path = alt_path
        else:
            raise FileNotFoundError(f"Config file not found: {path}")

    logger.info(f"Loading config from: {config_path}")

    with config_path.open("r") as f:
        config = yaml.safe_load(f)

    # Validate required fields
    required_fields = ["connector_name", "quote_asset"]
    for field in required_fields:
        if field not in config:
            raise ValueError(f"Missing required config field: {field}")

    logger.info(f"Config loaded: {config.get('connector_name')} / {config.get('quote_asset')}")
    return config


def parse_market_regime_config(config: Dict[str, Any]) -> MarketRegimeConfig:
    """
    Parse market regime configuration from YAML config.

    Args:
        config: Full configuration dictionary

    Returns:
        MarketRegimeConfig object with settings
    """
    regime_config_dict = config.get("market_regime", {})

    # Create config with values from YAML (or defaults)
    # Support both btc_symbol (new) and btc_reference_pair (legacy)
    btc_pair = regime_config_dict.get("btc_symbol") or regime_config_dict.get("btc_reference_pair", "BTC-EUR")

    regime_config = MarketRegimeConfig(
        btc_reference_pair=btc_pair,
        btc_trend_weight=regime_config_dict.get("btc_trend_weight", 0.6),
        # Support both old and new naming conventions
        btc_min_trend_1h=regime_config_dict.get(
            "btc_trend_1h_min_pct") or regime_config_dict.get("btc_min_trend_1h", -2.0),
        btc_min_trend_4h=regime_config_dict.get(
            "btc_trend_4h_min_pct") or regime_config_dict.get("btc_min_trend_4h", 0.0),
        btc_min_trend_24h=regime_config_dict.get(
            "btc_trend_24h_min_pct") or regime_config_dict.get("btc_min_trend_24h", -5.0),
        altcoin_breadth_enabled=regime_config_dict.get("altcoin_breadth_enabled", True),
        altcoin_breadth_min=regime_config_dict.get("altcoin_breadth_min", 0.30),
        altcoin_breadth_pairs=regime_config_dict.get("altcoin_breadth_pairs", None),
        altcoin_breadth_threshold_1h=regime_config_dict.get("altcoin_breadth_threshold_1h", 0.5),
        pause_on_btc_dump=regime_config_dict.get("pause_on_btc_dump", True),
        btc_dump_threshold_1h=regime_config_dict.get(
            "dump_threshold_pct") or regime_config_dict.get("btc_dump_threshold_1h", -5.0),
        btc_dump_cooldown_minutes=regime_config_dict.get(
            "dump_pause_minutes") or regime_config_dict.get("btc_dump_cooldown_minutes", 60),
        resume_on_recovery=regime_config_dict.get("resume_on_recovery", True),
        recovery_threshold_pct=regime_config_dict.get("recovery_threshold_pct", 2.0),
    )

    logger.info(f"Market regime config parsed: BTC ref={regime_config.btc_reference_pair}, "
                f"dump detection={'enabled' if regime_config.pause_on_btc_dump else 'disabled'}")

    return regime_config


def parse_time_based_config(config: Dict[str, Any]) -> TimeBasedConfig:
    """
    Parse time-based trading rules configuration from YAML config.

    Args:
        config: Full configuration dictionary

    Returns:
        TimeBasedConfig object with settings
    """
    time_config_dict = config.get("time_based_rules", {})

    # Map config.prod.yaml field names to internal names
    # Support both old and new field names for backward compatibility
    low_liq_hours = time_config_dict.get("low_liquidity_hours") or time_config_dict.get(
        "low_liquidity_hours_utc", [0, 1, 2, 3, 4, 5])
    high_liq_hours = time_config_dict.get("high_liquidity_hours") or time_config_dict.get(
        "high_liquidity_hours_utc", [13, 14, 15, 16, 17, 18])
    high_liq_bonus = time_config_dict.get(
        "high_liquidity_bonus_pct",
        time_config_dict.get(
            "high_liquidity_bonus",
            0.0)) / 100.0  # Convert % to decimal

    # Holiday support: new field names (holidays, holiday_action, holiday_risk_multiplier)
    holidays = time_config_dict.get("holidays") or time_config_dict.get("holiday_dates", [])
    holiday_enabled = len(holidays) > 0  # Auto-enable if holidays are defined
    holiday_risk_mult = time_config_dict.get("holiday_risk_multiplier", 0.5)

    # Create config with values from YAML (or defaults)
    time_config = TimeBasedConfig(
        enabled=time_config_dict.get("enabled", True),
        avoid_low_liquidity_hours=time_config_dict.get("avoid_low_liquidity_hours", True),
        low_liquidity_hours_utc=low_liq_hours,
        low_liquidity_action=time_config_dict.get("low_liquidity_action", "monitor_only"),
        prefer_high_liquidity_hours=time_config_dict.get("prefer_high_liquidity_hours", True),
        high_liquidity_hours_utc=high_liq_hours,
        high_liquidity_bonus=high_liq_bonus,
        weekend_mode=time_config_dict.get("weekend_mode", "reduced_risk"),
        weekend_risk_multiplier=time_config_dict.get("weekend_risk_multiplier", 0.5),
        weekend_days=time_config_dict.get("weekend_days", [6, 7]),
        daily_stats_reset_hour_utc=time_config_dict.get("daily_stats_reset_hour_utc", 0),
        respect_holidays=holiday_enabled,
        holiday_dates=holidays,
        holiday_risk_multiplier=holiday_risk_mult,
    )

    logger.info(f"Time-based config parsed: enabled={time_config.enabled}, "
                f"weekend_mode={time_config.weekend_mode}, "
                f"low_liquidity_action={time_config.low_liquidity_action}")

    return time_config


def parse_performance_config(config: Dict[str, Any]) -> PerformanceConfig:
    """
    Parse performance tracking configuration from YAML config.

    Args:
        config: Full configuration dictionary

    Returns:
        PerformanceConfig object with settings
    """
    perf_config_dict = config.get("performance_tracking", {})

    # Create config with values from YAML (or defaults)
    perf_config = PerformanceConfig(
        enabled=perf_config_dict.get("enabled", True),
        win_rate_lookback_trades=perf_config_dict.get("win_rate_lookback_trades", 20),
        sharpe_lookback_days=perf_config_dict.get("sharpe_lookback_days", 7),
        profit_factor_lookback_days=perf_config_dict.get("profit_factor_lookback_days", 7),
        min_acceptable_win_rate=perf_config_dict.get("min_acceptable_win_rate", 0.45),
        min_acceptable_sharpe=perf_config_dict.get("min_acceptable_sharpe", 0.5),
        min_acceptable_profit_factor=perf_config_dict.get("min_acceptable_profit_factor", 1.2),
        max_acceptable_drawdown_pct=perf_config_dict.get("max_acceptable_drawdown_pct", 5.0),
        max_fee_to_profit_ratio=perf_config_dict.get("max_fee_to_profit_ratio", 0.30),
        risk_free_rate_annual=perf_config_dict.get("risk_free_rate_annual", 0.03),
        report_interval_hours=perf_config_dict.get("report_interval_hours", 4),
        save_to_db=perf_config_dict.get("save_to_db", True),
    )

    logger.info(f"Performance tracking config parsed: enabled={perf_config.enabled}, "
                f"win_rate_threshold={perf_config.min_acceptable_win_rate:.0%}, "
                f"sharpe_threshold={perf_config.min_acceptable_sharpe:.2f}")

    return perf_config
