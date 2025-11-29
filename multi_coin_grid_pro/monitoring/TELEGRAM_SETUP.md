# 📱 Telegram Bot Setup & Testing

## Hoe werkt de Telegram Bot?

De Telegram bot heeft **twee functies**:

### 1. **Automatische Alerts** (via Collector)
De collector stuurt automatisch alerts wanneer belangrijke events gebeuren:
- 🛑 Stop-loss getriggerd
- ⚡ Circuit breaker geactiveerd
- ❌ Errors
- ⚠️ API errors
- 🔄 Trend switches
- 📊 Grote P&L swings (>5%)

### 2. **Handmatige Commands** (via Telegram of CLI)
Je kunt handmatig status opvragen:
- `/status` - Huidige bot status
- `/events` - Recente events

## 🚀 Quick Test

### Stap 1: Test de Bot

```bash
cd /home/mo/repos/hummingbot
python multi_coin_grid_pro/monitoring/test_telegram.py
```

Dit stuurt 4 test berichten naar je Telegram.

### Stap 2: Check Telegram

Open je Telegram app en kijk of je de berichten hebt ontvangen.

### Stap 3: Test via Command Line

```bash
# Send status
python -m multi_coin_grid_pro.monitoring.telegram_bot status

# Send events
python -m multi_coin_grid_pro.monitoring.telegram_bot events
```

## 🔧 Hoe werkt het technisch?

### Automatische Alerts

1. **Collector draait** elke 10 seconden
2. **Leest bot logs** en detecteert events
3. **Bij kritieke events** → stuurt Telegram alert
4. **Bij P&L swings** → stuurt alert als >5%

### Handmatige Commands

1. **Via CLI**: Run `telegram_bot.py` met command
2. **Via Telegram**: (Nog niet geïmplementeerd - kan later toegevoegd worden)

## 📝 Configuratie

De bot credentials staan in:
- `monitoring/config.py` (defaults)
- Environment variables (override)

```bash
# Option 1: Environment variables (aanbevolen)
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# Option 2: Direct in config.py (minder veilig)
# Edit monitoring/config.py
```

## 🧪 Test Scenarios

### Test 1: Simple Message
```python
from multi_coin_grid_pro.monitoring.telegram_bot import TelegramBot
from multi_coin_grid_pro.monitoring.database import MonitoringDatabase

db = MonitoringDatabase()
bot = TelegramBot(
    bot_token="your_token",
    chat_id="your_chat_id",
    db=db
)

bot.send_message("Test message!")
```

### Test 2: Alert
```python
bot.send_alert(
    event_type="stop_loss",
    message="Stop-loss triggered on FIL-EUR at -8%",
    coin="FIL-EUR"
)
```

### Test 3: Status
```python
bot.send_status()
```

## ⚠️ Troubleshooting

### Geen berichten ontvangen?

1. **Check bot token**:
   ```bash
   curl https://api.telegram.org/bot<TOKEN>/getMe
   ```
   Moet `"ok":true` teruggeven

2. **Check chat ID**:
   - Stuur een bericht naar je bot
   - Check: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Zoek je `chat.id` in de response

3. **Check bot is gestart**:
   - Je moet eerst een bericht naar de bot sturen
   - Dan kan de bot naar jou sturen

4. **Check logs**:
   ```bash
   tail -f logs/collector.log | grep -i telegram
   ```

### Bot werkt niet?

- **Token incorrect**: Check token bij @BotFather
- **Chat ID incorrect**: Check via getUpdates API
- **Bot niet gestart**: Stuur eerst een bericht naar de bot
- **Network issues**: Check internet connectie

## 📊 Integratie met Collector

De collector gebruikt automatisch de Telegram bot als deze is geconfigureerd:

```python
# In collector.py
if MonitoringConfig.TELEGRAM_BOT_TOKEN and MonitoringConfig.TELEGRAM_CHAT_ID:
    telegram_bot = TelegramBot(...)
    collector = DataCollector(..., telegram_bot=telegram_bot)
```

Bij elke kritieke event wordt automatisch een alert gestuurd!

## 🎯 Volgende Stappen

1. ✅ Test de bot met `test_telegram.py`
2. ✅ Start collector met Telegram alerts
3. ✅ Monitor alerts in Telegram
4. 🔜 (Optioneel) Voeg Telegram command handler toe voor interactieve commands
