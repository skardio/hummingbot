#!/usr/bin/env python3
"""
Multi-Coin Grid Trading Bot met Automatische Trend-Based Switching

Functionaliteit:
- Monitort meerdere cryptos: XRP, ADA, DOT, SOL, LINK
- Berekent 30min trend voor elke coin
- Switcht automatisch naar de coin met de beste trend
- Ondersteunt EUR/USD via BOT_ENV (prod=EUR, usd=USD)
- Cancelt oude orders en plaatst nieuwe grid op beste coin
- Minimum 1 uur tussen switches (vermijd fee churning)
- Trade alleen coins met positieve trend (>0.5%)

Capital: €133.18 (EUR) / $110 (USD)
Fees: 0.25% maker, 0.40% taker
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import ccxt

# Logging setup - dynamic log file based on BOT_ENV
bot_env = os.getenv('BOT_ENV', 'prod').lower()
log_suffix = f"_{bot_env}" if bot_env != 'prod' else ""
log_file = f'/home/mo/repos/hummingbot/logs/multi_coin_grid{log_suffix}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file)
        # StreamHandler removed for performance - use tail -f to view logs
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"📝 Logging to: {log_file}")


@dataclass
class CoinTrend:
    """Data class voor coin trend informatie"""
    symbol: str
    current_price: Decimal
    trend_pct: float
    price_history: List[Dict]
    last_updated: float


class MultiCoinGridBot:
    """
    Multi-coin grid trading bot met automatische trend-based switching
    """

    def __init__(self):
        # Detect quote currency from BOT_ENV (prod=EUR, usd=USD)
        bot_env = os.getenv('BOT_ENV', 'prod').lower()
        self.quote_currency = 'USD' if bot_env == 'usd' else 'EUR'

        # MONITORING MODE for USD bot (no trading)
        self.monitoring_only = bot_env == 'usd'
        mode_text = "📊 MONITORING MODE (trends only)" if self.monitoring_only else "🤖 TRADING MODE"

        logger.info(f"🌍 Bot Environment: {bot_env} → Quote Currency: {self.quote_currency}")
        logger.info(f"{mode_text}")

        self.config = {
            # Coins worden automatisch opgehaald!
            'coins': [],  # Wordt gevuld door discover_tradeable_coins()
            'min_24h_volume': 50000,  # Minimaal €50k/50k$ daily volume (verlaagd!)
            'max_coins_to_monitor': 20,  # Top 20 coins (verhoogd!)
            'exclude_expensive_coins': True,  # Exclude BTC/ETH (te duur, weinig volatiliteit)

            # Trend detectie
            'trend_lookback_minutes': 30,
            'trend_min_change_pct': 0.5,  # Minimaal 0.5% stijging vereist

            # Switch management
            'min_switch_interval_seconds': 3600,  # 1 uur tussen switches
            'last_switch_time': 0,

            # Grid configuratie
            'range_pct_down': 3.0,  # -3% onder current price
            'range_pct_up': 8.0,    # +8% boven current price
            'num_grids': 3,         # 3 buy orders, 3 sell orders (voor €50 capital)

            # Fees
            'maker_fee': 0.0025,    # 0.25% maker fee
            'taker_fee': 0.0040,    # 0.40% taker fee

            # Minimum order sizes (wordt per coin opgehaald)
            'min_order_quote': {}  # Wordt gevuld door discover_tradeable_coins()
        }

        # Kraken exchange setup
        self.exchange = ccxt.kraken({
            'apiKey': os.getenv('KRAKEN_API_KEY'),
            'secret': os.getenv('KRAKEN_SECRET_KEY'),
            'enableRateLimit': True,
            'options': {
                'fetchOpenOrders': {
                    'method': 'privatePostOpenOrders'
                }
            }
        })

        # State tracking
        self.coin_trends: Dict[str, CoinTrend] = {}
        self.active_coin: Optional[str] = None
        self.open_orders: List[Dict] = []
        self.last_range_update = 0
        self.range_update_interval = 3600  # Update range elk uur

        # Grid boundaries (wordt gezet bij eerste coin selectie)
        self.grid_lower = None
        self.grid_upper = None

        logger.info("=" * 80)
        logger.info("🚀 MULTI-COIN GRID BOT GESTART")
        logger.info("=" * 80)

        # Discover tradeable coins automatisch!
        self.discover_tradeable_coins()

        logger.info(f"📊 Monitoring {len(self.config['coins'])} coins: {', '.join(self.config['coins'])}")
        logger.info(f"📈 Trend vereiste: {self.config['trend_min_change_pct']}% over {self.config['trend_lookback_minutes']}min")
        logger.info(f"⏱️  Switch cooldown: {self.config['min_switch_interval_seconds'] / 60:.0f} minuten")
        logger.info(f"💰 Fees: {self.config['maker_fee'] * 100}% maker, {self.config['taker_fee'] * 100}% taker")
        logger.info("=" * 80)

    def discover_tradeable_coins(self):
        """
        Ontdek automatisch alle tradeable pairs op Kraken (EUR of USD)
        Sorteer op 24h volume en selecteer top coins
        """
        try:
            logger.info(f"\n🔍 Discovering tradeable {self.quote_currency} pairs...")

            # Haal populaire coins dynamisch op van de exchange
            # Dit zijn de top cryptos op Kraken - meer coins voor betere diversiteit
            base_coins = [
                'BTC', 'ETH', 'SOL', 'XRP', 'ADA',
                'DOGE', 'DOT', 'AVAX', 'LINK', 'MATIC',
                'UNI', 'ATOM', 'LTC', 'BCH', 'NEAR',
                'APT', 'ARB', 'OP', 'SUI', 'ALGO',
                'FIL', 'AAVE', 'ICP', 'POLKADOT', 'RIPPLE',
                'SHIB', 'PEPE', 'MEME', 'GALA', 'ENS',
                'BNB', 'CRO', 'LINA', 'XLM', 'JUP',
                'BLUR', 'PYTH', 'WLD', 'RENDER', 'CYBER'
            ]
            priority_coins = [f"{coin}/{self.quote_currency}" for coin in base_coins]

            # Load markets
            markets = self.exchange.load_markets()

            # Filter op coins die echt bestaan en actief zijn
            available_pairs = []
            for symbol in priority_coins:
                if symbol in markets and markets[symbol]['active'] and markets[symbol]['spot']:
                    available_pairs.append(symbol)

            logger.info(f"   Checking {len(available_pairs)} populaire {self.quote_currency} pairs...")

            # Haal 24h ticker data op voor volume filtering
            coin_volumes = []
            logger.info("   📊 Ophalen 24h volumes...")

            for symbol in available_pairs:
                try:
                    ticker = self.exchange.fetch_ticker(symbol)
                    volume_quote = float(ticker.get('quoteVolume', 0))

                    # Check minimum volume
                    if volume_quote >= self.config['min_24h_volume']:
                        coin_volumes.append({
                            'symbol': symbol,
                            'volume': volume_quote,
                            'price': ticker['last']
                        })
                        currency_symbol = '€' if self.quote_currency == 'EUR' else '$'
                        logger.info(f"      ✓ {symbol:12} | Volume: {currency_symbol}{volume_quote:,.0f}")

                    time.sleep(0.2)  # Rate limit respect

                except Exception as e:
                    logger.debug(f"      ✗ Skip {symbol}: {e}")
                    continue

            # Filter dure coins (BTC/ETH) eruit als optie enabled is
            if self.config.get('exclude_expensive_coins', False):
                excluded = [f'BTC/{self.quote_currency}', f'ETH/{self.quote_currency}']
                coin_volumes = [c for c in coin_volumes if c['symbol'] not in excluded]
                logger.info(f"   🚫 Excluded BTC/ETH (te duur, weinig beweging)")

            # Sorteer op PRIJS (laagste eerst) - goedkope coins = meer volatiliteit!
            coin_volumes.sort(key=lambda x: x['price'])

            # Selecteer top N coins
            top_coins = coin_volumes[:self.config['max_coins_to_monitor']]
            self.config['coins'] = [coin['symbol'] for coin in top_coins]

            # Set minimum order sizes (gebruik markets info)
            for symbol in self.config['coins']:
                market = markets[symbol]
                # Kraken minimum is meestal 5 EUR/USD, maar check limits
                min_cost = market.get('limits', {}).get('cost', {}).get('min', 5.0)
                self.config['min_order_quote'][symbol] = float(min_cost)

            logger.info(f"\n✅ Selected top {len(self.config['coins'])} coins:")
            currency_symbol = '€' if self.quote_currency == 'EUR' else '$'
            for i, coin in enumerate(top_coins, 1):
                logger.info(
                    f"   {i}. {coin['symbol']:12} | "
                    f"Volume: {currency_symbol}{coin['volume']:>12,.0f} | "
                    f"Price: {currency_symbol}{coin['price']:.4f}"
                )

        except Exception as e:
            logger.error(f"❌ Fout bij discovering coins: {e}")
            # Fallback naar handmatige lijst
            logger.warning("⚠️  Fallback naar standaard coin lijst")
            base_coins = ['XRP', 'ADA', 'DOT', 'SOL', 'LINK']
            self.config['coins'] = [f"{coin}/{self.quote_currency}" for coin in base_coins]
            for symbol in self.config['coins']:
                self.config['min_order_quote'][symbol] = 5.0

    def get_available_quote(self) -> Decimal:
        """Haal beschikbare quote currency balance op (EUR/USD)"""
        try:
            balance = self.exchange.fetch_balance()
            quote_free = Decimal(str(balance.get(self.quote_currency, {}).get('free', 0)))
            currency_symbol = '€' if self.quote_currency == 'EUR' else '$'
            logger.info(f"💶 Beschikbare {self.quote_currency}: {currency_symbol}{quote_free:.2f}")
            return quote_free
        except Exception as e:
            logger.error(f"❌ Fout bij ophalen {self.quote_currency} balance: {e}")
            return Decimal('0')

    def update_coin_price(self, symbol: str) -> Optional[Decimal]:
        """Update prijs voor een coin en voeg toe aan history"""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            price = Decimal(str(ticker['last']))
            current_time = time.time()

            # Initialiseer trend data als nog niet bestaat
            if symbol not in self.coin_trends:
                self.coin_trends[symbol] = CoinTrend(
                    symbol=symbol,
                    current_price=price,
                    trend_pct=0.0,
                    price_history=[],
                    last_updated=current_time
                )

            # Voeg prijs toe aan history
            coin_trend = self.coin_trends[symbol]
            coin_trend.current_price = price
            coin_trend.last_updated = current_time
            coin_trend.price_history.append({
                'price': price,
                'timestamp': current_time
            })

            # Verwijder oude prijzen (ouder dan lookback period)
            lookback_seconds = self.config['trend_lookback_minutes'] * 60
            cutoff_time = current_time - lookback_seconds
            coin_trend.price_history = [
                p for p in coin_trend.price_history
                if p['timestamp'] > cutoff_time
            ]

            # Bereken trend percentage
            if len(coin_trend.price_history) >= 2:
                oldest_price = coin_trend.price_history[0]['price']
                price_change = price - oldest_price
                coin_trend.trend_pct = float(price_change / oldest_price * 100)
            else:
                coin_trend.trend_pct = 0.0

            return price

        except Exception as e:
            logger.error(f"❌ Fout bij ophalen prijs voor {symbol}: {e}")
            return None

    def update_all_coin_prices(self):
        """Update prijzen voor alle coins"""
        logger.info("\n" + "=" * 80)
        logger.info("📊 COIN TREND UPDATE")
        logger.info("=" * 80)

        for symbol in self.config['coins']:
            self.update_coin_price(symbol)

            if symbol in self.coin_trends:
                trend = self.coin_trends[symbol]
                trend_emoji = "📈" if trend.trend_pct >= 0 else "📉"
                currency_symbol = '€' if self.quote_currency == 'EUR' else '$'
                logger.info(
                    f"{trend_emoji} {symbol:12} | "
                    f"{currency_symbol}{trend.current_price:8.4f} | "
                    f"Trend: {trend.trend_pct:+6.2f}% | "
                    f"History: {len(trend.price_history)} prijzen"
                )

    def get_best_coin(self) -> Optional[str]:
        """
        Vind de coin met de beste (hoogste) trend
        Retourneert None als geen enkele coin aan minimale trend voldoet
        """
        best_symbol = None
        best_trend = self.config['trend_min_change_pct']  # Minimale drempel

        for symbol, trend in self.coin_trends.items():
            # Skip coins zonder voldoende data (minimaal 60 prijzen = 30 minuten!)
            if len(trend.price_history) < 60:
                continue

            # Check of deze coin beter is dan huidige best
            if trend.trend_pct > best_trend:
                best_trend = trend.trend_pct
                best_symbol = symbol

        if best_symbol:
            logger.info(f"\n🏆 BESTE COIN: {best_symbol} met {best_trend:+.2f}% trend")
        else:
            # Check of we genoeg data hebben
            max_history = max((len(t.price_history) for t in self.coin_trends.values()), default=0)
            if max_history < 60:
                logger.info(
                    f"\n⏳ DATA VERZAMELEN: {max_history}/60 prijzen "
                    f"({max_history * 0.5:.1f}/30 minuten) - wacht nog {30 - max_history * 0.5:.1f} min"
                )
            else:
                logger.warning(f"\n⚠️  GEEN COIN VOLDOET AAN MINIMUM TREND ({self.config['trend_min_change_pct']}%)")

        return best_symbol

    def should_switch_coin(self, best_coin: str) -> bool:
        """
        Bepaal of we moeten switchen naar een andere coin
        """
        # Als geen actieve coin, altijd switchen naar beste
        if self.active_coin is None:
            logger.info(f"✅ Geen actieve coin - switch naar {best_coin}")
            return True

        # Als beste coin hetzelfde is, niet switchen
        if best_coin == self.active_coin:
            logger.info(f"✅ {best_coin} is nog steeds de beste - geen switch nodig")
            return False

        # Check cooldown period
        time_since_last_switch = time.time() - self.config['last_switch_time']
        if time_since_last_switch < self.config['min_switch_interval_seconds']:
            remaining = self.config['min_switch_interval_seconds'] - time_since_last_switch
            logger.warning(
                f"⏰ Switch cooldown actief - nog {remaining / 60:.1f} minuten wachten"
            )
            return False

        # Alles OK - we mogen switchen
        active_trend = self.coin_trends[self.active_coin].trend_pct
        best_trend = self.coin_trends[best_coin].trend_pct
        logger.info(
            f"🔄 SWITCH VEREIST: {self.active_coin} ({active_trend:+.2f}%) → "
            f"{best_coin} ({best_trend:+.2f}%)"
        )
        return True

    def cancel_all_orders(self):
        """Cancel alle open orders voor actieve coin"""
        if not self.active_coin:
            return

        try:
            logger.info(f"\n🗑️  Canceling alle orders voor {self.active_coin}...")

            # Haal open orders op
            open_orders = self.exchange.fetch_open_orders(self.active_coin)

            if not open_orders:
                logger.info("   Geen open orders gevonden")
                return

            # Cancel elke order
            cancelled_count = 0
            currency_symbol = '€' if self.quote_currency == 'EUR' else '$'
            for order in open_orders:
                try:
                    self.exchange.cancel_order(order['id'], self.active_coin)
                    logger.info(f"   ✓ Cancelled {order['side']} order @ {currency_symbol}{order['price']:.4f}")
                    cancelled_count += 1
                except Exception as e:
                    logger.error(f"   ✗ Fout bij cancelen order {order['id']}: {e}")

            logger.info(f"✅ {cancelled_count}/{len(open_orders)} orders gecanceld")
            self.open_orders = []

        except Exception as e:
            logger.error(f"❌ Fout bij cancelen orders: {e}")

    def calculate_grid_range(self, current_price: Decimal) -> Tuple[Decimal, Decimal]:
        """
        Bereken grid range dynamisch gebaseerd op huidige prijs
        """
        lower = current_price * (Decimal('1') - Decimal(str(self.config['range_pct_down'] / 100)))
        upper = current_price * (Decimal('1') + Decimal(str(self.config['range_pct_up'] / 100)))

        currency_symbol = '€' if self.quote_currency == 'EUR' else '$'
        logger.info(f"📏 Grid range: {currency_symbol}{lower:.4f} - {currency_symbol}{upper:.4f} (huidig: {currency_symbol}{current_price:.4f})")
        return lower, upper

    def place_grid_orders(self):
        """
        Plaats grid orders voor actieve coin
        """
        # Skip if in monitoring mode
        if self.monitoring_only:
            logger.info(f"📊 MONITORING MODE: Skipping grid orders for {self.active_coin}")
            return

        if not self.active_coin:
            logger.warning("⚠️  Geen actieve coin - kan geen orders plaatsen")
            return

        try:
            # Haal huidige prijs op
            current_price = self.coin_trends[self.active_coin].current_price

            # Update range als nodig (of eerste keer)
            current_time = time.time()
            if (self.grid_lower is None or
                    current_time - self.last_range_update > self.range_update_interval):
                self.grid_lower, self.grid_upper = self.calculate_grid_range(current_price)
                self.last_range_update = current_time

            # Check of prijs nog binnen range is
            currency_symbol = '€' if self.quote_currency == 'EUR' else '$'
            if current_price <= self.grid_lower or current_price >= self.grid_upper:
                logger.warning(
                    f"⚠️  Prijs {currency_symbol}{current_price:.4f} buiten range "
                    f"{currency_symbol}{self.grid_lower:.4f}-{currency_symbol}{self.grid_upper:.4f} - herbereken range"
                )
                self.grid_lower, self.grid_upper = self.calculate_grid_range(current_price)
                self.last_range_update = current_time

            # Haal beschikbare quote currency op
            available_quote = self.get_available_quote()
            if available_quote < Decimal('20'):  # Minimaal €20/$20 voor 4 orders
                logger.warning(f"⚠️  Onvoldoende {self.quote_currency} ({currency_symbol}{available_quote:.2f}) - minimaal {currency_symbol}20 vereist")
                return

            # Gebruik maximaal €80/$85 (of minder als niet beschikbaar)
            max_capital = Decimal('85') if self.quote_currency == 'USD' else Decimal('80')
            usable_quote = min(available_quote, max_capital)

            # Verdeel capital over buy orders (helft van beschikbare quote)
            capital_per_side = usable_quote / Decimal('2')
            capital_per_order = capital_per_side / Decimal(str(self.config['num_grids']))

            # Check minimum order size
            min_order = Decimal(str(self.config['min_order_quote'][self.active_coin]))
            if capital_per_order < min_order:
                logger.warning(
                    f"⚠️  Order size te klein ({currency_symbol}{capital_per_order:.2f}) - "
                    f"minimaal {currency_symbol}{min_order:.2f} vereist. Verhoog capital of verlaag num_grids!"
                )
                return

            logger.info(f"\n📝 PLAATS GRID ORDERS voor {self.active_coin}")
            logger.info(f"   Capital per order: {currency_symbol}{capital_per_order:.2f}")
            logger.info(f"   Range: {currency_symbol}{self.grid_lower:.4f} - {currency_symbol}{self.grid_upper:.4f}")

            # Bereken buy levels (onder current price)
            buy_range = current_price - self.grid_lower
            buy_step = buy_range / Decimal(str(self.config['num_grids'] + 1))

            # Bereken sell levels (boven current price)
            sell_range = self.grid_upper - current_price
            sell_step = sell_range / Decimal(str(self.config['num_grids'] + 1))

            orders_placed = 0

            # Plaats BUY orders (lagere prijzen)
            logger.info("\n   🟢 BUY ORDERS:")
            for i in range(1, self.config['num_grids'] + 1):
                price = current_price - (buy_step * Decimal(str(i)))
                amount = capital_per_order / price

                try:
                    order = self.exchange.create_limit_buy_order(
                        self.active_coin,
                        float(amount),
                        float(price)
                    )
                    logger.info(f"   ✓ BUY  {float(amount):.4f} @ {currency_symbol}{float(price):.4f} (ID: {order['id']})")
                    self.open_orders.append(order)
                    orders_placed += 1
                    time.sleep(0.5)  # Rate limit respect
                except Exception as e:
                    logger.error(f"   ✗ Fout bij plaatsen buy order @ {currency_symbol}{float(price):.4f}: {e}")

            # Plaats SELL orders (we hebben nog geen positie, maar bereid voor)
            logger.info("\n   🔴 SELL ORDERS:")
            for i in range(1, self.config['num_grids'] + 1):
                price = current_price + (sell_step * Decimal(str(i)))
                amount = capital_per_order / price

                try:
                    order = self.exchange.create_limit_sell_order(
                        self.active_coin,
                        float(amount),
                        float(price)
                    )
                    logger.info(f"   ✓ SELL {float(amount):.4f} @ {currency_symbol}{float(price):.4f} (ID: {order['id']})")
                    self.open_orders.append(order)
                    orders_placed += 1
                    time.sleep(0.5)  # Rate limit respect
                except Exception as e:
                    logger.error(f"   ✗ Fout bij plaatsen sell order @ {currency_symbol}{float(price):.4f}: {e}")

            logger.info(f"\n✅ {orders_placed} orders geplaatst voor {self.active_coin}")

        except Exception as e:
            logger.error(f"❌ Fout bij plaatsen grid orders: {e}")

    def switch_to_coin(self, new_coin: str):
        """
        Switch naar nieuwe coin:
        1. Cancel alle orders van oude coin
        2. Update active coin
        3. Plaats grid orders voor nieuwe coin
        """
        logger.info("\n" + "=" * 80)
        logger.info(f"🔄 SWITCHING: {self.active_coin or 'NONE'} → {new_coin}")
        logger.info("=" * 80)

        # Cancel oude orders
        if self.active_coin:
            self.cancel_all_orders()

        # Update active coin
        self.active_coin = new_coin
        self.config['last_switch_time'] = time.time()

        # Reset grid boundaries zodat ze opnieuw berekend worden
        self.grid_lower = None
        self.grid_upper = None

        # Plaats nieuwe grid orders (skip if monitoring only)
        if not self.monitoring_only:
            self.place_grid_orders()
        else:
            logger.info(f"📊 MONITORING: Selected {new_coin} (no orders - monitoring mode)")

        logger.info("=" * 80)
        logger.info(f"✅ SWITCH COMPLEET - Nu actief op {new_coin}")
        logger.info("=" * 80)

    def check_and_refill_orders(self):
        """
        Check of orders nog steeds actief zijn en vul aan indien nodig
        """
        if not self.active_coin:
            return

        try:
            current_open_orders = self.exchange.fetch_open_orders(self.active_coin)

            # Als er minder dan verwacht aantal orders open zijn, refill
            expected_orders = self.config['num_grids'] * 2  # buy + sell
            actual_orders = len(current_open_orders)

            if actual_orders < expected_orders:
                logger.info(
                    f"\n🔄 REFILL NODIG: {actual_orders}/{expected_orders} orders actief"
                )
                self.cancel_all_orders()
                time.sleep(2)
                self.place_grid_orders()

        except Exception as e:
            logger.error(f"❌ Fout bij checken orders: {e}")

    def run(self):
        """
        Hoofdloop van de bot
        """
        logger.info("\n🏁 Bot hoofdloop gestart\n")

        iteration = 0

        try:
            while True:
                iteration += 1
                iteration_start = time.time()

                logger.info(f"\n{'=' * 80}")
                logger.info(f"🔁 ITERATIE #{iteration} - {datetime.now().strftime('%H:%M:%S')}")
                logger.info(f"{'=' * 80}")

                # 1. Update alle coin prijzen en trends
                self.update_all_coin_prices()

                # 2. Vind beste coin
                best_coin = self.get_best_coin()

                # 3. Check of we moeten switchen
                if best_coin:
                    if self.should_switch_coin(best_coin):
                        self.switch_to_coin(best_coin)
                else:
                    # Geen coin voldoet aan minimum trend
                    if self.active_coin:
                        logger.warning(
                            f"⚠️  Geen coin heeft voldoende trend - "
                            f"cancel orders voor {self.active_coin}"
                        )
                        self.cancel_all_orders()
                        self.active_coin = None

                # 4. Check en refill orders voor actieve coin
                if self.active_coin:
                    self.check_and_refill_orders()

                # 5. Wacht voor volgende iteratie
                # Meet hoelang deze iteratie duurde
                iteration_time = time.time() - iteration_start

                # We willen elke 30 seconden een update, dus:
                sleep_time = max(1, 30 - iteration_time)

                logger.info(f"\n💤 Iteratie duurde {iteration_time:.1f}s, wacht {sleep_time:.1f}s...")
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            logger.info("\n\n⚠️  Bot gestopt door gebruiker")
            if self.active_coin:
                logger.info("🗑️  Cleaning up - canceling alle orders...")
                self.cancel_all_orders()
        except Exception as e:
            logger.error(f"\n\n❌ FATALE FOUT: {e}")
            if self.active_coin:
                logger.info("🗑️  Emergency cleanup - canceling alle orders...")
                self.cancel_all_orders()
            raise


if __name__ == "__main__":
    bot = MultiCoinGridBot()
    bot.run()
