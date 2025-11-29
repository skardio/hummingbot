# 🚀 Quick Start Guide - Monitoring System

## 1️⃣ Setup Telegram Bot (Optional but Recommended)

```bash
# 1. Create bot via @BotFather on Telegram
# 2. Get your chat ID via @userinfobot
# 3. Set environment variables (or use defaults in config.py):
export TELEGRAM_BOT_TOKEN="your_bot_token_here"
export TELEGRAM_CHAT_ID="your_chat_id_here"
```

## 2️⃣ Install Dependencies

```bash
cd /home/mo/repos/hummingbot
pip install flask requests
```

## 3️⃣ Start Monitoring System

### Option A: Use Start Script (Easiest) - Includes Command Handler

```bash
bash multi_coin_grid_pro/monitoring/start_monitoring.sh
```

Dit start:
- ✅ Data Collector (monitort logs)
- ✅ Dashboard (http://localhost:5000)
- ✅ Telegram Command Handler (luistert naar commands)

### Option B: Manual Start

**Terminal 1 - Data Collector:**
```bash
cd /home/mo/repos/hummingbot
python -m multi_coin_grid_pro.monitoring.collector
```

**Terminal 2 - Dashboard:**
```bash
cd /home/mo/repos/hummingbot
python -m multi_coin_grid_pro.monitoring.dashboard
```

**Terminal 3 - Telegram Command Handler:**
```bash
cd /home/mo/repos/hummingbot
python -m multi_coin_grid_pro.monitoring.telegram_bot_handler
```

## 4️⃣ Access Dashboard

Open browser: **http://localhost:5000**

## 5️⃣ Use Telegram Commands

Nu kun je commands sturen naar je Telegram bot:

- `/status` - Huidige bot status
- `/events` - Laatste 5 events
- `/events 10` - Laatste 10 events
- `/help` - Help bericht

## ✅ What You'll See

- **Dashboard**: Real-time bot status, P&L chart, recent events
- **Telegram Alerts**: Automatic alerts for stop-loss, errors, switches
- **Telegram Commands**: Interactive commands via Telegram
- **Database**: All data stored in `multi_coin_grid_pro/data/monitoring.db`

## 🔧 Troubleshooting

**Collector not starting?**
- Check log file path in `monitoring/config.py`
- Ensure bot log file exists

**Dashboard not loading?**
- Check if Flask is installed: `pip install flask`
- Check port 5000 is free: `lsof -i :5000`

**Telegram commands not working?**
- Make sure command handler is running: `ps aux | grep telegram_bot_handler`
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set
- Check handler logs: `tail -f logs/telegram_handler.log`
- Make sure you've sent `/start` to the bot first

**Telegram alerts not working?**
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set
- Test bot: `curl https://api.telegram.org/bot<TOKEN>/getMe`
- Check collector logs for Telegram errors

## 📊 Next Steps

1. Let collector run for a few minutes
2. Check dashboard for data
3. Test Telegram commands: `/status`, `/events`
4. Test Telegram alerts by triggering events
5. Customize alerts in `monitoring/config.py`
