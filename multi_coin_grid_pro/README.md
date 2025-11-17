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
├── tests/                       # Unit & integration tests
│   ├── test_coin_discovery.py
│   ├── test_trend_calculator.py
│   └── test_controller.py
│
└── logs/                        # Log files (runtime)
```

**Architecture:**
- Built on Hummingbot Strategy V2
- Uses `GridExecutor` for order management
- Uses `TripleBarrierConfig` for risk management
- Event-driven async architecture

---

## 🎯 Development Phases

Zie `ROADMAP_TO_PRODUCTION.md` voor complete planning.

**Current Phase:** Phase 1 - Critical Risks
**Current Task:** 1.1 - Stop-Loss Mechanism
**Progress:** 0/34 tasks completed (0%)

---

## 🔧 Setup Instructions

### 1. Install Dependencies
```bash
cd /home/mo/repos/hummingbot/scripts/multi_coin_grid_pro
pip install -r requirements.txt
```

### 2. Configure
```bash
cp config/config.example.yaml config/config.dev.yaml
# Edit config.dev.yaml with your settings
```

### 3. Set API Keys
```bash
export KRAKEN_API_KEY="your_key"
export KRAKEN_SECRET_KEY="your_secret"
```

### 4. Run (Development)
```bash
python src/main.py --config config/config.dev.yaml
```

---

## 📊 Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| Stop-Loss | 🔴 TODO | Phase 1.1 |
| Circuit Breaker | 🔴 TODO | Phase 1.2 |
| Error Handling | 🔴 TODO | Phase 1.3 |
| Trend Detection | 🔴 TODO | Phase 2 |
| Grid Optimization | 🔴 TODO | Phase 4 |
| Testing | 🔴 TODO | Phase 7 |

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
