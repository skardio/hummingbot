# Monitoring & Alerting Module

Lightweight monitoring system for the Multi-Coin Grid Bot with SQLite database, Flask dashboard, and Telegram alerts.

## 🎯 Features

- **SQLite Database**: Stores events, status snapshots, and trades
- **Data Collector**: Background service that monitors logs and collects status
- **Flask Dashboard**: Web interface on localhost:5000
- **Telegram Bot**: Alerts and commands via Telegram

## 📦 Installation

### Requirements

```bash
pip install flask requests
```

Or add to `requirements.txt`:
```
flask>=2.0.0
requests>=2.28.0
```

### Telegram Bot Setup

1. Create a Telegram bot:
   - Message [@BotFather](https://t.me/botfather) on Telegram
   - Send `/newbot` and follow instructions
   - Save the bot token

2. Get your Chat ID:
   - Message [@userinfobot](https://t.me/userinfobot) on Telegram
   - Save your chat ID

3. Set environment variables:
```bash
export TELEGRAM_BOT_TOKEN="8310424124:AAGc--tOZvhucvyfJnoKeIucm6aD9L9N1Jk"
export TELEGRAM_CHAT_ID="8586283471"
```

## 🚀 Usage

### 1. Start Data Collector

The collector runs in the background and collects data every 10 seconds:

```bash
cd /home/mo/repos/hummingbot
python -m multi_coin_grid_pro.monitoring.collector --interval 10
```

Or run as background service:
```bash
nohup python -m multi_coin_grid_pro.monitoring.collector > logs/collector.log 2>&1 &
```

### 2. Start Dashboard

Start the Flask dashboard (runs on localhost:5000):

```bash
python -m multi_coin_grid_pro.monitoring.dashboard
```

Or run as background service:
```bash
nohup python -m multi_coin_grid_pro.monitoring.dashboard > logs/dashboard.log 2>&1 &
```

Then open: http://localhost:5000

### 3. Telegram Commands

**Interactive Commands (via Telegram):**

Start the command handler:
```bash
python -m multi_coin_grid_pro.monitoring.telegram_bot_handler
```

Or use the start script (includes command handler):
```bash
bash multi_coin_grid_pro/monitoring/start_monitoring.sh
```

Then send commands to your Telegram bot:
- `/status` - Get current bot status
- `/events [N]` - Get recent events (default: 5, max: 20)
  - Example: `/events 10` - Get last 10 events
- `/help` - Show help message

**Command Line (alternative):**
```bash
python -m multi_coin_grid_pro.monitoring.telegram_bot status
python -m multi_coin_grid_pro.monitoring.telegram_bot events
```

### 4. Risk Monitor (Arbitrage Guardrail)

Continuously samples public market data via ccxt, feeds it into `ArbitrageRiskScanner`, and pushes Telegram notifications when the trade status changes.

```bash
cd /home/mo/repos/hummingbot
python -m multi_coin_grid_pro.monitoring.risk_monitor \
  --config multi_coin_grid_pro/config/risk_monitor.yaml \
  --interval 180
```

- Defaults to the config in `multi_coin_grid_pro/config/risk_monitor.yaml`
- Uses `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` env vars when the config values are `null`
- Run with `--once` for a single evaluation (useful in cron jobs)
- Safe to keep running in the background: `nohup python -m ... &`

## 📊 Dashboard Features

- **Status Cards**: Active coin, P&L, exposure, mode, latency, connection
- **P&L Chart**: 24-hour P&L history with Chart.js
- **Recent Events**: Last 20 events with event types
- **Auto-refresh**: Updates every 5 seconds

## 🔔 Alerts

The collector automatically sends Telegram alerts for:

- **Stop-loss triggered** 🛑
- **Circuit breaker activated** ⚡
- **Errors** ❌
- **API errors** ⚠️
- **Trend switches** 🔄
- **Large P&L swings** (>5% by default)

## 📁 Database

Database is stored at: `multi_coin_grid_pro/data/monitoring.db`

### Tables

1. **bot_events**: Events and errors
2. **bot_status**: Status snapshots
3. **trades**: Trade history

### Query Examples

```python
from multi_coin_grid_pro.monitoring.database import MonitoringDatabase

db = MonitoringDatabase()

# Get latest status
status = db.get_latest_status()

# Get recent events
events = db.get_recent_events(limit=30)

# Get trades today
trades = db.get_trades_today()

# Get P&L history
pnl_history = db.get_pnl_history(hours=24)
```

## ⚙️ Configuration

Edit `multi_coin_grid_pro/monitoring/config.py`:

```python
# Collector interval (seconds)
COLLECTOR_INTERVAL = 10

# Log file to monitor
LOG_FILE = "/home/mo/repos/hummingbot/logs/logs_multi_coin_grid_v2.log"

# Alert thresholds
PNL_ALERT_THRESHOLD = 5.0  # Alert if P&L swing > 5%
LATENCY_WARNING_MS = 1000.0  # Warn if latency > 1 second

# Dashboard
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 5000
```

## 🔧 Troubleshooting

### Collector not reading logs

- Check log file path in config
- Ensure log file exists and is readable
- Check collector logs: `tail -f logs/collector.log`

### Dashboard not loading

- Check if Flask is installed: `pip install flask`
- Check if port 5000 is available
- Check dashboard logs: `tail -f logs/dashboard.log`

### Telegram alerts not working

- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set
- Test bot token: `curl https://api.telegram.org/bot<TOKEN>/getMe`
- Check collector logs for Telegram errors

## 📝 Notes

- The monitoring system is lightweight and runs independently
- Database is SQLite (no server needed)
- Dashboard is localhost-only (secure by default)
- All components can run independently
