# 🤖 COMPLETE BOT FLOW - VAN COIN SELECTIE TOT GRID SLUITEN

## 📚 INHOUDSOPGAVE
1. [Startup & Initialisatie](#1-startup--initialisatie)
2. [Coin Discovery & Selectie](#2-coin-discovery--selectie)
3. [Trend Analyse & Ranking](#3-trend-analyse--ranking)
4. [SmartEntry Filter](#4-smartentry-filter)
5. [Grid Executor Creatie](#5-grid-executor-creatie)
6. [Order Plaatsing](#6-order-plaatsing)
7. [Order Fill Monitoring](#7-order-fill-monitoring)
8. [Grid Sluiten](#8-grid-sluiten)
9. [Control Loop](#9-control-loop)

---

## 1. STARTUP & INITIALISATIE

### Stap 1.1: Bot Start
**File**: `start_bot.sh` → `scripts/multi_coin_grid_v2.py`

```bash
#!/bin/bash
# start_bot.sh

source ~/.venvs/bot/bin/activate
export BOT_ENV=prod
python bin/hummingbot_quickstart.py --script multi_coin_grid_v2
```

### Stap 1.2: Markets Laden
**File**: `scripts/multi_coin_grid_v2.py` → `_load_markets_from_config()`

```python
@classmethod
def _load_markets_from_config(cls) -> Dict[str, set]:
    """
    Laad initiale markets voor WebSocket subscriptie

    Strategie:
    1. Probeer config te laden (whitelisted_pairs)
    2. Als niet ingesteld, gebruik dynamic discovery via REST API
    3. Fallback naar default seed pairs
    """
    env = os.environ.get("BOT_ENV", "prod")
    config_file = f"config.{env}.yaml"
    config_path = Path(__file__).parent.parent / "multi_coin_grid_pro" / "config" / config_file

    # Laad config
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Check of whitelisted_pairs is ingesteld
    pairs = config.get("whitelisted_pairs", [])

    if not pairs:
        # Geen whitelist → gebruik dynamic discovery
        print("🔍 No whitelist → using dynamic discovery")
        discovered = cls._discover_pairs_sync(config)
        return {"kraken": discovered}
    else:
        # Whitelist gevonden
        print(f"📋 Using whitelist: {len(pairs)} pairs")
        return {"kraken": set(pairs)}
```

**Wat gebeurt hier:**
1. Bot leest `config.prod.yaml`
2. Checkt `whitelisted_pairs` lijst
3. Als leeg → dynamic discovery (zie hieronder)
4. Als gevuld → gebruik die lijst

---

### Stap 1.3: Dynamic Discovery (als geen whitelist)
**File**: `scripts/multi_coin_grid_v2.py` → `_discover_pairs_sync()`

```python
@classmethod
def _discover_pairs_sync(cls, config: dict) -> set:
    """
    Ontdek beste pairs via Kraken REST API
    """
    async def fetch_and_rank():
        # Config parameters
        quote_asset = config.get("quote_asset", "EUR")
        min_volume = config.get("min_24h_volume_eur", 100000)  # €100k min
        max_pairs = config.get("max_coins_to_monitor", 25)     # Max 25 pairs
        max_spread = config.get("max_entry_spread_pct", 0.5)   # 0.5% max spread
        blacklist = set(config.get("blacklist", []))

        # Haal alle tickers op van Kraken
        async with aiohttp.ClientSession() as session:
            url = "https://api.kraken.com/0/public/Ticker"
            async with session.get(url) as response:
                data = await response.json()
                tickers = data.get("result", {})

        # Analyseer elke ticker
        pairs_data = []
        for kraken_sym, ticker in tickers.items():
            # Parse ticker data
            ask = float(ticker.get("a", [0])[0])
            bid = float(ticker.get("b", [0])[0])
            last = float(ticker.get("c", [0])[0])
            vol_24h = float(ticker.get("v", [0, 0])[1])
            open_price = float(ticker.get("o", 0))

            # Bereken metrics
            vol_eur = vol_24h * last                              # Volume in EUR
            spread = ((ask - bid) / bid * 100) if bid > 0 else 999  # Spread %
            change = ((last - open_price) / open_price * 100)     # 24h change %

            # Filter: skip als volume te laag of spread te groot
            if vol_eur < min_volume or spread > max_spread:
                continue

            # Bereken score (0-100)
            # 40% volume, 40% trend, 20% spread
            vol_score = min(100, (vol_eur / 100000) * 10)        # €100k = 10 points
            trend_score = min(100, max(0, (change + 10) * 5))    # -10% to +10% mapped
            spread_score = max(0, 100 - spread * 100)             # Lower = better
            score = vol_score * 0.4 + trend_score * 0.4 + spread_score * 0.2

            pairs_data.append({
                "symbol": symbol,
                "volume": vol_eur,
                "change": change,
                "spread": spread,
                "score": score
            })

        # Sorteer op score en pak top N
        pairs_data.sort(key=lambda x: x["score"], reverse=True)
        selected = pairs_data[:max_pairs]

        return {p["symbol"] for p in selected}

    # Run async functie
    return asyncio.run(fetch_and_rank())
```

**Output voorbeeld:**
```
🔍 Fetching all tickers from Kraken...
   Got 847 tickers from API
   Selected 25 pairs (vol>€100k, spread<0.5%)
     1. BTC-EUR: vol=€25341k, Δ+2.3%, spread=0.01%
     2. ETH-EUR: vol=€12456k, Δ+1.8%, spread=0.02%
     3. SOL-EUR: vol=€5432k, Δ+5.2%, spread=0.05%
     ...
     25. TAO-EUR: vol=€156k, Δ+0.5%, spread=0.12%
```

**Resultaat:** Bot heeft nu 25 coins om te monitoren via WebSocket

---

## 2. COIN DISCOVERY & SELECTIE

### Stap 2.1: WebSocket Streams Starten
**File**: `scripts/multi_coin_grid_v2.py` → `on_start()`

```python
async def on_start(self):
    """
    Called once when bot starts
    """
    # Hummingbot start WebSocket streams voor alle 25 pairs
    # Elke pair krijgt:
    # - Trade feed (price updates)
    # - Orderbook feed (bid/ask depth)

    # Initialize controller
    self.create_controller()
```

### Stap 2.2: Controller Initialisatie
**File**: `hummingbot/multi_coin_grid_controllers/multi_coin_grid_controller.py` → `__init__()`

```python
class MultiCoinGridController(ControllerBase):
    def __init__(self, config, *args, **kwargs):
        super().__init__(config, *args, **kwargs)

        # State tracking
        self._active_coin: Optional[str] = None       # Huidige actieve coin
        self._last_coin_switch: float = 0             # Timestamp laatste switch
        self._session_blacklist: Dict[str, float] = {} # Tijdelijk geblokkeerde coins

        # Components
        self.trend_calculator = TrendCalculator()      # Berekent trends
        self.smart_entry = SmartEntryFilter()         # Entry filter
        self.regime_detector = MarketRegimeDetector() # Detecteert bull/bear/neutral

        # Executors (grids)
        self.executors_info: Dict[str, Any] = {}     # Actieve grid executors
```

---

## 3. TREND ANALYSE & RANKING

### Stap 3.1: Control Task (Main Loop)
**File**: `multi_coin_grid_controller.py` → `control_task()`

```python
async def control_task(self):
    """
    Main control loop - draait continu elke 10 seconden
    """
    while True:
        try:
            # === STAP 1: Update Trends ===
            if self._should_update_trends():
                await self._update_trends()

            # === STAP 2: Analyseer Coins ===
            best_coin = await self._analyze_and_pick_best_coin()

            # === STAP 3: Switch of Behoud ===
            if best_coin != self._active_coin:
                await self._consider_switching_coin(best_coin)

            # === STAP 4: Monitor Actieve Grid ===
            if self._active_coin:
                await self._monitor_active_grid()

        except Exception as e:
            self.logger().error(f"Control task error: {e}")

        # Sleep 10 seconden
        await asyncio.sleep(10)
```

### Stap 3.2: Trend Update
**File**: `multi_coin_grid_controller.py` → `_update_trends()`

```python
async def _update_trends(self):
    """
    Haal candles op en bereken trends voor alle 25 coins
    """
    # Haal 5-min candles op (laatste 24 uur = 288 candles)
    for symbol in self.all_pairs:
        try:
            # Vraag candles op aan Hummingbot
            candles = await self._get_candles(
                connector="kraken",
                trading_pair=symbol,
                interval="5m",
                max_records=300  # ~24 uur
            )

            # Update trend calculator
            self.trend_calculator.update_candles(symbol, candles)

        except Exception as e:
            self.logger().warning(f"Failed to fetch candles for {symbol}: {e}")
```

### Stap 3.3: Trend Berekening
**File**: `multi_coin_grid_pro/utils/trend_calculator.py` → `calculate_consensus_trend()`

```python
class TrendCalculator:
    def calculate_consensus_trend(self, symbol: str) -> dict:
        """
        Bereken consensus trend uit meerdere timeframes

        Gebruikt GEWOGEN GEMIDDELDE van:
        - 1h trend (25% weight)
        - 4h trend (35% weight)
        - 24h trend (40% weight)
        """
        candles = self.candles[symbol]  # 288 candles van 5min

        # Bereken price changes
        current_price = candles[-1]['close']
        price_1h_ago = candles[-12]['close']   # 12 * 5min = 1h
        price_4h_ago = candles[-48]['close']   # 48 * 5min = 4h
        price_24h_ago = candles[-288]['close'] # 288 * 5min = 24h

        # Percentage changes
        trend_1h = ((current_price - price_1h_ago) / price_1h_ago * 100)
        trend_4h = ((current_price - price_4h_ago) / price_4h_ago * 100)
        trend_24h = ((current_price - price_24h_ago) / price_24h_ago * 100)

        # Gewogen consensus
        consensus = (
            trend_1h * 0.25 +   # 25% weight
            trend_4h * 0.35 +   # 35% weight
            trend_24h * 0.40    # 40% weight
        )

        return {
            "symbol": symbol,
            "consensus": consensus,
            "trend_1h": trend_1h,
            "trend_4h": trend_4h,
            "trend_24h": trend_24h,
            "candles_count": len(candles)
        }
```

**Voorbeeld output:**
```python
{
    "symbol": "PEPE-EUR",
    "consensus": 7.17,      # 7.17% weighted average
    "trend_1h": 0.20,       # +0.20% laatste uur
    "trend_4h": -0.03,      # -0.03% laatste 4 uur
    "trend_24h": 0.08,      # +0.08% laatste 24 uur
    "candles_count": 288
}
```

### Stap 3.4: Coin Ranking
**File**: `multi_coin_grid_controller.py` → `_analyze_and_pick_best_coin()`

```python
async def _analyze_and_pick_best_coin(self) -> Optional[str]:
    """
    Analyseer alle coins en kies de beste
    """
    # === STAP 1: Get Top Coins by Trend ===
    min_trend = 0.007  # 0.007% minimum trend (=0.7 basis points)

    top_coins = self.trend_calculator.get_top_n_coins(
        n=10,  # Top 10
        min_trend_pct=min_trend,
        exclude_coins=self._session_blacklist.keys()  # Skip blacklisted
    )

    if not top_coins:
        self.logger().info(f"❌ No coin found with trend >= {min_trend}%")
        return None

    # Log top coins
    self.logger().info(f"🔝 TOP 10 COINS (requested 10):")
    for i, coin_data in enumerate(top_coins[:10], 1):
        self.logger().info(
            f"  {i}. {coin_data['symbol']}: {coin_data['consensus']:+.3f}% "
            f"(24h: {coin_data['trend_24h']:+.2f}%, "
            f"4h: {coin_data['trend_4h']:+.2f}%, "
            f"1h: {coin_data['trend_1h']:+.2f}%, "
            f"{coin_data['candles_count']} points)"
        )

    # === STAP 2: Pick First Inactive Coin ===
    # Als we al 2 slots vol hebben, skip
    active_count = len([e for e in self.executors_info.values() if e.is_active])
    max_slots = 2  # Config: max 2 concurrent grids

    if active_count >= max_slots:
        self.logger().info(f"📊 Multi-coin mode: {active_count}/{max_slots} slots used - FULL")
        return None

    # Probeer eerste inactive coin
    for coin_data in top_coins:
        symbol = coin_data['symbol']

        # Check of al actief
        if symbol in [e.config.trading_pair for e in self.executors_info.values() if e.is_active]:
            continue

        # === STAP 3: SmartEntry Filter ===
        passed = await self._check_smart_entry(symbol, coin_data)

        if passed:
            self.logger().info(f"✅ Selected coin: {symbol} (consensus: {coin_data['consensus']:+.2f}%)")
            return symbol
        else:
            self.logger().warning(f"⚠️  {symbol} rejected by SmartEntry - checking next...")

    # Geen coin voldoet aan filters
    self.logger().warning(f"⚠️  All top coins rejected by SmartEntry filters")
    return None
```

**Output voorbeeld:**
```
🔝 TOP 10 COINS:
  1. DOT-EUR: +16.019% (24h: +0.22%, 4h: +0.44%, 1h: +0.00%, 956 points)
  2. CC-EUR: +15.695% (24h: +1.99%, 4h: +2.22%, 1h: +1.76%, 956 points)
  3. STBL-EUR: +12.779% (24h: +0.72%, 4h: +1.08%, 1h: +0.36%, 956 points)
  ...
🔍 Selected coin: DOT-EUR (consensus: +16.02%)
```

---

## 4. SMARTENTRY FILTER

### Stap 4.1: SmartEntry Check
**File**: `multi_coin_grid_controller.py` → `_check_smart_entry()`

```python
async def _check_smart_entry(self, symbol: str, trend_data: dict) -> bool:
    """
    Check of coin voldoet aan SmartEntry filters
    """
    # === STAP 1: Bereken Indicators ===
    candles = self.trend_calculator.get_candles(symbol)

    # Bereken RSI (14 periode)
    rsi = self._calculate_rsi(candles, period=14)

    # Bereken VWAP (Volume Weighted Average Price)
    vwap = self._calculate_vwap(candles)

    # Bereken ATR (Average True Range) in %
    atr_pct = self._calculate_atr_pct(candles, period=14)

    # Huidige prijs
    current_price = candles[-1]['close']

    # VWAP deviation
    vwap_dev_pct = abs((current_price - vwap) / vwap * 100)

    # Indicators object
    indicators = CandleIndicators(
        price=Decimal(str(current_price)),
        rsi_14=rsi,
        vwap=Decimal(str(vwap)),
        atr_pct=atr_pct,
        wick_ratio=0.0,  # Simplified
        trend_1h_pct=trend_data['trend_1h'],
        trend_4h_pct=trend_data['trend_4h'],
        trend_24h_pct=trend_data['trend_24h'],
        change_5m_pct=0.0
    )

    # === STAP 2: Load Config for This Symbol ===
    config = self._get_smart_entry_config(symbol)

    # === STAP 3: Run SmartEntry Filters ===
    result = self.smart_entry.check_entry_allowed(
        symbol=symbol,
        indicators=indicators,
        config=config
    )

    if result['allowed']:
        self.logger().info(f"✅ {symbol} PASSED SmartEntry filters")
        return True
    else:
        self.logger().warning(
            f"🔴 {symbol} REJECTED by {result['reject_reason']} | "
            f"RSI: {rsi:.2f}, VWAP dev: {vwap_dev_pct:.2f}%, ATR: {atr_pct:.2f}%"
        )
        return False
```

### Stap 4.2: SmartEntry Filter Logic
**File**: `multi_coin_grid_pro/filters/smart_entry_filter.py` → `check_entry_allowed()`

```python
class SmartEntryFilter:
    def check_entry_allowed(self, symbol: str, indicators: CandleIndicators, config: SmartEntryConfig) -> dict:
        """
        Check alle filters - return {'allowed': bool, 'reject_reason': str}
        """
        # === FILTER 1: RSI Overbought ===
        if indicators.rsi_14 > config.rsi_block_min:
            return {
                'allowed': False,
                'reject_reason': 'rsi_block',
                'details': f'RSI {indicators.rsi_14:.1f} > {config.rsi_block_min} (overbought)'
            }

        # === FILTER 2: RSI Buy Max ===
        if indicators.rsi_14 > config.rsi_buy_max:
            return {
                'allowed': False,
                'reject_reason': 'rsi_buy_max',
                'details': f'RSI {indicators.rsi_14:.1f} > {config.rsi_buy_max}'
            }

        # === FILTER 3: VWAP Deviation ===
        vwap_dev = abs((indicators.price - indicators.vwap) / indicators.vwap * 100)
        if vwap_dev > config.vwap_max_deviation_pct:
            return {
                'allowed': False,
                'reject_reason': 'vwap_deviation',
                'details': f'VWAP dev {vwap_dev:.2f}% > {config.vwap_max_deviation_pct}%'
            }

        # === FILTER 4: ATR Too Low (dead market) ===
        if indicators.atr_pct < config.min_atr_pct_for_grid:
            return {
                'allowed': False,
                'reject_reason': 'atr_min',
                'details': f'ATR {indicators.atr_pct:.2f}% < {config.min_atr_pct_for_grid}% (too low)'
            }

        # === FILTER 5: ATR Too High (too volatile) ===
        if indicators.atr_pct > config.max_atr_pct_for_grid:
            return {
                'allowed': False,
                'reject_reason': 'atr_max',
                'details': f'ATR {indicators.atr_pct:.2f}% > {config.max_atr_pct_for_grid}% (too volatile)'
            }

        # === FILTER 6: 24h Trend Too High (extended run) ===
        if indicators.trend_24h_pct > config.max_trend_24h_pct:
            return {
                'allowed': False,
                'reject_reason': 'trend_24h_max',
                'details': f'24h trend {indicators.trend_24h_pct:.2f}% > {config.max_trend_24h_pct}% (extended)'
            }

        # === ALL FILTERS PASSED ===
        return {
            'allowed': True,
            'reject_reason': None,
            'details': f'All filters passed (RSI: {indicators.rsi_14:.1f}, VWAP dev: {vwap_dev:.2f}%, ATR: {indicators.atr_pct:.2f}%)'
        }
```

**Output voorbeeld (PASSED):**
```
✅ DOT-EUR PASSED SmartEntry filters
   RSI: 50.00, VWAP dev: 3.89%, ATR: 0.07%
```

**Output voorbeeld (REJECTED):**
```
🔴 DOT-EUR REJECTED by vwap_deviation
   RSI: 50.00, VWAP dev: 3.89%, ATR: 0.07%
   Details: VWAP dev 3.89% > 2.50% (limit for DOT-EUR profile)
```

---

## 5. GRID EXECUTOR CREATIE

### Stap 5.1: Create Grid Action
**File**: `multi_coin_grid_controller.py` → `_create_grid_action()`

```python
def _create_grid_action(self, symbol: str, total_amount_quote: Optional[Decimal] = None) -> CreateExecutorAction:
    """
    Maak een CreateExecutorAction voor nieuwe grid
    """
    # === STAP 1: Get Configuration ===
    order_amount_eur = total_amount_quote or Decimal("60")  # €60 per grid

    # === STAP 1B: Story D1 - Calculate Adaptive Timeout ===
    # Bereken dynamische timeout gebaseerd op markt volatiliteit
    adaptive_timeout_sec = self.config.no_fill_timeout_sec  # Default: 600s (10 min)

    try:
        # Haal recente candle data op voor volatiliteit berekening
        candle_df = self.market_data_provider.get_candles_df(
            connector_name="kraken",
            trading_pair=symbol,
            interval="1m",  # 1-min candles voor responsiveness
            max_records=20  # 20 candles voor ATR-14 berekening
        )

        if candle_df is not None and len(candle_df) >= 14:
            # Extract OHLC data
            highs = [float(h) for h in candle_df['high'].tolist()]
            lows = [float(l) for l in candle_df['low'].tolist()]
            closes = [float(c) for c in candle_df['close'].tolist()]

            # Bereken ATR-based adaptive timeout
            from multi_coin_grid_pro.utils.adaptive_timeout import get_recommended_timeout

            timeout_result = get_recommended_timeout(
                symbol=symbol,
                current_price=float(mid_price),
                high_prices=highs,
                low_prices=lows,
                close_prices=closes,
                base_timeout_sec=self.config.no_fill_timeout_sec
            )

            adaptive_timeout_sec = timeout_result.adjusted_timeout_sec

            # Log aanpassing
            if timeout_result.adjustment_factor != 1.0:
                self.logger().info(
                    f"⏱️  Adaptive timeout voor {symbol}: "
                    f"{adaptive_timeout_sec}s (was {self.config.no_fill_timeout_sec}s, "
                    f"factor: {timeout_result.adjustment_factor:.2f}x) - "
                    f"{timeout_result.reasoning}"
                )

            # Voorbeelden:
            # - LOW volatility (<1% ATR): timeout 420s (600s * 0.7x) ← sneller stall detectie
            # - NORMAL volatility (1-3%): timeout 600s (ongewijzigd)
            # - HIGH volatility (3-6%): timeout 900s (600s * 1.5x) ← minder false timeouts
            # - EXTREME volatility (>6%): timeout 1200s (600s * 2.0x) ← maximale tolerantie

    except Exception as e:
        self.logger().warning(
            f"⚠️  Failed to calculate adaptive timeout: {e} - using base {adaptive_timeout_sec}s"
        )

    # Get coin-specific overrides
    overrides = self.config.get("coin_specific_overrides", {}).get(symbol, {})

    # Grid spacing multiplier (default 1.0)
    grid_spacing_mult = overrides.get("grid_spacing_mult", 1.0)

    # Base grid spacing in BPS (basis points)
    # 1 BPS = 0.01%, so 25 BPS = 0.25%
    base_spread_bps = 25  # 0.25% base
    spread_bps = int(base_spread_bps * grid_spacing_mult)

    # Number of grid levels (default 7)
    n_levels = overrides.get("n_levels", 7)

    # Take profit per level (0.25% default)
    take_profit = Decimal(str(overrides.get("take_profit", 0.0025)))

    # Stop loss (2.0% default)
    stop_loss = Decimal(str(overrides.get("stop_loss", 0.02)))

    # === STAP 2: Calculate Grid Levels ===
    # Start price = current mid price
    mid_price = self.market_data_provider.get_price_by_type(
        connector_name="kraken",
        trading_pair=symbol,
        price_type=PriceType.MidPrice
    )

    # Grid levels array
    grid_levels = []
    for i in range(n_levels):
        # Elk level is spread_bps lager dan vorige
        # Level 0: mid_price - 0*0.25% = mid_price
        # Level 1: mid_price - 1*0.25% = mid_price * 0.9975
        # Level 2: mid_price - 2*0.25% = mid_price * 0.9950
        # etc.
        level_price = mid_price * (1 - Decimal(str(spread_bps * i / 10000)))

        grid_levels.append({
            "level": i,
            "side": TradeType.BUY,  # We buy at grid levels
            "price": level_price,
            "amount_quote": order_amount_eur / n_levels,  # Verdeel €60 over 7 levels
            "take_profit": take_profit  # 0.25% profit per level
        })

    # === STAP 3: Create GridExecutorConfig ===
    config = GridExecutorConfig(
        timestamp=time.time(),
        connector_name="kraken",
        trading_pair=symbol,
        side=TradeType.BUY,  # We're buying

        # Grid parameters
        grid_levels=grid_levels,
        total_amount_quote=order_amount_eur,

        # Triple barrier config (take profit / stop loss)
        triple_barrier_config=TripleBarrierConfig(
            stop_loss=stop_loss,  # 2% stop loss
            take_profit=take_profit,  # 0.25% take profit per level
            time_limit=None,  # No time limit
            trailing_stop=None,  # No trailing stop
            open_order_type=OrderType.LIMIT_MAKER,  # Limit orders (maker fees)
            take_profit_order_type=OrderType.LIMIT_MAKER
        ),

        # Risk management
        max_open_orders=n_levels,  # Max 7 open orders
        cooldown_time=60,  # 60s cooldown tussen orders

        # Other settings
        leverage=1,  # Spot trading, no leverage
        activation_bounds=None,  # Start immediately

        # Story D1: Adaptive timeout (passed via custom_info)
        custom_info={
            "no_fill_timeout_sec": adaptive_timeout_sec,  # Dynamic timeout!
            "no_progress_timeout_sec": self.config.no_progress_timeout_sec,
            "max_hold_time_sec": self.config.max_hold_time_seconds,
            "close_grace_sec": self.config.close_grace_sec,
        }
    )

    # === STAP 4: Create Action ===
    return CreateExecutorAction(
        controller_id=self.config.id,
        executor_config=config
    )
```

**Grid Levels Voorbeeld (DOT-EUR @ €7.50):**
```
Grid Spacing: 0.25% (25 BPS)
Total Amount: €60
Per Level: €8.57 (€60 / 7)

Level 0: Buy @ €7.5000 (mid) = €8.57
Level 1: Buy @ €7.4813 (-0.25%) = €8.57
Level 2: Buy @ €7.4625 (-0.50%) = €8.57
Level 3: Buy @ €7.4438 (-0.75%) = €8.57
Level 4: Buy @ €7.4250 (-1.00%) = €8.57
Level 5: Buy @ €7.4063 (-1.25%) = €8.57
Level 6: Buy @ €7.3875 (-1.50%) = €8.57

Take Profit per level: +0.25%
Stop Loss: -2.0% from entry
```

### Stap 5.2: Execute Action
**File**: `hummingbot/strategy_v2/strategy_v2_base.py` → `process_action()`

```python
async def process_action(self, action: CreateExecutorAction):
    """
    Process de action en maak executor aan
    """
    # Maak GridExecutor instantie
    executor = GridExecutor(
        strategy=self,
        config=action.executor_config,
        executors_update_interval=1.0
    )

    # Start executor
    executor.start()

    # Store in executors dict
    self.executors[executor.config.id] = executor

    self.logger().info(
        f"✅ Created GridExecutor for {executor.config.trading_pair} "
        f"with {len(executor.config.grid_levels)} levels"
    )
```

---

## 6. ORDER PLAATSING

### Stap 6.1: GridExecutor Start
**File**: `hummingbot/strategy_v2/executors/grid_executor/grid_executor.py` → `start()`

```python
class GridExecutor(ExecutorBase):
    def start(self):
        """
        Start grid executor - plaats alle grid levels als orders
        """
        # Set status
        self._status = ExecutorStatus.ACTIVE

        # === STAP 1: Initialize Grid Levels ===
        self.levels = []
        for level_config in self.config.grid_levels:
            level = GridLevel(
                id=f"level_{level_config['level']}",
                side=level_config['side'],  # BUY
                price=level_config['price'],
                amount_quote=level_config['amount_quote'],
                take_profit=level_config['take_profit'],
                active_open_order=None,  # No order yet
                active_close_order=None
            )
            self.levels.append(level)

        # === STAP 2: Place All Open Orders ===
        for level in self.levels:
            self.adjust_and_place_open_order(level)

        self.logger().info(
            f"🎯 Grid started: {len(self.levels)} buy orders placed for {self.config.trading_pair}"
        )
```

### Stap 6.2: Place Open Order
**File**: `grid_executor.py` → `adjust_and_place_open_order()`

```python
def adjust_and_place_open_order(self, level: GridLevel):
    """
    Plaats een open order (buy order voor dit level)
    """
    # === STAP 1: Get Order Candidate ===
    order_candidate = self._get_open_order_candidate(level)

    # ORDER CANDIDATE EXAMPLE:
    # OrderCandidate(
    #     trading_pair='DOT-EUR',
    #     is_maker=True,
    #     order_type=OrderType.LIMIT_MAKER,
    #     order_side=TradeType.BUY,
    #     amount=1.143,  # €8.57 / €7.50 = 1.143 DOT
    #     price=Decimal('7.4813')  # Level 1 price
    # )

    # === STAP 2: Adjust Order (budget check) ===
    self.adjust_order_candidates(self.config.connector_name, [order_candidate])

    # This checks:
    # - Is er genoeg balance? (€8.57 EUR beschikbaar?)
    # - Is amount boven minimum? (1.143 DOT > 0.1 DOT min?)
    # - Adjust amount if needed

    if order_candidate.amount > 0:
        # === STAP 3: Place Order via Hummingbot ===
        order_id = self.place_order(
            connector_name="kraken",
            trading_pair="DOT-EUR",
            order_type=OrderType.LIMIT_MAKER,
            amount=Decimal("1.143"),
            price=Decimal("7.4813"),
            side=TradeType.BUY,
            position_action=PositionAction.OPEN
        )

        # === STAP 4: Track Order ===
        level.active_open_order = TrackedOrder(order_id=order_id)

        self.logger().debug(
            f"Executor ID: {self.config.id[:8]}... - "
            f"Placing open order {order_id}: "
            f"BUY 1.143 DOT @ €7.4813"
        )
```

### Stap 6.3: Kraken API Call
**File**: `hummingbot/connector/exchange/kraken/kraken_exchange.py` → `buy()`

```python
def buy(
    self,
    trading_pair: str,
    amount: Decimal,
    order_type: OrderType,
    price: Decimal,
) -> str:
    """
    Place buy order on Kraken
    """
    # Convert to Kraken format
    kraken_symbol = self._convert_to_kraken_symbol(trading_pair)  # DOT-EUR → DOTEUR

    # Build order params
    params = {
        "pair": kraken_symbol,
        "type": "buy",
        "ordertype": "limit",  # Limit order
        "price": str(price),   # "7.4813"
        "volume": str(amount),  # "1.143"
        "oflags": "post",  # Post-only (maker fee)
        "userref": self._generate_client_order_id()
    }

    # Send to Kraken API
    response = await self._api_request(
        method="POST",
        path_url="/0/private/AddOrder",
        params=params,
        is_auth_required=True
    )

    # Parse response
    # {
    #   "error": [],
    #   "result": {
    #     "descr": {"order": "buy 1.143 DOTEUR @ limit 7.4813"},
    #     "txid": ["O5KS54-4VDGB-XIOMRK"]  ← Order ID
    #   }
    # }

    order_id = response["result"]["txid"][0]

    # Store in tracking
    self._in_flight_orders[order_id] = InFlightOrder(
        client_order_id=order_id,
        exchange_order_id=order_id,
        trading_pair=trading_pair,
        order_type=order_type,
        trade_type=TradeType.BUY,
        amount=amount,
        price=price,
        creation_timestamp=time.time()
    )

    self.logger().info(
        f"✅ Order placed on Kraken: "
        f"BUY 1.143 DOT @ €7.4813 (order_id: {order_id})"
    )

    return order_id
```

**Kraken Response:**
```json
{
  "error": [],
  "result": {
    "descr": {
      "order": "buy 1.143 DOTEUR @ limit 7.4813"
    },
    "txid": ["O5KS54-4VDGB-XIOMRK"]
  }
}
```

**Nu staat order in Kraken orderbook!**

---

## 7. ORDER FILL MONITORING

### Stap 7.1: WebSocket Update
**File**: `kraken_exchange.py` → `_process_user_stream_event()`

```python
async def _process_user_stream_event(self, event):
    """
    Process WebSocket update van Kraken
    """
    # Kraken stuurt trade fills via WebSocket
    # {
    #   "event": "fill",
    #   "orderId": "O5KS54-4VDGB-XIOMRK",
    #   "pair": "DOTEUR",
    #   "price": "7.4813",
    #   "volume": "1.143",
    #   "fee": "0.0002",
    #   "tradeId": "T5JPMN-6LN3C-SHTRNU"
    # }

    if event.get("event") == "fill":
        order_id = event["orderId"]
        trade_id = event["tradeId"]

        # Parse fill data
        fill_price = Decimal(event["price"])
        fill_amount = Decimal(event["volume"])
        fee_amount = Decimal(event["fee"])

        # Trigger OrderFilledEvent
        self.trigger_event(
            MarketEvent.OrderFilled,
            OrderFilledEvent(
                timestamp=time.time(),
                order_id=order_id,
                trading_pair="DOT-EUR",
                trade_type=TradeType.BUY,
                order_type=OrderType.LIMIT_MAKER,
                price=fill_price,  # €7.4813
                amount=fill_amount,  # 1.143 DOT
                trade_fee=TradeFeeBase(
                    percent=Decimal("0"),
                    flat_fees=[TradeFeeSchema(
                        token="EUR",
                        amount=fee_amount  # €0.0002
                    )]
                ),
                exchange_trade_id=trade_id,
                exchange_order_id=order_id
            )
        )
```

### Stap 7.2: GridExecutor Handles Fill
**File**: `grid_executor.py` → `process_order_filled_event()`

```python
def process_order_filled_event(self, _, market, event: OrderFilledEvent):
    """
    Order is filled! Nu actie ondernemen
    """
    # === STAP 1: Find Which Level Was Filled ===
    filled_level = None
    for level in self.levels:
        if level.active_open_order and level.active_open_order.order_id == event.order_id:
            filled_level = level
            break

    if not filled_level:
        return  # Not our order

    # === STAP 2: Update Level State ===
    filled_level.active_open_order.executed_amount_base = event.amount  # 1.143 DOT
    filled_level.active_open_order.average_executed_price = event.price  # €7.4813
    filled_level.active_open_order.cum_fees_quote = event.trade_fee.flat_fees[0].amount  # €0.0002
    filled_level.active_open_order.is_filled = True

    self.logger().info(
        f"✅ FILL: Level {filled_level.id} - "
        f"Bought 1.143 DOT @ €7.4813 (fee: €0.0002)"
    )

    # === STAP 3: Calculate Take Profit Price ===
    entry_price = event.price  # €7.4813
    take_profit_pct = filled_level.take_profit  # 0.0025 (0.25%)
    take_profit_price = entry_price * (Decimal("1") + take_profit_pct)  # €7.4813 * 1.0025 = €7.5000

    # === STAP 4: Place Close Order (Sell) ===
    self.adjust_and_place_close_order(filled_level)

    # This places a SELL order at €7.5000 for 1.143 DOT
    # When this fills, we make 0.25% profit!
```

### Stap 7.3: Place Close Order
**File**: `grid_executor.py` → `adjust_and_place_close_order()`

```python
def adjust_and_place_close_order(self, level: GridLevel):
    """
    Plaats close order (sell order om winst te nemen)
    """
    # === STAP 1: Calculate Take Profit Price ===
    take_profit_price = self.get_take_profit_price(level)
    # €7.4813 * 1.0025 = €7.5000

    # === STAP 2: Apply GUARDRAILS (NEW!) ===
    # GUARDRAIL A: Never sell below breakeven
    entry_price = level.price  # €7.4813
    fee_buffer = Decimal("0.0010")  # 0.10%
    min_profit = Decimal("0.0015")  # 0.15%
    min_acceptable_price = entry_price * (1 + fee_buffer + min_profit)
    # €7.4813 * 1.0025 = €7.5000

    if take_profit_price < min_acceptable_price:
        self.logger().warning(
            f"⚠️ GUARDRAIL: Would sell below breakeven! "
            f"Adjusting from €{take_profit_price} to €{min_acceptable_price}"
        )
        take_profit_price = min_acceptable_price

    # === STAP 3: Get Order Candidate ===
    order_candidate = OrderCandidate(
        trading_pair="DOT-EUR",
        is_maker=True,
        order_type=OrderType.LIMIT_MAKER,
        order_side=TradeType.SELL,
        amount=Decimal("1.143"),  # Sell what we bought
        price=take_profit_price   # €7.5000
    )

    # === STAP 4: Adjust (balance check) ===
    self.adjust_order_candidates(self.config.connector_name, [order_candidate])

    # Check: Do we have 1.143 DOT available?

    if order_candidate.amount > 0:
        # === STAP 5: Place Sell Order ===
        order_id = self.place_order(
            connector_name="kraken",
            trading_pair="DOT-EUR",
            order_type=OrderType.LIMIT_MAKER,
            amount=Decimal("1.143"),
            price=Decimal("7.5000"),
            side=TradeType.SELL,
            position_action=PositionAction.CLOSE
        )

        # === STAP 6: Track Close Order ===
        level.active_close_order = TrackedOrder(order_id=order_id)

        self.logger().info(
            f"🎯 CLOSE ORDER placed: "
            f"SELL 1.143 DOT @ €7.5000 (take profit)"
        )
```

**Nu hebben we:**
- ✅ Buy order filled @ €7.4813
- ✅ Sell order placed @ €7.5000
- ✅ Profit potential: €0.0187 (0.25%)

---

## 8. GRID SLUITEN

### Stap 8.0: Story B2 - Audit Record Creatie
**File**: `multi_coin_grid_controller.py` → `_on_executor_terminated()`

```python
def _on_executor_terminated(self, executor):
    """
    Wanneer executor stopt, schrijf audit record voor analytics
    """
    # === Story B2: Write Execution Audit ===
    from multi_coin_grid_pro.models.execution_audit import (
        AuditWriter, create_audit_from_executor
    )

    try:
        # Bepaal close reason
        close_reason_map = {
            CloseType.TAKE_PROFIT: "TAKE_PROFIT",
            CloseType.STOP_LOSS: "STOP_LOSS",
            CloseType.TIMEOUT: "TIMEOUT",
            CloseType.USER_STOP: "USER_STOP",
            CloseType.EARLY_STOP: "EARLY_STOP"
        }
        close_reason = close_reason_map.get(executor.close_type, "UNKNOWN")

        # Maak audit record
        audit = create_audit_from_executor(executor, close_reason)

        # Audit bevat:
        # - symbol: "DOT-EUR"
        # - executor_id: "abc123..."
        # - start_ts: 1735574400.0 (Unix timestamp)
        # - end_ts: 1735578000.0
        # - duration_sec: 3600.0 (1 uur)
        # - close_reason: "TAKE_PROFIT"
        # - realized_pnl_quote: "8.57" (bruto winst)
        # - fees_quote: "0.04" (totale fees)
        # - net_pnl_quote: "8.53" (netto winst)
        # - num_fills: 14 (7 buys + 7 sells)
        # - num_open_fills: 7
        # - num_close_fills: 7
        # - time_to_first_fill_sec: 78.5 (eerste fill na 78s)
        # - timeout_triggered: False
        # - timeout_type: None
        # - unwind_phase_reached: None
        # - graceful_close_success: True
        # - config_snapshot: {grid config dict}
        # - version: "1.0"
        # - recorded_at: "2025-12-30T14:30:00.123456"

        # Schrijf naar JSONL file (audits/2025-12-30.jsonl)
        writer = AuditWriter(audit_dir="audits")
        writer.write(audit)

        self.logger().info(
            f"📊 Audit written: {executor.config.trading_pair} - "
            f"PNL: €{audit.net_pnl_quote} ({audit.close_reason})"
        )

    except Exception as e:
        self.logger().error(f"Failed to write audit: {e}")
```

**Audit File Format (JSONL):**
```json
{"version":"1.0","symbol":"DOT-EUR","executor_id":"abc123","start_ts":1735574400.0,"end_ts":1735578000.0,"duration_sec":3600.0,"close_reason":"TAKE_PROFIT","close_type_priority":1,"realized_pnl_quote":"8.57","fees_quote":"0.04","net_pnl_quote":"8.53","num_fills":14,"num_open_fills":7,"num_close_fills":7,"num_closed_levels":7,"time_to_first_fill_sec":78.5,"time_to_last_fill_sec":3521.0,"time_in_graceful_unwind_sec":0.0,"time_in_aggressive_unwind_sec":0.0,"timeout_triggered":false,"timeout_type":null,"unwind_phase_reached":null,"graceful_close_success":true,"max_adverse_excursion":"0.0","max_favorable_excursion":"0.0","max_position_size_quote":"60.0","config_snapshot":{},"recorded_at":"2025-12-30T14:30:00.123456"}
{"version":"1.0","symbol":"TAO-EUR","executor_id":"def456","start_ts":1735578000.0,...}
```

### Stap 8.0B: Story C2 - Metrics Analysis
**File**: `multi_coin_grid_pro/utils/metrics_calculator.py`

```python
from multi_coin_grid_pro.utils.metrics_calculator import MetricsCalculator

# Na een week trading, analyseer performance
calculator = MetricsCalculator(audit_dir="audits")

# Bereken metrics voor laatste 7 dagen
metrics = calculator.calculate_period_metrics(
    days=7,
    end_date=datetime.strptime("2025-12-30", "%Y-%m-%d"),
    by_symbol=True  # Breakdown per coin
)

# Metrics object bevat:
print(f"Total Executions: {metrics.total_executions}")  # 143
print(f"Total PNL: €{metrics.total_pnl_net}")  # €1247.35
print(f"Win Rate: {metrics.win_rate:.1f}%")  # 87.4%
print(f"Timeout Rate: {metrics.timeout_rate:.1f}%")  # 3.5%
print(f"Avg Time to First Fill: {metrics.avg_time_to_first_fill_sec:.0f}s")  # 124s
print(f"Median Time to First Fill: {metrics.median_time_to_first_fill_sec:.0f}s")  # 89s
print(f"P95 Time to First Fill: {metrics.p95_time_to_first_fill_sec:.0f}s")  # 312s
print(f"PNL per Hour: €{metrics.pnl_per_hour:.2f}")  # €8.72/hour
print(f"Graceful Unwind Rate: {metrics.graceful_vs_aggressive_rate:.1f}%")  # 94.2%
print(f"Avg Fills per Execution: {metrics.avg_fills_per_execution:.1f}")  # 13.8

# Per-symbol breakdown
for symbol, symbol_metrics in metrics.by_symbol_metrics.items():
    print(f"\n{symbol}:")
    print(f"  Executions: {symbol_metrics['total_executions']}")
    print(f"  Net PNL: €{symbol_metrics['total_pnl_net']}")
    print(f"  Win Rate: {symbol_metrics['win_rate']:.1f}%")
    print(f"  Avg Duration: {symbol_metrics['avg_duration_sec']/60:.1f} min")

# Export naar CSV voor analyse
calculator.export_to_csv(metrics, "metrics_report_2025-12-30.csv")

# Export naar JSON voor dashboards
calculator.export_to_json(metrics, "metrics_report_2025-12-30.json")
```

**Output Voorbeeld:**
```
Total Executions: 143
Total PNL: €1247.35
Win Rate: 87.4%
Timeout Rate: 3.5%
Avg Time to First Fill: 124s
Median Time to First Fill: 89s
P95 Time to First Fill: 312s
PNL per Hour: €8.72
Graceful Unwind Rate: 94.2%
Avg Fills per Execution: 13.8

DOT-EUR:
  Executions: 45
  Net PNL: €387.52
  Win Rate: 91.1%
  Avg Duration: 58.3 min

TAO-EUR:
  Executions: 38
  Net PNL: €324.18
  Win Rate: 86.8%
  Avg Duration: 52.1 min

...
```

**Key Insights:**
- **Time to First Fill** metrics help tune timeout settings
- **Timeout Rate** shows if adaptive timeout is working (target: <5%)
- **Win Rate** validates coin selection and SmartEntry filters
- **PNL per Hour** measures efficiency
- **Per-symbol breakdown** identifies best/worst performers

### Scenario 8.1: Take Profit Hit (HAPPY PATH)

**Stap 1: Sell Order Fills**
```python
# Kraken WebSocket trigger:
OrderFilledEvent(
    order_id="O2KNON-JPKRF-ETRDPV",  # Sell order
    trading_pair="DOT-EUR",
    trade_type=TradeType.SELL,
    price=Decimal("7.5000"),  # Filled at take profit!
    amount=Decimal("1.143"),
    trade_fee=fee
)
```

**Stap 2: GridExecutor Handles Sell Fill**
```python
def process_order_filled_event(self, _, market, event: OrderFilledEvent):
    # Find level with this close order
    for level in self.levels:
        if level.active_close_order and level.active_close_order.order_id == event.order_id:
            # Mark as filled
            level.active_close_order.is_filled = True
            level.status = GridLevelStatus.CLOSED

            # Calculate P&L
            buy_cost = level.active_open_order.average_executed_price * level.active_open_order.executed_amount_base
            buy_fee = level.active_open_order.cum_fees_quote
            sell_revenue = event.price * event.amount
            sell_fee = event.trade_fee.flat_fees[0].amount

            pnl = (sell_revenue - sell_fee) - (buy_cost + buy_fee)
            # €8.5725 - €0.0002 - (€8.5542 + €0.0002) = €0.0179

            self.logger().info(
                f"✅ PROFIT TAKEN: Level {level.id} - "
                f"P&L: €{pnl:.4f} (+0.25%)"
            )

            # Check if all levels closed
            if all(level.status == GridLevelStatus.CLOSED for level in self.levels):
                self._status = ExecutorStatus.COMPLETED
                self.logger().info("🎉 Grid completed - all levels profitable!")
```

### Scenario 8.2: Stop Loss Hit (LOSS PATH)

**Stap 1: Price Drops Below Stop Loss**
```python
async def control_task(self):
    """
    GridExecutor control loop checks stop loss elke seconde
    """
    while self.is_active:
        # Check current price
        mid_price = self.market_data_provider.get_price_by_type(
            connector_name="kraken",
            trading_pair="DOT-EUR",
            price_type=PriceType.MidPrice
        )

        # Voor elk level met open positie
        for level in self.levels:
            if level.active_open_order and level.active_open_order.is_filled:
                entry_price = level.active_open_order.average_executed_price  # €7.4813
                stop_loss_pct = self.config.triple_barrier_config.stop_loss  # 0.02 (2%)
                stop_loss_price = entry_price * (1 - stop_loss_pct)  # €7.3317

                # Check if stop loss triggered
                if mid_price <= stop_loss_price:
                    self.logger().warning(
                        f"⚠️ STOP LOSS TRIGGERED for level {level.id}! "
                        f"Price €{mid_price:.4f} <= Stop €{stop_loss_price:.4f}"
                    )

                    # Cancel take profit order
                    if level.active_close_order:
                        self.cancel_order(level.active_close_order.order_id)

                    # Place market sell order
                    self.place_close_order_and_cancel_open_orders(
                        close_type=CloseType.STOP_LOSS,
                        price=mid_price  # Market price
                    )

        await asyncio.sleep(1)
```

**Stap 2: Emergency Close**
```python
def place_close_order_and_cancel_open_orders(self, close_type: CloseType, price: Decimal):
    """
    Emergency close - plaats market order
    """
    # Cancel all open orders
    for level in self.levels:
        if level.active_open_order and not level.active_open_order.is_filled:
            self.cancel_order(level.active_open_order.order_id)

    # Place market sell for all filled positions
    total_amount = sum(
        level.active_open_order.executed_amount_base
        for level in self.levels
        if level.active_open_order and level.active_open_order.is_filled
    )

    if total_amount > 0:
        # MARKET ORDER (not limit!)
        order_id = self.place_order(
            connector_name="kraken",
            trading_pair="DOT-EUR",
            order_type=OrderType.MARKET,  # Market order = instant fill
            amount=total_amount,
            price=price,  # For market orders, price is just reference
            side=TradeType.SELL,
            position_action=PositionAction.CLOSE
        )

        self.logger().warning(
            f"🚨 STOP LOSS ORDER: SELL {total_amount} DOT at market (est. €{price:.4f})"
        )

        # Mark as closed
        self._status = ExecutorStatus.CLOSED_BY_STOP_LOSS
        self.close_timestamp = time.time()
        self.close_type = CloseType.STOP_LOSS
```

### Scenario 8.3: Manual Stop (User Command)

```python
# User types in Hummingbot console:
# > stop --controller-id abc123

async def stop(self, controller_id: str):
    """
    Manually stop a controller and all its executors
    """
    controller = self.controllers.get(controller_id)

    if controller:
        # Stop all executors
        for executor in controller.executors_info.values():
            if executor.is_active:
                # Place market close orders
                executor.place_close_order_and_cancel_open_orders(
                    close_type=CloseType.USER_STOP,
                    price=executor.mid_price
                )

        # Stop controller
        controller.stop()

        self.logger().info(f"✅ Controller {controller_id[:8]}... stopped by user")
```

---

## 9. CONTROL LOOP

### Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    CONTROL TASK (10s loop)                  │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
        ┌──────────────────────┐
        │  1. Update Trends    │
        │  (every 30s)         │
        └──────────┬───────────┘
                   │
                   ▼
        ┌──────────────────────┐
        │  2. Rank Coins       │
        │  (get top 10)        │
        └──────────┬───────────┘
                   │
                   ▼
        ┌──────────────────────┐
        │  3. Check Active     │
        │     Slots            │
        └──────────┬───────────┘
                   │
                   ├─ Slots full? ──► Continue monitoring
                   │
                   ├─ Slots available?
                   │          │
                   │          ▼
                   │   ┌─────────────────┐
                   │   │ 4. Pick Best    │
                   │   │    Inactive     │
                   │   └────────┬────────┘
                   │            │
                   │            ▼
                   │   ┌─────────────────┐
                   │   │ 5. SmartEntry   │
                   │   │    Filter       │
                   │   └────────┬────────┘
                   │            │
                   │            ├─ Passed? ──► Create Grid
                   │            │
                   │            └─ Failed? ──► Try next coin
                   │
                   ▼
        ┌──────────────────────┐
        │  6. Monitor Active   │
        │     Grids            │
        └──────────┬───────────┘
                   │
                   ├─ Check Stop Loss
                   ├─ Check Take Profit
                   ├─ Check Trend Reversal
                   │
                   ▼
        ┌──────────────────────┐
        │  7. Sleep 10s        │
        └──────────────────────┘
                   │
                   └──► LOOP
```

### Timing Overview

```
Time      Action
────────────────────────────────────────────────────
00:00     Bot starts
00:00     - Load config
00:01     - Discover 25 pairs via REST API
00:05     - WebSocket streams connected
00:10     - First trend update (fetch 24h candles)
00:10     - Rank coins → DOT-EUR best
00:10     - SmartEntry check → PASSED
00:10     - Story D1: Calculate adaptive timeout (ATR 0.8% → NORMAL → 600s)
00:10     - Create GridExecutor (with dynamic timeout)
00:11     - Place 7 buy orders

...waiting for fills...

01:23     - Level 2 buy fills @ €7.4625
01:23     - Place sell order @ €7.4813 (+0.25%)

...waiting...

02:45     - Level 2 sell fills @ €7.4813
02:45     - P&L: +€0.0179 (0.25%)
02:45     - Level 2 closed ✅

...continue monitoring other levels...

04:30     - All 7 levels closed
04:30     - Grid completed
04:30     - Total P&L: +€0.13 (0.25% avg)
04:30     - Story B2: Write audit record (audits/2025-12-30.jsonl)
04:30     - Audit: symbol=DOT-EUR, pnl=€0.13, duration=14100s, fills=14

04:40     - Next control loop
04:40     - Check if DOT still best
04:40     - If yes: create new grid
04:40     - If no: switch to TAO-EUR
```

---

## SAMENVATTING

**Hele flow in vogelvlucht:**

1. **Startup** → Load 25 coins via REST API
2. **Control Loop** (10s) → Update trends, rank coins
3. **Coin Selection** → Pick top coin that passes SmartEntry
4. **Grid Creation** → Create 7 buy orders with 0.25% spacing
5. **Fill Monitoring** → Wait for buys to fill
6. **Take Profit** → When buy fills, place sell order
7. **Close** → When sell fills, take 0.25% profit
8. **Repeat** → Check if same coin still best, or switch

**Key Points:**
- ✅ Guardrails prevent selling below entry price
- ✅ SmartEntry filters ensure good timing
- ✅ Grid levels spread risk (€60 / 7 = €8.57 per level)
- ✅ 0.25% take profit per level
- ✅ 2% stop loss for risk management
- ✅ **Story D1**: Adaptive timeout based on volatility (0.7x - 2.0x multiplier)
- ✅ **Story B2**: Audit trail for every execution (JSONL format)
- ✅ **Story C2**: KPI metrics and performance analysis

**Files Involved:**
- `scripts/multi_coin_grid_v2.py` - Main strategy
- `multi_coin_grid_controller.py` - Control logic
- `grid_executor.py` - Order management
- `trend_calculator.py` - Trend analysis
- `smart_entry_filter.py` - Entry filters
- `kraken_exchange.py` - Exchange integration
- **Story D1**: `adaptive_timeout.py` - Dynamic timeout based on ATR volatility
- **Story B2**: `execution_audit.py` - Audit record creation and JSONL writing
- **Story C2**: `metrics_calculator.py` - KPI calculation and performance analysis

Heb je specifieke vragen over een bepaald deel?
