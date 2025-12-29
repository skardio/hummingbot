# Phase 4: "Why No Trade?" Reporting - User Guide

## 🎯 Overview

Phase 4 completes **US-E3: "Why No Trade?" Summary Report** met automatische hourly reports én on-demand commands.

## ⚙️ Setup

### 1. Enable Observability in Config

Voeg toe aan je bot config (bijv. `conf/conf_multi_coin_grid_v2.yml`):

```yaml
observability:
  structured_events_enabled: true
  events_output_dir: "logs/events"
  buffer_size: 100
  report_interval_minutes: 60  # Hourly reports (0 = disabled)
```

### 2. Herstart Bot

```bash
bin/hummingbot.py
```

## 📊 Automatische Reports

Als `report_interval_minutes > 0`, genereert de bot automatisch reports:

```
================================================================================
📊 WHY NO TRADE REPORT (every 60m)
================================================================================

======================================================================
[WHY-NO-TRADE SUMMARY] Last 24 hours
======================================================================
Total intents evaluated: 1154
Denied: 843 (73.1%)
Approved: 310 (26.9%)

Top Rejection Reasons:
  1. RSI_OVERBOUGHT: 434 (37.6%) [SMART_ENTRY]
  2. ATR_TOO_LOW: 214 (18.5%) [SMART_ENTRY]
  3. RSI_OVERSOLD: 80 (6.9%) [SMART_ENTRY]
  4. SLOT_FULL: 59 (5.1%) [EXECUTION]
  5. VWAP_DEVIATION_TOO_HIGH: 35 (3.0%) [SMART_ENTRY]
======================================================================
```

## 🎮 On-Demand Commands

### In Hummingbot Console:

```python
# Quick summary - last hour
>>> strategy.report_why_no_trade(hours=1)

# Last 6 hours
>>> strategy.report_why_no_trade(hours=6)

# By stage breakdown
>>> strategy.report_by_stage(hours=6)

# Top rejected symbols
>>> strategy.report_by_symbol(hours=6, top_n=10)

# Full dashboard
>>> strategy.report_full_dashboard(hours=24)
```

### Standalone Python Script:

```python
from multi_coin_grid_pro.observability.console_reporter import ConsoleReporter
from pathlib import Path

reporter = ConsoleReporter(Path('logs/events'))
reporter.report_full_dashboard(hours=24)
```

## 📈 Report Types

### 1. **Summary** (`report_why_no_trade`)
- Total intents evaluated
- Denial rate
- Top 10 rejection reasons met stage attribution

### 2. **By Stage** (`report_by_stage`)
- Rejections per pipeline stage:
  - SMART_ENTRY (entry filters)
  - MTF (multi-timeframe validation)
  - RISK (exposure/drawdown limits)
  - EXECUTION (slots/capacity)
  - REGIME (regime-based blocks)

### 3. **By Symbol** (`report_by_symbol`)
- Top N rejected coins
- Helps identify problematic pairs

### 4. **Full Dashboard** (`report_full_dashboard`)
- All reports combined
- Comprehensive view

## 🔍 Interpreting Results

### High RSI_OVERBOUGHT (>30%)
✅ **Good** - Filters werken, voorkomt buying overbought coins
**Action:** Geen actie nodig

### High ATR_TOO_LOW (>20%)
⚠️ **Low Volatility Market**
**Action:** Verlaag `min_atr` in config als je meer wilt traden

### High SLOT_FULL (>10%)
🚫 **Capacity Issue**
**Action:** Verhoog `max_simultaneous_coins` van 1 → 3

### High EXPOSURE_LIMIT (>15%)
💰 **Risk Limits Active**
**Action:** Verhoog `max_total_exposure_eur` als risico acceptable is

### High VWAP_DEVIATION_TOO_HIGH (>15%)
📊 **Price Too Far from VWAP**
**Action:** Verhoog `max_vwap_deviation_pct` voor ruimere entry window

## 📁 Data Location

Events opgeslagen in:
```
logs/events/events_YYYYMMDD_HHMMSS.jsonl
```

Elke regel is een JSON event:
```json
{
  "ts": 1766837640.152,
  "event_type": "gate_denied",
  "correlation_id": "0b36530a-6f32-4316-bae2-965ae91ec06f",
  "symbol": "BTC-EUR",
  "stage": "SMART_ENTRY",
  "reason_code": "RSI_OVERBOUGHT",
  "reason_msg": "RSI 78.3 > 70",
  "metadata": {"rsi": 78.3, "threshold": 70}
}
```

## 🛠️ Advanced Usage

### Custom Time Windows

```python
# Last 30 minutes
strategy.report_why_no_trade(hours=0.5)

# Last 3 days
strategy.report_full_dashboard(hours=72)
```

### Scheduled vs On-Demand

- **Scheduled**: Automatisch elke X minuten (config: `report_interval_minutes`)
- **On-Demand**: Manual via console commands (altijd beschikbaar)

### Disable Scheduled Reports

```yaml
observability:
  structured_events_enabled: true
  report_interval_minutes: 0  # Disabled, only on-demand
```

## 🎯 Use Cases

### 1. Debug Waarom Bot Niet Trade
```python
>>> strategy.report_why_no_trade(hours=1)
# → Zie top rejection reason (bijv. SLOT_FULL 80%)
```

### 2. Optimize Filter Settings
```python
>>> strategy.report_by_stage(hours=24)
# → Als SMART_ENTRY 90% reject, filters misschien te strikt
```

### 3. Identify Problematic Pairs
```python
>>> strategy.report_by_symbol(hours=6, top_n=5)
# → Als bepaalde coins steeds rejected, misschien blacklist
```

### 4. Capacity Planning
```python
>>> strategy.report_full_dashboard(hours=24)
# → Als SLOT_FULL hoog, verhoog max_simultaneous_coins
```

## ✅ Success Metrics

Na Phase 4 implementatie:
- ✅ 531 tests passing (519 + 12 new)
- ✅ Automatische hourly reports
- ✅ 4 on-demand report commands
- ✅ Full pipeline visibility (5/5 stages)
- ✅ Production-ready observability stack

## 📚 Related Docs

- [EventLogger API](../multi_coin_grid_pro/observability/event_logger.py)
- [ReasonCode Taxonomy](../multi_coin_grid_pro/core/reason_codes.py)
- [Demo Script](../demo_phase_4_reporting.py)
- [US-E3 Acceptance Criteria](../SMART_GRID_PROP_DESK_V1_BACKLOG.md#us-e3-why-no-trade-summary-report)

---

**Status:** ✅ Phase 4 Complete
**Last Updated:** 2025-12-27
