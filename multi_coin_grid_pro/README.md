# 🚀 Multi-Coin Grid Trading Bot - Professional Edition

**Version:** 2.0.0 - Strategy V2
**Status:** ✅ Tier 1 Complete - Ready for Testing
**Target:** Production-ready for €10,000+ capital
**Architecture:** Hummingbot Strategy V2 with GridExecutor
**Previous Version:** `../multi_coin_grid_kraken/` (v1.0 - €80 test version)

---

## 📁 Project Structure

```
multi_coin_grid_pro/
├── README.md                    # This file
├── ROADMAP_TO_PRODUCTION.md     # Complete development roadmap
├── CHANGELOG.md                 # Version history
│
├── controllers/                 # ✅ Strategy V2 Controllers
│   ├── __init__.py
│   ├── multi_coin_grid_config.py      # Configuration dataclass
│   └── multi_coin_grid_controller.py  # Main controller logic
│
├── utils/                       # ✅ Utility modules
│   ├── __init__.py
│   ├── coin_discovery.py        # Find tradeable coins
│   └── trend_calculator.py      # Trend tracking & calculation
│
├── scripts/                     # ✅ Entry points
│   └── multi_coin_grid_v2.py    # Main strategy script
│
├── conf/                        # Configuration files
│   └── multi_coin_grid.yml      # Strategy configuration
│
├── tests/                       # ✅ Unit & integration tests
│   ├── unit/                   # Unit tests
│   │   ├── test_multi_coin_grid_controller.py
│   │   └── test_multi_coin_grid_controller_extended.py
│   ├── integration/            # Integration tests
│   │   └── test_full_cycle.py
│   ├── backtest/               # Backtesting framework
│   │   ├── backtest_engine.py
│   │   └── test_backtest.py
│   ├── test_coin_discovery.py
│   ├── test_trend_calculator.py
│   └── run_unit_tests.sh
│
├── paper_trading/              # ✅ Paper trading mode
│   └── paper_trading_mode.py
│
├── config/                     # ✅ Configuration management
│   ├── config_manager.py
│   ├── config.dev.yaml
│   ├── config.test.yaml
│   └── config.prod.yaml
│
├── docs/                       # ✅ Documentation
│   ├── ARCHITECTURE.md
│   └── RUNBOOK.md
│
└── logs/                        # Log files (runtime)
```

**Architecture:**
- Built on Hummingbot Strategy V2
- Uses `GridExecutor` for order management
- Uses `TripleBarrierConfig` for risk management
- Event-driven async architecture

**See:** `docs/ARCHITECTURE.md` for detailed architecture documentation

---

## 🎯 Development Phases

Zie `ROADMAP_TO_PRODUCTION.md` voor complete planning.

**Current Phase:** Phase 7 & 8 - Testing & Production Readiness
**Progress:** 21.8/34 tasks completed (64%)
**Status:** ✅ Phase 1-4 Complete, Phase 6 Mostly Complete, Phase 7 & 8 In Progress

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
cd /home/mo/repos/hummingbot
pip install -e .
pip install -r multi_coin_grid_pro/requirements.txt
```

### 2. Configure

**Main Config File:** `config/multi_coin_grid.yml`

**Key Configuration Parameters:**
- `min_startup_wait_seconds`: Wait time before first trade (default: 3600 = 1 hour)
- `stop_loss_pct`: Stop-loss percentage (default: 0.08 = -8%)
- `total_amount_quote`: Capital per grid (default: 120 EUR)
- `use_multi_timeframe`: Enable multi-timeframe trend analysis (default: true)
- `exit_short_threshold`: Exit if 60m trend < threshold (default: -0.5%)

**Environment-Specific Configs:**
- **Development:** `config/config.dev.yaml` (default)
- **Testing:** `config/config.test.yaml` (set `BOT_ENV=test`)
- **Production:** `config/config.prod.yaml` (set `BOT_ENV=prod`)

```bash
# Set environment
export BOT_ENV=prod  # or test, prod

# Override config via environment variables (optional)
export BOT_RISK_STOP_LOSS_PCT=0.08
export BOT_GRID_TOTAL_AMOUNT_QUOTE=120
```

### 3. Set API Keys
```bash
export KRAKEN_API_KEY="your_key"
export KRAKEN_SECRET_KEY="your_secret"
```

### 4. Performance Optimizations

**Batch API Calls:**
- The bot uses batch API calls to fetch prices for all monitored coins simultaneously
- Reduces API calls from N (one per coin) to 1 (single batch call)
- Speed improvement: ~22x faster (from 44 seconds to ~2 seconds for 40 coins)
- Automatic fallback to individual calls with rate limiting if batch fails
- Respects Kraken's rate limits (1 call/second for Ticker endpoint)

**Rate Limiting:**
- Batch calls prevent rate limit warnings
- Fallback mode uses 1.1 second delay between individual calls
- Handles paper trading connectors via base connector fallback

**Warm-up Mode:**
- First 24 hours after bot start uses stricter thresholds
- 4h trend requirement: >1.5% (lowered from 2.0%)
- 1h trend requirement: >=0.3% (lowered from 0.5%)
- Both trends must be positive (no negative trends allowed)
- Prevents buying crashing coins during initial period

### 5. Run Tests

```bash
# Unit tests
./multi_coin_grid_pro/tests/run_unit_tests.sh

# Integration tests
pytest multi_coin_grid_pro/tests/integration/ -v

# Backtesting
pytest multi_coin_grid_pro/tests/backtest/ -v
```

### 5. Paper Trading (Recommended First)

```python
from multi_coin_grid_pro.paper_trading.paper_trading_mode import PaperTradingMode
from decimal import Decimal

paper = PaperTradingMode(
    initial_capital=Decimal("120"),
    config={"maker_fee_pct": 0.0016}
)

# Simulate trades
paper.simulate_buy_order("XRP-EUR", Decimal("1.5"), Decimal("80"))
```

### 6. Start Bot

```bash
# Via Hummingbot CLI
bin/hummingbot.py
>>> start --script multi_coin_grid_v2.py
```

### 7. Monitor

- **Dashboard:** http://localhost:5000 (if monitoring enabled)
- **Telegram:** Send `/status` to bot
- **Logs:** `tail -f logs/logs_multi_coin_grid_v2.log`

**See:** `docs/RUNBOOK.md` for operational guide

---

## 📊 Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| Stop-Loss | ✅ Complete | Phase 1.1 - Entry tracking, monitoring, logging |
| Circuit Breaker | ✅ Complete | Phase 1.2 - Volatility detection, pause mechanism |
| API Error Handling | ✅ Complete | Phase 1.3 - Consecutive errors, exponential backoff |
| Position Limits | ✅ Complete | Phase 1.4 - Max exposure per coin/total |
| Trend Detection | ✅ Complete | Phase 2 - EMA, LinReg, Consensus |
| Switch Logic | ✅ Complete | Phase 3 - Smart thresholds, cost calculation |
| Grid Optimization | ✅ Complete | Phase 4 - ATR ranges, volatility-based count |
| Monitoring | ✅ Mostly Complete | Phase 6 - SQLite, Flask, Telegram (88%) |
| Unit Tests | ✅ Complete | Phase 7.1 - 20 tests covering core functionality |
| Integration Tests | 🟡 In Progress | Phase 7.2 - Framework created |
| Backtesting | 🟡 In Progress | Phase 7.3 - Engine created |
| Paper Trading | 🟡 In Progress | Phase 7.4 - Mode created |
| Config Management | ✅ Complete | Phase 8.1 - Environment-specific configs |
| Documentation | ✅ Complete | Phase 8.2 - Architecture, Runbook |

---

## 🚦 Safety Checklist (Before Production)

- [ ] Stop-loss tested with 3+ scenarios
- [ ] Circuit breaker proven to work
- [ ] All error handlers tested
- [ ] Backtesting shows positive Sharpe >1.5
- [ ] Paper trading 2 weeks positive
- [ ] Live testing €100 → €500 → €2500 all profitable
- [ ] All monitoring alerts working
- [ ] Code review completed
- [ ] Documentation complete

**❌ NOT READY FOR €10k - DO NOT USE WITH LARGE CAPITAL YET**

---

## 📈 Target Performance (Once Complete)

- **Expected Return:** 3-8% per week
- **Sharpe Ratio:** >1.5
- **Win Rate:** >60%
- **Max Drawdown:** <15%
- **Uptime:** >99%

## ⚡ Performance Optimizations

### API Rate Limiting
- **Batch API Calls**: `update_all_trends_v2()` uses batch calls to fetch all prices in 1 API call instead of N calls
- **Built-in Rate Limiting**: Automatic rate limiting prevents API rate limit errors
  - `update_all_trends_v2()`: Minimum 2 seconds between batch calls
  - `_get_ticker_data_safe()`: Minimum 1.5 seconds between ticker calls
- **Speed Improvement**: ~22x faster (from 44 seconds to ~2 seconds for 40 coins)
- **Fallback**: Automatic fallback to individual calls with rate limiting if batch fails

See `CHANGELOG.md` for detailed changes.

---

## 🔗 Related Files

- **Old Version:** `../multi_coin_grid_kraken/01_multi_coin_grid_live.py`
- **Old README:** `../multi_coin_grid_kraken/README.md`
- **Roadmap:** `ROADMAP_TO_PRODUCTION.md`
- **Changelog:** `CHANGELOG.md`

---

## 📝 Notes

- Development started: 2025-11-14
- Based on expert review feedback (score 4.8/10 → target 8.5/10)
- Incremental refactoring approach (niet alles in 1x herschrijven)
- Test-driven development
- Safety first

---

## 🤝 Contributing

This is a personal trading bot. Niet bedoeld voor publieke distributie.

Voor vragen: zie ROADMAP_TO_PRODUCTION.md voor development plan.
