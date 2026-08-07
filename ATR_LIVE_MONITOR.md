# ATR Live Monitor

Real-time ATR% checker voor trading pairs op OKX, Kraken en Bitget.
Laat zien of de markt beweeglijk genoeg is om winstgevend te handelen na fees.

## Gebruik

```bash
# Activeer venv eerst
source ~/.venvs/bot/bin/activate
cd ~/repos/hummingbot

# OKX — BTC elke 30 seconden (default)
python atr_live.py okx BTC-USDC

# OKX — ETH, langere ATR periode
python atr_live.py okx ETH-USDC --period 20

# Kraken EUR
python atr_live.py kraken-eur XBT/EUR

# Kraken USD
python atr_live.py kraken-usd XBT/USD

# Bitget — snellere refresh
python atr_live.py bitget BTC-USDT --refresh 15

# Ctrl+C om te stoppen
```

## Opties

| Optie | Kort | Default | Uitleg |
|-------|------|---------|--------|
| `--period` | `-p` | 14 | ATR periode in candles (1m candles) |
| `--refresh` | `-r` | 30 | Refresh interval in seconden |

## Exchanges

| Exchange | Commando | Round-trip fee | Vereiste ATR (2×) |
|----------|----------|---------------|-------------------|
| OKX EU | `okx` | 0.40% | **0.80%** |
| Kraken EUR | `kraken-eur` | 0.40% | **0.80%** |
| Kraken USD | `kraken-usd` | 0.40% | **0.80%** |
| Bitget | `bitget` | 0.20% | **0.40%** |

## Voorbeeld output

```
==============================================================
  ATR Live Monitor  |  OKX EU  |  BTC-USDC
  ATR(14 × 1m candles)  |  refresh: 30s  |  Ctrl+C om te stoppen
==============================================================

[13:22:50]  #1  Prijs:  77,229.50  Spread: 0.0001%  Vol24h: €1.5M
  ATR(14):   0.0293%  [░░░░░░░░░░░░░░░░░░░░░░░░] 4%
  Vereist:   0.800%   (fees 0.40% × 2.0)
  Status:    ❌ ATR_TOO_LOW — 27.3× onder target

  Volgende update over 28s...
```

**Balk vult op** naarmate ATR dichter bij het target komt.
Zodra `✅ HANDELEN OK` verschijnt is de markt beweeglijk genoeg.

## Hoe werkt ATR?

ATR (Average True Range) meet hoeveel de prijs gemiddeld beweegt per minuut-candle.

```
True Range per candle = max(
    high - low,           ← bereik van de candle
    |high - prev_close|,  ← gap omhoog
    |low  - prev_close|   ← gap omlaag
)

ATR(14) = gemiddelde van laatste 14 True Ranges
ATR%    = ATR / huidige prijs × 100
```

**Waarom ATR ≥ 2× fees nodig?**
Als ATR lager is dan de round-trip fee × 2, kun je wiskundig nooit winst maken na kosten.
De bot weigert dan correct om te handelen.
