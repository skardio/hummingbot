#!/usr/bin/env python3
"""
B2 Hybrid Scalper Bot for Bitget

Combines ORDERFLOW (orderbook imbalance + taker flow) with CANDLE MOMENTUM.

Strategy:
1. Scan orderbook for bid/ask imbalance (>60% bids = bullish)
2. Analyze recent trades for taker buy/sell ratio
3. Confirm with RSI, EMA trend, VWAP, price momentum
4. Dynamic TP/SL based on ATR (volatility-adjusted)
5. Trail stop after profit threshold

Key Features:
- Orderflow analysis (orderbook + taker flow)
- ATR-based dynamic take profit & stop loss
- EMA + VWAP + RSI multi-indicator confirmation
- Spread filter (skip wide spread markets)
- Volume spike detection
- Telegram alerts with NET P&L (after fees)

Usage:
  export BITGET_API_KEY="your_key"
  export BITGET_SECRET_KEY="your_secret"
  export BITGET_PASSPHRASE="your_passphrase"
  python3 scripts/momentum_scalper_bitget/momentum_scalper.py
"""

import asyncio
import json
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    import ccxt.async_support as ccxt_async
except ImportError:
    print("❌ ccxt not installed. Run: pip install ccxt")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    print("❌ numpy not installed. Run: pip install numpy")
    sys.exit(1)

try:
    import requests
except ImportError:
    requests = None

try:
    import yaml
except ImportError:
    print("❌ pyyaml not installed. Run: pip install pyyaml")
    sys.exit(1)


@dataclass
class TradeSignal:
    """Trading signal with momentum data."""
    symbol: str
    direction: str  # 'long' or 'short'
    strength: float  # 0-100
    rsi: float
    volume_ratio: float
    price: Decimal
    timestamp: datetime
    reason: str


@dataclass
class Position:
    """Open position tracking."""
    symbol: str
    direction: str
    entry_price: Decimal
    amount: Decimal
    entry_time: datetime
    stop_loss: Decimal
    take_profit: Decimal
    trailing_stop: Optional[Decimal] = None
    highest_price: Decimal = field(default_factory=lambda: Decimal("0"))
    lowest_price: Decimal = field(default_factory=lambda: Decimal("999999"))


class MomentumScalperBot:
    """B2 Hybrid Momentum/Scalper Trading Bot with AI-Adaptive Features."""

    @staticmethod
    def load_config(config_path: str = None) -> Dict:
        """Load configuration from YAML file with fallback to defaults."""
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"

        if not Path(config_path).exists():
            print(f"⚠️ Config file not found: {config_path}, using defaults")
            return MomentumScalperBot._default_config()

        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)

            # Convert to expected types
            if 'base_order_size_usdt' in config:
                config['order_size_usdt'] = Decimal(str(config['base_order_size_usdt']))
            if 'fee_per_trade_pct' in config:
                config['fee_per_trade_pct'] = Decimal(str(config['fee_per_trade_pct']))

            # Map YAML keys to internal keys (atr_tp_multiplier → atr_tp_mult)
            if 'atr_tp_multiplier' in config:
                config['atr_tp_mult'] = Decimal(str(config['atr_tp_multiplier']))
            if 'atr_sl_multiplier' in config:
                config['atr_sl_mult'] = Decimal(str(config['atr_sl_multiplier']))

            # Add any missing defaults
            defaults = MomentumScalperBot._default_config()
            for key, value in defaults.items():
                if key not in config:
                    config[key] = value

            print(f"✅ Config loaded from {config_path}")
            return config

        except Exception as e:
            print(f"❌ Error loading config: {e}")
            print("⚠️ Using default configuration")
            return MomentumScalperBot._default_config()

    @staticmethod
    def _default_config() -> Dict:
        """Default configuration (fallback)."""
        return {
            'symbols': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT'],
            'order_size_usdt': Decimal('20'),
            'max_positions': 3,
            'fee_per_trade_pct': Decimal('0.1'),
            'rsi_period': 14,
            'rsi_overbought': 65,
            'rsi_oversold': 35,
            'momentum_threshold': 70,  # INCREASED: was 35, now 70 for higher quality signals
            'min_imbalance_long': 0.52,
            'min_imbalance_short': 0.48,
            'min_taker_buy_ratio_long': 0.52,
            'min_taker_buy_ratio_short': 0.48,
            'max_spread_bps': 20,
            'volume_spike_threshold': 2.0,
            'min_volume_ratio': 1.3,
            'atr_period': 14,
            'atr_tp_mult': Decimal('1.5'),  # INCREASED: was 0.8
            'atr_sl_mult': Decimal('0.5'),  # DECREASED: was 1.1
            'take_profit_pct': Decimal('1.0'),  # INCREASED: was 0.8
            'stop_loss_pct': Decimal('0.3'),  # DECREASED: was 0.7
            'trailing_activate_pct': Decimal('0.8'),  # INCREASED: was 0.5
            'trailing_stop_pct': Decimal('0.25'),  # DECREASED: was 0.35
            'candle_period': '1m',
            'scan_interval': 5,
            'position_timeout': 900,
            'max_daily_loss_pct': Decimal('4'),
            'max_trades_per_hour': 10,
            'use_market_orders': True,
            'execute_trades': os.getenv('EXECUTE_TRADES', 'false').lower() == 'true',
            # AI-Adaptive features
            'enable_adaptive_sizing': True,
            'min_position_multiplier': 0.5,
            'max_position_multiplier': 3.0,
            'enable_cooldown': True,
            'cooldown_duration_seconds': 3600,
            'cooldown_trigger_losses': 3,
            'cooldown_trigger_hot_score': 0.3,
            'hot_score_memory': 10,
            'base_atr_threshold': 0.03,
            'min_orderflow_score': 30,
            'daily_loss_size_reduction_threshold_1': -20.0,
            'daily_loss_size_reduction_multiplier_1': 0.7,
            'daily_loss_size_reduction_threshold_2': -50.0,
            'daily_loss_size_reduction_multiplier_2': 0.5,
        }

    # Configuration will be loaded from config.yaml
    CONFIG = None

    def __init__(self, config_path: str = None):
        # Load configuration from YAML
        self.CONFIG = self.load_config(config_path)

        # API credentials
        self.api_key = os.getenv('BITGET_API_KEY')
        self.api_secret = os.getenv('BITGET_SECRET_KEY')
        self.passphrase = os.getenv('BITGET_PASSPHRASE')

        # Telegram
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat = os.getenv('TELEGRAM_CHAT_ID')

        # Exchange
        self.exchange: Optional[ccxt_async.bitget] = None

        # Data storage
        self.candles: Dict[str, deque] = {}  # symbol -> deque of candles
        self.positions: Dict[str, Position] = {}  # symbol -> position

        # Statistics
        self.trades_executed = 0
        self.trades_won = 0
        self.trades_lost = 0
        self.total_pnl = Decimal("0")
        self.daily_pnl = Decimal("0")
        self.hourly_trades = deque(maxlen=100)

        # Per-symbol stats (for hot/cold tracking and cooldowns)
        self.symbol_stats: Dict[str, Dict] = {}
        self.last_mid_price: Dict[str, float] = {}

        # Logging - auto-detect log directory
        # Try to use repo root logs/ if we're in scripts/momentum_scalper_bitget/
        repo_logs = Path(__file__).parent.parent.parent / 'logs'
        if repo_logs.exists():
            log_dir = repo_logs
        else:
            log_dir = Path('logs')
            log_dir.mkdir(exist_ok=True)

        # Override with config if specified as absolute path
        config_log_file = self.CONFIG.get('log_file', 'logs/momentum_scalper.log')
        config_trade_log = self.CONFIG.get('trade_log_file', 'logs/momentum_trades.json')

        if Path(config_log_file).is_absolute():
            self.log_file = config_log_file
        else:
            self.log_file = str(log_dir / 'momentum_scalper.log')

        if Path(config_trade_log).is_absolute():
            self.trade_log = config_trade_log
        else:
            self.trade_log = str(log_dir / 'momentum_trades.json')

        # Initialize per-symbol storage
        for symbol in self.CONFIG['symbols']:
            self.candles[symbol] = deque(maxlen=100)
            self.symbol_stats[symbol] = {
                'cooldown_until': 0.0,
                'recent_results': deque(maxlen=self.CONFIG.get('hot_score_memory', 10)),
                'hot_score': 0.5,  # 0..1 (0.5 = neutral)
                'last_trade_ts': 0.0,
            }
            self.last_mid_price[symbol] = 0.0

    async def init_exchange(self) -> bool:
        """Initialize exchange connection."""
        if not all([self.api_key, self.api_secret, self.passphrase]):
            if self.CONFIG['execute_trades']:
                self.log("❌ API keys required for live trading!")
                return False
            self.log("⚠️ No API keys - running in simulation mode")

        self.exchange = ccxt_async.bitget({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'password': self.passphrase,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'},
        })

        await self.exchange.load_markets()
        self.log("✅ Exchange connected")
        return True

    async def close_exchange(self):
        """Close exchange connection."""
        if self.exchange:
            await self.exchange.close()

    def log(self, message: str, level: str = "INFO"):
        """Log message to console and file."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)

        with open(self.log_file, 'a') as f:
            f.write(log_line + '\n')

    def send_telegram(self, message: str):
        """Send Telegram notification."""
        if not self.telegram_token or not self.telegram_chat or not requests:
            return

        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            requests.post(url, json={
                'chat_id': self.telegram_chat,
                'text': message,
                'parse_mode': 'HTML',
            }, timeout=5)
        except Exception:
            pass

    async def fetch_candles(self, symbol: str, limit: int = 50) -> List:
        """Fetch recent candles."""
        try:
            ohlcv = await self.exchange.fetch_ohlcv(
                symbol,
                self.CONFIG['candle_period'],
                limit=limit
            )
            return ohlcv
        except Exception as e:
            self.log(f"⚠️ Failed to fetch candles for {symbol}: {e}", "WARNING")
            return []

    def calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate RSI indicator."""
        if len(prices) < period + 1:
            return 50.0

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi)

    def calculate_volume_ratio(self, volumes: List[float]) -> float:
        """Calculate current volume vs average."""
        if len(volumes) < 10:
            return 1.0

        current_vol = volumes[-1]
        avg_vol = np.mean(volumes[-20:-1]) if len(volumes) > 20 else np.mean(volumes[:-1])

        if avg_vol == 0:
            return 1.0

        return current_vol / avg_vol

    def calculate_atr(self, candles: List, period: int = 14) -> float:
        """Average True Range in absolute price units."""
        if len(candles) < period + 1:
            return 0.0

        trs = []
        for i in range(1, len(candles)):
            prev_close = candles[i - 1][4]
            high = candles[i][2]
            low = candles[i][3]

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
            trs.append(tr)

        if len(trs) < period:
            return float(np.mean(trs))
        return float(np.mean(trs[-period:]))

    async def fetch_orderflow(self, symbol: str) -> Optional[Dict[str, float]]:
        """Orderbook + trade-based orderflow metrics + momentum score."""
        if not self.exchange:
            return None

        try:
            # Fetch orderbook (top 20 levels)
            ob = await self.exchange.fetch_order_book(symbol, limit=20)
            bids = ob.get('bids', [])
            asks = ob.get('asks', [])
            if not bids or not asks:
                return None

            best_bid = bids[0][0]
            best_ask = asks[0][0]
            mid = (best_bid + best_ask) / 2

            # Track micro-move (change in mid price since last check)
            prev_mid = self.last_mid_price.get(symbol, 0.0)
            self.last_mid_price[symbol] = mid

            if prev_mid > 0:
                micro_move_pct = (mid - prev_mid) / prev_mid * 100
            else:
                micro_move_pct = 0.0

            spread_pct = (best_ask - best_bid) / mid * 100  # in %

            # Orderbook imbalance
            bid_vol = sum(level[1] for level in bids)
            ask_vol = sum(level[1] for level in asks)
            total_book_vol = bid_vol + ask_vol
            if total_book_vol == 0:
                return None

            imbalance = bid_vol / total_book_vol  # 0..1 (>0.5 = more bids = bullish)

            # Taker flow from recent trades
            trades = await self.exchange.fetch_trades(symbol, limit=50)
            buy_vol = sum(t['amount'] for t in trades if t.get('side') == 'buy')
            sell_vol = sum(t['amount'] for t in trades if t.get('side') == 'sell')
            total_trades_vol = buy_vol + sell_vol

            if total_trades_vol == 0:
                taker_buy_ratio = 0.5
            else:
                taker_buy_ratio = buy_vol / total_trades_vol

            # Compute orderflow momentum score (0-100)
            of_score = self.compute_orderflow_momentum_score(
                imbalance=imbalance,
                taker_buy_ratio=taker_buy_ratio,
                spread_pct=spread_pct,
                micro_move_pct=micro_move_pct,
            )

            return {
                'imbalance': float(imbalance),
                'taker_buy_ratio': float(taker_buy_ratio),
                'spread_pct': float(spread_pct),
                'micro_move_pct': float(micro_move_pct),
                'of_score': float(of_score),
            }

        except Exception as e:
            self.log(f"⚠️ Orderflow fetch failed for {symbol}: {e}", "WARNING")
            return None

    def compute_orderflow_momentum_score(
        self,
        imbalance: float,
        taker_buy_ratio: float,
        spread_pct: float,
        micro_move_pct: float,
    ) -> float:
        """
        Compute 0-100 score for orderflow momentum (how explosive the flow is).
        0 = dead, 100 = extreme momentum.
        """
        score = 0.0

        # 1) Imbalance component (orderbook pressure)
        # 0.5 = neutral, >0.6 long bias, <0.4 short bias
        imbalance_dist = abs(imbalance - 0.5) * 2  # 0..1
        score += imbalance_dist * 35  # max 35 points

        # 2) Taker flow component
        taker_dist = abs(taker_buy_ratio - 0.5) * 2  # 0..1
        score += taker_dist * 35  # max 35 points

        # 3) Spread penalty (tighter spread = better)
        # 0.02% spread = excellent, 0.20% = poor
        spread_penalty = min(max(spread_pct / 0.20, 0.0), 1.0)  # 0..1
        score += (1.0 - spread_penalty) * 20  # max 20 points

        # 4) Micro move boost (small positive move = momentum building)
        micro_boost = max(min(micro_move_pct / 0.05, 1.0), -1.0)  # -1..1
        score += micro_boost * 10  # can be -10 to +10

        # Clamp to 0-100
        score = max(0.0, min(score, 100.0))
        return score

    def adaptive_atr_threshold(
        self,
        atr_pct: float,
        imbalance: float,
        taker_buy_ratio: float,
        of_score: float,
    ) -> bool:
        """
        AI-adaptive ATR threshold check.
        - Normal: atr_pct >= base_threshold
        - Strong orderflow: may go lower
        - Extreme orderflow: even lower
        """
        base_threshold = self.CONFIG.get('base_atr_threshold', 0.03)

        # Normal situation
        if atr_pct >= base_threshold:
            return True

        # Level 2: strong orderflow (score >= 65)
        if of_score >= 65 and atr_pct >= base_threshold * 0.60:
            return True

        # Level 3: extreme orderflow (score >= 80)
        if of_score >= 80 and atr_pct >= base_threshold * 0.40:
            return True

        return False

    def compute_position_size_usdt(
        self,
        symbol: str,
        signal_strength: float,
        of_score: float
    ) -> Decimal:
        """
        AI-adaptive position sizing based on:
        - Trade quality (orderflow + signal strength)
        - Symbol hot/cold state
        - Daily P&L (reduce if losing)
        """
        if not self.CONFIG.get('enable_adaptive_sizing', False):
            return self.CONFIG['order_size_usdt']

        base = self.CONFIG['order_size_usdt']

        # 1) Trade quality score (0..1)
        trade_quality = (0.6 * (of_score / 100.0) + 0.4 * (signal_strength / 100.0))
        trade_quality = max(0.0, min(trade_quality, 1.0))

        # 2) Hot score per symbol (0..1)
        stats = self.symbol_stats.get(symbol, {})
        hot_score = stats.get('hot_score', 0.5)

        # 3) Daily P&L safety (reduce size if losing)
        daily_usd = float(self.daily_pnl)
        safety_mult = 1.0

        threshold_1 = self.CONFIG.get('daily_loss_size_reduction_threshold_1', -20.0)
        threshold_2 = self.CONFIG.get('daily_loss_size_reduction_threshold_2', -50.0)
        mult_1 = self.CONFIG.get('daily_loss_size_reduction_multiplier_1', 0.7)
        mult_2 = self.CONFIG.get('daily_loss_size_reduction_multiplier_2', 0.5)

        if daily_usd < threshold_2:
            safety_mult = mult_2
        elif daily_usd < threshold_1:
            safety_mult = mult_1

        # 4) Quality multiplier
        if trade_quality < 0.4:
            q_mult = 0.5
        elif trade_quality < 0.6:
            q_mult = 1.0
        elif trade_quality < 0.8:
            q_mult = 1.5
        else:
            q_mult = 2.0

        # 5) Hotness multiplier
        if hot_score > 0.7:
            h_mult = 1.25
        elif hot_score < 0.3:
            h_mult = 0.7
        else:
            h_mult = 1.0

        final_mult = q_mult * h_mult * safety_mult

        # Clamp to configured bounds
        min_mult = self.CONFIG.get('min_position_multiplier', 0.5)
        max_mult = self.CONFIG.get('max_position_multiplier', 3.0)
        final_mult = max(min_mult, min(final_mult, max_mult))

        final_size = base * Decimal(str(final_mult))
        return final_size

    def detect_momentum(self, symbol: str, candles: List) -> Optional[TradeSignal]:
        """Detect momentum signal from candles.

        FIXED: Previous version had a bug where RSI oversold would trigger LONG,
        but then "RSI falling" would override to SHORT. Now we use exclusive logic.
        """
        if len(candles) < 20:
            return None

        # Extract data
        closes = [c[4] for c in candles]
        volumes = [c[5] for c in candles]
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]
        current_price = Decimal(str(closes[-1]))

        # Calculate indicators
        rsi = self.calculate_rsi(closes)
        volume_ratio = self.calculate_volume_ratio(volumes)

        # Price momentum (last 5 candles)
        price_change_5 = (closes[-1] - closes[-5]) / closes[-5] * 100

        # Trend filter: Simple moving average (20 period)
        sma_20 = np.mean(closes[-20:])
        above_sma = closes[-1] > sma_20

        # Determine signal - FIXED: Use exclusive logic to prevent conflicts
        bullish_strength = 0
        bearish_strength = 0
        bullish_reasons = []
        bearish_reasons = []

        # ===== BULLISH SIGNALS =====
        # RSI oversold = expect bounce UP → go LONG
        if rsi < self.CONFIG['rsi_oversold']:
            bullish_strength += 35
            bullish_reasons.append(f"RSI oversold ({rsi:.1f}) - expect bounce")

        # RSI rising from middle + price going up
        if 40 < rsi < 65 and price_change_5 > 0.3:
            bullish_strength += 25
            bullish_reasons.append(f"RSI momentum up ({rsi:.1f})")

        # Price above SMA = uptrend
        if above_sma:
            bullish_strength += 10
            bullish_reasons.append("Above SMA20")

        # Strong upward price move
        if price_change_5 > 0.5:
            bullish_strength += 20
            bullish_reasons.append(f"Strong up move (+{price_change_5:.2f}%)")

        # ===== BEARISH SIGNALS =====
        # RSI overbought = expect pullback DOWN → go SHORT
        if rsi > self.CONFIG['rsi_overbought']:
            bearish_strength += 35
            bearish_reasons.append(f"RSI overbought ({rsi:.1f}) - expect pullback")

        # RSI falling from middle + price going down
        if 35 < rsi < 60 and price_change_5 < -0.3:
            bearish_strength += 25
            bearish_reasons.append(f"RSI momentum down ({rsi:.1f})")

        # Price below SMA = downtrend
        if not above_sma:
            bearish_strength += 10
            bearish_reasons.append("Below SMA20")

        # Strong downward price move
        if price_change_5 < -0.5:
            bearish_strength += 20
            bearish_reasons.append(f"Strong down move ({price_change_5:.2f}%)")

        # ===== VOLUME CONFIRMATION (adds to winning direction) =====
        volume_bonus = 0
        volume_reason = ""
        if volume_ratio > self.CONFIG['volume_spike_threshold']:
            volume_bonus = 25
            volume_reason = f"Volume spike ({volume_ratio:.1f}x)"
        elif volume_ratio > 1.5:
            volume_bonus = 15
            volume_reason = f"High volume ({volume_ratio:.1f}x)"

        # ===== DETERMINE FINAL DIRECTION =====
        # Only take signal if one direction clearly dominates
        direction = None
        signal_strength = 0
        reason = []

        # Minimum difference to avoid conflicting signals (STRICTER)
        MIN_DOMINANCE = 25  # Was 15 - now need clearer directional bias

        # Also require volume confirmation for any trade
        MIN_VOLUME_RATIO = 1.5  # Must have at least 1.5x volume

        if volume_ratio < MIN_VOLUME_RATIO:
            return None  # Skip low volume = unreliable signals

        if bullish_strength > bearish_strength + MIN_DOMINANCE:
            direction = 'long'
            signal_strength = bullish_strength + volume_bonus
            reason = bullish_reasons + ([volume_reason] if volume_reason else [])
        elif bearish_strength > bullish_strength + MIN_DOMINANCE:
            direction = 'short'
            signal_strength = bearish_strength + volume_bonus
            reason = bearish_reasons + ([volume_reason] if volume_reason else [])
        # else: Conflicting signals - no trade

        # Create signal if strong enough
        if signal_strength >= self.CONFIG['momentum_threshold'] and direction:
            return TradeSignal(
                symbol=symbol,
                direction=direction,
                strength=signal_strength,
                rsi=rsi,
                volume_ratio=volume_ratio,
                price=current_price,
                timestamp=datetime.now(),
                reason=", ".join(reason)
            )

        return None

    def detect_momentum_hybrid(
        self,
        symbol: str,
        candles: List,
        orderflow: Optional[Dict[str, float]]
    ) -> Optional[TradeSignal]:
        """Hybrid signal: candle momentum + orderflow confirmation (B2 mode)."""
        if len(candles) < 30:
            return None

        closes = [c[4] for c in candles]
        volumes = [c[5] for c in candles]
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]
        current_price = Decimal(str(closes[-1]))

        # 1) Candle indicators
        rsi = self.calculate_rsi(closes, self.CONFIG['rsi_period'])
        volume_ratio = self.calculate_volume_ratio(volumes)

        ema_fast = float(np.mean(closes[-10:]))
        ema_slow = float(np.mean(closes[-25:]))
        price_change_5 = (closes[-1] - closes[-5]) / closes[-5] * 100

        # VWAP (approx over last N candles)
        vwap_num = sum(c[4] * c[5] for c in candles[-20:])
        vwap_den = sum(c[5] for c in candles[-20:])
        vwap = vwap_num / vwap_den if vwap_den > 0 else closes[-1]
        above_vwap = closes[-1] > vwap

        atr = self.calculate_atr(candles, self.CONFIG['atr_period'])
        atr_pct = (atr / closes[-1]) * 100 if closes[-1] > 0 else 0.0

        # 2) Candle-based directional strength
        bull = 0
        bear = 0
        bull_reasons = []
        bear_reasons = []

        # RSI zones
        if rsi < self.CONFIG['rsi_oversold']:
            bull += 20
            bull_reasons.append(f"RSI oversold ({rsi:.1f})")
        if rsi > self.CONFIG['rsi_overbought']:
            bear += 20
            bear_reasons.append(f"RSI overbought ({rsi:.1f})")

        # Trend via EMA
        if ema_fast > ema_slow:
            bull += 15
            bull_reasons.append("EMA fast > slow")
        else:
            bear += 15
            bear_reasons.append("EMA fast < slow")

        # VWAP bias
        if above_vwap:
            bull += 10
            bull_reasons.append("Above VWAP")
        else:
            bear += 10
            bear_reasons.append("Below VWAP")

        # Recent momentum
        if price_change_5 > 0.4:
            bull += 20
            bull_reasons.append(f"Strong up move ({price_change_5:.2f}%)")
        elif price_change_5 < -0.4:
            bear += 20
            bear_reasons.append(f"Strong down move ({price_change_5:.2f}%)")

        # Volume bonus
        if volume_ratio > self.CONFIG['volume_spike_threshold']:
            bull += 10
            bear += 10  # spike = direction later via orderflow
        elif volume_ratio > self.CONFIG['min_volume_ratio']:
            bull += 5
            bear += 5

        # 3) Orderflow – confirmation / veto
        if not orderflow:
            return None  # Geen orderflow → geen scalp

        imbalance = orderflow['imbalance']
        taker_buy_ratio = orderflow['taker_buy_ratio']
        spread_pct = orderflow['spread_pct']

        # Spread te groot? skip
        spread_bps = spread_pct * 100
        if spread_bps > self.CONFIG['max_spread_bps']:
            # Don't log every skip, too noisy
            return None

        # Orderflow adds to side
        of_bull = 0
        of_bear = 0
        of_reasons_bull = []
        of_reasons_bear = []

        if imbalance >= self.CONFIG['min_imbalance_long'] and \
           taker_buy_ratio >= self.CONFIG['min_taker_buy_ratio_long']:
            of_bull += 25
            of_reasons_bull.append(
                f"Orderflow long (imb={imbalance:.2f}, tBuy={taker_buy_ratio:.2f})"
            )

        if imbalance <= self.CONFIG['min_imbalance_short'] and \
           taker_buy_ratio <= self.CONFIG['min_taker_buy_ratio_short']:
            of_bear += 25
            of_reasons_bear.append(
                f"Orderflow short (imb={imbalance:.2f}, tBuy={taker_buy_ratio:.2f})"
            )

        bullish_strength = bull + of_bull
        bearish_strength = bear + of_bear

        MIN_DOMINANCE = 15  # B2: losser dan 25
        direction = None
        reasons: List[str] = []

        if bullish_strength > bearish_strength + MIN_DOMINANCE:
            direction = "long"
            reasons = bull_reasons + of_reasons_bull
        elif bearish_strength > bullish_strength + MIN_DOMINANCE:
            direction = "short"
            reasons = bear_reasons + of_reasons_bear
        else:
            return None  # Geen duidelijke kant

        # Minimum signal strength
        signal_strength = max(bullish_strength, bearish_strength)
        if signal_strength < self.CONFIG['momentum_threshold']:
            # Debug: log why rejected
            if signal_strength > 30:  # Only log if close to threshold
                self.log(f"⚠️ {symbol}: strength {signal_strength} < {self.CONFIG['momentum_threshold']} (bull={bullish_strength}, bear={bearish_strength})")
            return None

        # Check minimum orderflow score
        of_score = orderflow.get('of_score', 0.0)
        min_of_score = self.CONFIG.get('min_orderflow_score', 30)
        if of_score < min_of_score:
            return None

        # AI-adaptive ATR threshold (uses orderflow to lower requirements)
        if not self.adaptive_atr_threshold(
            atr_pct=atr_pct,
            imbalance=imbalance,
            taker_buy_ratio=taker_buy_ratio,
            of_score=of_score,
        ):
            self.log(f"⚠️ {symbol}: ATR {atr_pct:.2f}% too low (of_score={of_score:.0f})")
            return None

        return TradeSignal(
            symbol=symbol,
            direction=direction,
            strength=float(signal_strength),
            rsi=float(rsi),
            volume_ratio=float(volume_ratio),
            price=current_price,
            timestamp=datetime.now(),
            reason=", ".join(reasons) + f", ATR={atr_pct:.2f}%",
        )

    async def place_order(self, symbol: str, side: str, amount: Decimal,
                          price: Optional[Decimal] = None) -> Optional[Dict]:
        """Place an order."""
        if not self.CONFIG['execute_trades']:
            return {
                'id': f'sim_{int(time.time() * 1000)}',
                'status': 'simulated',
                'symbol': symbol,
                'side': side,
                'amount': float(amount),
            }

        try:
            if self.CONFIG['use_market_orders']:
                order = await self.exchange.create_market_order(
                    symbol, side, float(amount)
                )
            else:
                order = await self.exchange.create_limit_order(
                    symbol, side, float(amount), float(price)
                )
            return order
        except Exception as e:
            self.log(f"❌ Order failed: {e}", "ERROR")
            return None

    async def open_position(self, signal: TradeSignal) -> bool:
        """Open a new position based on signal with ATR-based TP/SL."""
        # Check symbol cooldown
        if self.CONFIG.get('enable_cooldown', True):
            stats = self.symbol_stats.get(signal.symbol, {})
            cooldown_until = stats.get('cooldown_until', 0.0)
            now_ts = time.time()
            if now_ts < cooldown_until:
                remaining = int(cooldown_until - now_ts)
                self.log(f"🧊 {signal.symbol} on cooldown for {remaining}s, skipping")
                return False

        # Check limits
        if len(self.positions) >= self.CONFIG['max_positions']:
            self.log(f"⚠️ Max positions reached ({self.CONFIG['max_positions']})")
            return False

        if signal.symbol in self.positions:
            self.log(f"⚠️ Already have position in {signal.symbol}")
            return False

        # Check hourly trade limit
        recent_trades = sum(1 for t in self.hourly_trades
                            if time.time() - t < 3600)
        if recent_trades >= self.CONFIG['max_trades_per_hour']:
            self.log(f"⚠️ Hourly trade limit reached ({recent_trades})")
            return False

        # AI-adaptive position sizing
        of_score = getattr(signal, 'of_score', 0.0)
        dyn_size_usdt = self.compute_position_size_usdt(
            signal.symbol,
            signal_strength=signal.strength,
            of_score=of_score,
        )
        amount = dyn_size_usdt / signal.price

        # ATR-based dynamic TP/SL
        candles = list(self.candles.get(signal.symbol, []))
        atr = self.calculate_atr(candles, self.CONFIG['atr_period']) if candles else 0.0
        atr_pct = (atr / float(signal.price) * 100) if atr > 0 else 0.6  # fallback 0.6%

        # Calculate TP/SL from ATR
        tp_pct = Decimal(str(atr_pct)) * self.CONFIG['atr_tp_mult']
        sl_pct = Decimal(str(atr_pct)) * self.CONFIG['atr_sl_mult']

        # Clamp to wider bounds (SL loosened to reduce premature stops)
        tp_pct = max(Decimal('1.0'), min(tp_pct, Decimal('2.0')))
        sl_pct = max(Decimal('0.5'), min(sl_pct, Decimal('0.8')))  # WIDENED: was 0.3-0.6%, now 0.5-0.8%

        # Calculate actual price levels
        if signal.direction == 'long':
            stop_loss = signal.price * (1 - sl_pct / 100)
            take_profit = signal.price * (1 + tp_pct / 100)
            side = 'buy'
        else:
            stop_loss = signal.price * (1 + sl_pct / 100)
            take_profit = signal.price * (1 - tp_pct / 100)
            side = 'sell'

        # Place order
        size_mult = float(dyn_size_usdt / self.CONFIG['order_size_usdt'])
        hot_score = self.symbol_stats.get(signal.symbol, {}).get('hot_score', 0.5)
        self.log(f"🎯 OPEN {signal.direction.upper()} {signal.symbol} @ {signal.price}")
        self.log(f"   Size: ${dyn_size_usdt:.2f} ({size_mult:.2f}x base) | Hot: {hot_score:.2f}")
        self.log(f"   TP {tp_pct:.2f}% SL {sl_pct:.2f}% (ATR={atr_pct:.2f}%)")
        self.log(f"   Signal: {signal.reason} | OF_score: {of_score:.0f}")

        order = await self.place_order(signal.symbol, side, amount)

        if not order:
            return False

        # Create position
        position = Position(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.price,
            amount=amount,
            entry_time=datetime.now(),
            stop_loss=stop_loss,
            take_profit=take_profit,
            highest_price=signal.price,
            lowest_price=signal.price,
        )

        self.positions[signal.symbol] = position
        self.hourly_trades.append(time.time())

        # Telegram alert
        self.send_telegram(
            f"🎯 <b>NEW {signal.direction.upper()}</b>\n"
            f"{signal.symbol}\n"
            f"Price: {signal.price}\n"
            f"TP: {take_profit:.4f} | SL: {stop_loss:.4f}\n"
            f"ATR-based: TP {tp_pct:.2f}% SL {sl_pct:.2f}%"
        )

        return True

    async def check_position_exit(self, position: Position, current_price: Decimal) -> bool:
        """Check if position should be exited."""
        symbol = position.symbol
        pnl_pct = Decimal("0")

        if position.direction == 'long':
            pnl_pct = ((current_price - position.entry_price) / position.entry_price) * 100

            # Update highest price for trailing stop
            if current_price > position.highest_price:
                position.highest_price = current_price

                # Activate trailing stop
                if pnl_pct >= self.CONFIG['trailing_activate_pct']:
                    position.trailing_stop = float(current_price) * (1 - self.CONFIG['trailing_stop_pct'] / 100)

            # Check exits
            should_exit = False
            exit_reason = ""

            if current_price <= position.stop_loss:
                should_exit = True
                exit_reason = "Stop Loss Hit"
            elif current_price >= position.take_profit:
                should_exit = True
                exit_reason = "Take Profit Hit"
            elif position.trailing_stop and current_price <= position.trailing_stop:
                should_exit = True
                exit_reason = "Trailing Stop Hit"

        else:  # short
            pnl_pct = ((position.entry_price - current_price) / position.entry_price) * 100

            # Update lowest price for trailing stop
            if current_price < position.lowest_price:
                position.lowest_price = current_price

                # Activate trailing stop
                if pnl_pct >= self.CONFIG['trailing_activate_pct']:
                    position.trailing_stop = float(current_price) * (1 + self.CONFIG['trailing_stop_pct'] / 100)

            # Check exits
            should_exit = False
            exit_reason = ""

            if current_price >= position.stop_loss:
                should_exit = True
                exit_reason = "Stop Loss Hit"
            elif current_price <= position.take_profit:
                should_exit = True
                exit_reason = "Take Profit Hit"
            elif position.trailing_stop and current_price >= position.trailing_stop:
                should_exit = True
                exit_reason = "Trailing Stop Hit"

        # Check timeout
        hold_time = (datetime.now() - position.entry_time).total_seconds()
        if hold_time > self.CONFIG['position_timeout']:
            should_exit = True
            exit_reason = "Timeout"

        if should_exit:
            await self.close_position(position, current_price, pnl_pct, exit_reason)
            return True

        return False

    async def close_position(self, position: Position, exit_price: Decimal,
                             pnl_pct: Decimal, reason: str):
        """Close a position."""
        symbol = position.symbol

        # Place exit order
        if position.direction == 'long':
            side = 'sell'
        else:
            side = 'buy'

        # Calculate NET P&L after fees (0.1% entry + 0.1% exit = 0.2% total)
        total_fees_pct = self.CONFIG['fee_per_trade_pct'] * 2  # Entry + exit
        net_pnl_pct = pnl_pct - total_fees_pct

        self.log(f"📤 Closing {position.direction.upper()} on {symbol}")
        self.log(f"   Entry: {position.entry_price} → Exit: {exit_price}")
        self.log(f"   Gross P&L: {pnl_pct:.2f}% | Fees: -{total_fees_pct:.2f}% | NET: {net_pnl_pct:.2f}%")
        self.log(f"   Reason: {reason}")

        order = await self.place_order(symbol, side, position.amount)

        # Update statistics with NET P&L (after fees)
        net_pnl_usdt = position.amount * position.entry_price * net_pnl_pct / 100
        self.total_pnl += net_pnl_usdt
        self.daily_pnl += net_pnl_usdt
        self.trades_executed += 1

        # Win/loss based on NET profit (after fees)
        if net_pnl_pct > 0:
            self.trades_won += 1
            emoji = "✅"
        else:
            self.trades_lost += 1
            emoji = "❌"

        # Update per-symbol stats (hot/cold + cooldowns)
        if self.CONFIG.get('enable_cooldown', True):
            stats = self.symbol_stats.get(symbol)
            if stats is not None:
                # Track result: +1 for win, -1 for loss
                result = 1 if net_pnl_pct > 0 else -1
                stats['recent_results'].append(result)
                stats['last_trade_ts'] = time.time()

                # Calculate hot score: map -1..+1 → 0..1
                if stats['recent_results']:
                    avg = sum(stats['recent_results']) / len(stats['recent_results'])  # -1..+1
                    hot_score = (avg + 1) / 2.0  # 0..1
                else:
                    hot_score = 0.5

                stats['hot_score'] = hot_score

                # Check for loss streaks
                losses_in_row = 0
                wins_in_row = 0
                for r in reversed(stats['recent_results']):
                    if r == -1:
                        losses_in_row += 1
                        wins_in_row = 0
                    else:
                        wins_in_row += 1
                        losses_in_row = 0
                    if losses_in_row >= 3 or wins_in_row >= 3:
                        break

                # Apply cooldown rules
                cooldown_trigger_losses = self.CONFIG.get('cooldown_trigger_losses', 3)
                cooldown_trigger_hot = self.CONFIG.get('cooldown_trigger_hot_score', 0.3)
                cooldown_duration = self.CONFIG.get('cooldown_duration_seconds', 3600)

                if losses_in_row >= cooldown_trigger_losses or hot_score < cooldown_trigger_hot:
                    stats['cooldown_until'] = time.time() + cooldown_duration
                    self.log(f"🧊 {symbol} cooled down for {cooldown_duration / 60:.0f}min (hot_score={hot_score:.2f}, losses={losses_in_row})")
                elif wins_in_row >= 3 and hot_score > 0.7:
                    self.log(f"🔥 {symbol} marked as HOT (hot_score={hot_score:.2f}, wins={wins_in_row})")

        # Remove position
        del self.positions[symbol]

        # Log trade
        trade_record = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'direction': position.direction,
            'entry_price': float(position.entry_price),
            'exit_price': float(exit_price),
            'gross_pnl_pct': float(pnl_pct),
            'net_pnl_pct': float(net_pnl_pct),
            'net_pnl_usdt': float(net_pnl_usdt),
            'fees_pct': float(total_fees_pct),
            'reason': reason,
            'hold_time': (datetime.now() - position.entry_time).total_seconds(),
        }

        with open(self.trade_log, 'a') as f:
            f.write(json.dumps(trade_record) + '\n')

        # Telegram alert (show NET P&L)
        self.send_telegram(
            f"{emoji} <b>CLOSED {position.direction.upper()}</b>\n"
            f"Symbol: {symbol}\n"
            f"NET P&L: {net_pnl_pct:.2f}% (${net_pnl_usdt:.2f})\n"
            f"Fees: -{total_fees_pct:.2f}%\n"
            f"Reason: {reason}\n"
            f"Total P&L: ${self.total_pnl:.2f}"
        )

    async def scan_markets(self):
        """Scan markets for hybrid signals (B2 aggressive)."""
        for symbol in self.CONFIG['symbols']:
            if symbol in self.positions:
                continue

            # Fetch candles
            candles = await self.fetch_candles(symbol)
            if not candles:
                self.log(f"⚠️ {symbol}: No candles")
                continue

            # Fetch orderflow (orderbook + recent trades)
            orderflow = await self.fetch_orderflow(symbol)
            if not orderflow:
                # Fallback to V1 signal detection if orderflow fails
                self.log(f"⚠️ {symbol}: Orderflow failed, using V1 fallback")
                signal = self.detect_momentum(symbol, candles)
            else:
                # Log orderflow data (spread_pct is already in %, *100 = bps)
                spread_bps = orderflow['spread_pct'] * 100
                self.log(
                    f"🔍 {symbol}: imb={orderflow['imbalance']:.2f} "
                    f"taker={orderflow['taker_buy_ratio']:.2f} "
                    f"spread={spread_bps:.1f}bps (max={self.CONFIG['max_spread_bps']})"
                )
                # Try hybrid first
                signal = self.detect_momentum_hybrid(symbol, candles, orderflow)

            # Store candles
            self.candles[symbol] = deque(candles, maxlen=100)

            if signal:
                # Enrich signal with orderflow score
                signal.of_score = orderflow.get('of_score', 0.0) if orderflow else 0.0

                self.log(
                    f"📊 SIGNAL {symbol} {signal.direction.upper()} "
                    f"strength={signal.strength:.1f} | of_score={signal.of_score:.0f} | "
                    f"rsi={signal.rsi:.1f} | vol={signal.volume_ratio:.2f}"
                )
                await self.open_position(signal)

            await asyncio.sleep(0.2)  # Rate limit

    async def manage_positions(self):
        """Check and manage open positions."""
        for symbol in list(self.positions.keys()):
            position = self.positions[symbol]

            # Get current price
            try:
                ticker = await self.exchange.fetch_ticker(symbol)
                current_price = Decimal(str(ticker['last']))
            except Exception:
                continue

            await self.check_position_exit(position, current_price)

    def print_status(self):
        """Print current status."""
        win_rate = (self.trades_won / self.trades_executed * 100) if self.trades_executed > 0 else 0

        status = (
            f"\r⏱️ Positions: {len(self.positions)}/{self.CONFIG['max_positions']} | "
            f"Trades: {self.trades_executed} (W:{self.trades_won} L:{self.trades_lost}) | "
            f"Win Rate: {win_rate:.1f}% | "
            f"P&L: ${float(self.total_pnl):.2f}"
        )
        print(status, end='', flush=True)

    async def run(self):
        """Main bot loop."""
        print()
        print("=" * 70)
        print("  B2 HYBRID SCALPER - ORDERFLOW + MOMENTUM")
        print("=" * 70)
        print()

        if self.CONFIG['execute_trades']:
            print("⚠️  MODE: LIVE TRADING (REAL ORDERS!)")
        else:
            print("🔄 MODE: SIMULATION (no real trades)")

        print()
        print(f"📊 Symbols: {', '.join(self.CONFIG['symbols'])}")
        print(f"💰 Order size: ${self.CONFIG['order_size_usdt']} USDT | Max positions: {self.CONFIG['max_positions']}")
        print(f"💸 Fees: {self.CONFIG['fee_per_trade_pct']}% per trade ({self.CONFIG['fee_per_trade_pct'] * 2}% round-trip)")
        print()
        print("📈 ATR-based TP/SL:")
        print(f"   TP = ATR × {self.CONFIG['atr_tp_mult']} (clamped 1.0-2.0%)")
        print(f"   SL = ATR × {self.CONFIG['atr_sl_mult']} (clamped 0.3-0.6%)")
        print()
        print("🔍 Orderflow filters:")
        print(f"   Long: imbalance ≥{self.CONFIG['min_imbalance_long']}, taker_buy ≥{self.CONFIG['min_taker_buy_ratio_long']}")
        print(f"   Short: imbalance ≤{self.CONFIG['min_imbalance_short']}, taker_buy ≤{self.CONFIG['min_taker_buy_ratio_short']}")
        print(f"   Max spread: {self.CONFIG['max_spread_bps']} bps")
        print()
        print(f"⏱️ Scan: {self.CONFIG['scan_interval']}s | Max trades/hour: {self.CONFIG['max_trades_per_hour']} | Threshold: {self.CONFIG['momentum_threshold']}")
        print()

        if not await self.init_exchange():
            return

        # Startup notification
        self.send_telegram(
            f"🚀 <b>Momentum Scalper Started</b>\n"
            f"Mode: {'LIVE' if self.CONFIG['execute_trades'] else 'Simulation'}\n"
            f"Symbols: {len(self.CONFIG['symbols'])}\n"
            f"Order size: ${self.CONFIG['order_size_usdt']}"
        )

        print("-" * 70)
        print("Bot running... Press Ctrl+C to stop")
        print("-" * 70)

        try:
            while True:
                # Scan for new signals
                await self.scan_markets()

                # Manage existing positions
                await self.manage_positions()

                # Print status
                self.print_status()

                # Wait
                await asyncio.sleep(self.CONFIG['scan_interval'])

        except KeyboardInterrupt:
            print("\n")
            print("=" * 70)
            print("  BOT STOPPED")
            print("=" * 70)
            print()
            print(f"Total trades: {self.trades_executed}")
            print(f"Won: {self.trades_won} | Lost: {self.trades_lost}")
            print(f"Win rate: {(self.trades_won / self.trades_executed * 100) if self.trades_executed > 0 else 0:.1f}%")
            print(f"Total P&L: ${float(self.total_pnl):.2f}")
            print()

            # Final notification
            self.send_telegram(
                f"🛑 <b>Momentum Scalper Stopped</b>\n"
                f"Trades: {self.trades_executed}\n"
                f"Win Rate: {(self.trades_won / self.trades_executed * 100) if self.trades_executed > 0 else 0:.1f}%\n"
                f"Total P&L: ${float(self.total_pnl):.2f}"
            )

        finally:
            await self.close_exchange()


def main():
    bot = MomentumScalperBot()
    asyncio.run(bot.run())


if __name__ == '__main__':
    main()
