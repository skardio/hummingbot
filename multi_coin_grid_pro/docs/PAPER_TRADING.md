# 📝 Paper Trading Mode

## Wat is Paper Trading?

Paper trading is een simulatie modus waarbij de bot handelt zonder echt geld te gebruiken. Alle orders worden gesimuleerd, maar de bot gedraagt zich verder precies hetzelfde als bij live trading.

## Voordelen

- ✅ **Geen risico**: Test je strategie zonder geld te verliezen
- ✅ **Realistische simulatie**: Gebruikt echte marktdata en prijzen
- ✅ **Leren**: Begrijp hoe de bot werkt voordat je echt geld gebruikt
- ✅ **Debuggen**: Test fixes en nieuwe features veilig

## Hoe te activeren

### Optie 1: Via Config File (Aanbevolen)

Voeg `paper_trading: true` toe aan je config file:

**`multi_coin_grid_pro/config/config.dev.yaml`:**
```yaml
# Exchange Configuration
connector_name: kraken
quote_asset: EUR

# Paper Trading Mode
paper_trading: true  # Enable paper trading for testing
```

### Optie 2: Via Environment Variable

```bash
export MULTI_COIN_GRID_PAPER_TRADING=true
```

## Hoe het werkt

1. **Connector naam**: Wanneer paper trading is ingeschakeld, wordt de connector naam automatisch aangepast:
   - `kraken` → `kraken_paper_trade`
   - Hummingbot gebruikt dan automatisch de paper trading connector

2. **Simulatie**:
   - Orders worden gesimuleerd (geen echte orders op de exchange)
   - Balansen zijn virtueel (je kunt ze instellen in Hummingbot)
   - Alle andere functionaliteit werkt hetzelfde

3. **Logging**: Alle logs zijn identiek aan live trading, zodat je precies ziet wat er zou gebeuren

## Paper Trading Balans instellen

In Hummingbot CLI, wanneer je de bot start met paper trading:

1. Start Hummingbot: `bin/hummingbot.py`
2. Configureer paper trading balance:
   ```
   >>> config paper_trade_account_balance
   >>> Enter paper trade account balance (e.g., EUR:1000, BTC:0.1): EUR:1000
   ```
3. Start de bot: `start --script multi_coin_grid_v2.py`

## Controleren of Paper Trading actief is

In de logs zie je:
```
📝 PAPER TRADING MODE ENABLED - No real money will be used!
✅ Controller initialized: kraken_paper_trade (📝 PAPER TRADING)
```

## Van Paper Trading naar Live Trading

1. Zet `paper_trading: false` in je config (of verwijder de regel)
2. Herstart de bot
3. Controleer de logs: je zou moeten zien `💰 LIVE TRADING` in plaats van `📝 PAPER TRADING`

## Belangrijke Notities

- ⚠️ **Paper trading gebruikt echte marktdata**, maar plaatst geen echte orders
- ⚠️ **Resultaten kunnen verschillen** van live trading door:
  - Slippage (niet gesimuleerd)
  - Order fills (gesimuleerd als instant)
  - Network latency (niet gesimuleerd)
- ✅ **Perfect voor testing** van logica, trends, en coin discovery
- ✅ **Gebruik voor development** voordat je live gaat

## Troubleshooting

**Paper trading connector niet gevonden?**
- Zorg dat je Hummingbot versie paper trading ondersteunt
- Check of `kraken_paper_trade` beschikbaar is: `>>> connect kraken_paper_trade`

**Balans is 0?**
- Configureer paper trade balance in Hummingbot CLI
- Check: `>>> config paper_trade_account_balance`

**Bot handelt niet?**
- Check logs voor errors
- Verify dat connector naam correct is (`kraken_paper_trade`)
- Check dat `paper_trading: true` in config staat
