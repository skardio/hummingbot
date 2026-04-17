# Follow-Up Prompt: Kraken USD Bot Validatie na Pre-Masterplan Fixes

**Gebruik na 2-4 uur draaien van de Kraken USD bot (gestart 4 april 2026)**

---

## Prompt (kopieer dit):

```
De Kraken USD bot draait nu een paar uur met alle pre-masterplan fixes. Analyseer de recente sessie en vergelijk met de baseline. Antwoord in het Nederlands.

## Context: Wat is er veranderd (pre-masterplan backlog)

De volgende 14 items zijn geïmplementeerd vóór deze sessie:

### Critical Fixes (HF-01)
- **ATR fix**: `atr_min_pct` 1.5→0.15 in alle 3 spot configs (1.5% filterde ALLE coins, typische ATR is 0.05-0.5%)
- **bear_allow_meanrev**: false→true (99% BEAR regime blokkeerde 1284 entries)

### Spikes (SP-01 t/m SP-05) — onderzoek dat configs stuurde
- SP-01: ATR confidence → bevestigde dat 1.5% te hoog was
- SP-02: Slot/budget deadlock → leidde tot max_simultaneous_coins 4→2 en budget-alignment
- SP-03: Fill rate deep-dive → bevestigde dat grids te ver van markt staan
- SP-04: Insufficient balance root cause → 99% INSUF_BAL → budget/slots fix
- SP-05: Sell-ratio analyse → buy/sell onevenwicht geïdentificeerd

### Stories (ST-01 t/m ST-06b) — code-wijzigingen
- ST-01: `_NO_SCALE_KEYS` in AdaptiveFilterResolver (voorkomt dat ATR thresholds per-regime geschaald worden)
- ST-02: Universe quality gate module (filtert lage-kwaliteit coins)
- ST-03: Pool rotation cooldown 30 min (voorkomt 29× in/uit flipping)
- ST-04: Data health fixes (top_n alignment, unsubscribe fix, auto-align)
- ST-05a: ExecutionFunnelTracker integratie (5 funnel stages geïnstrumenteerd)
- ST-05b: Timeout exit redesign (grace 600s, LIMIT orders ipv aggressive market)
- ST-06a: `_log_selection_trace()` method voor debug
- ST-06b: Database logging fix (buffer 100→5, schrijft nu echt naar DB)

### Config tuning (T3-F3 sessie + 2026-04-03 tuning)
- vwap_max_deviation_pct: 18→12 (stop adverse selection)
- max_trend_24h_pct: 25→15 (stop trend-chasing)
- dynamic_tp_min_pct: 0.012→0.020 (floor 2.0%, net ~1.58% na fees)
- dynamic_tp_max_pct: 0.03→0.04 (cap 4%)
- switch_cost_multiplier: 2.5→3.5 (straf switching af)
- min_switch_interval: 600→1800 (30 min cooldown)
- min_hold_time: 3600→7200 (2h, grid heeft tijd nodig)
- pause_cooldown_minutes: 120→30 (was te lang, death spiral)
- no_progress_min_loss_pct: 1.0→0.5 (cut bags eerder)
- switch_threshold_percent: 3→5 (hogere bar voor switch)
- max_open_orders: 60→20
- num_grids: 5→3 ($50/level)

## Baseline (VÓÓR fixes - historische data)

Uit de eerdere analyse (alle data t/m 4 april):
- **USD Executor fill rate**: 0.5% (1 van 212 executors gevuld)
- **USD INSUF_BAL**: 99.1% (210 van 212 executors)
- **USD buy/sell ratio**: 26.7% (2025 buys, 541 sells)
- **USD netto cashflow**: -$240 over $2786 gekocht
- **USD fees**: $12.30
- **EUR fill rate**: 1.5% (34 van 2216)
- **Bitget Spot fill rate**: 1.5% (6 van 400)

## Wat ik wil weten

### 1. Executor Fill Rate (T3 proof gate target: ≥30%)
- Hoeveel executors zijn er DEZE SESSIE aangemaakt?
- Hoeveel daarvan zijn gevuld (filled_amount_quote > 0)?
- Wat is de fill rate? Vergelijk met baseline 0.5%.
- Welke close_types deze sessie? (EARLY_STOP=5, INSUF_BAL=7, TAKE_PROFIT=3, etc.)

### 2. INSUFFICIENT_BALANCE opgelost?
- Hoeveel executors faalden op INSUF_BAL (close_type=7)?
- Was baseline 99.1% — is dit gedaald?

### 3. Buy/Sell ratio
- Hoeveel buys vs sells deze sessie?
- Worden er daadwerkelijk take-profits geraakt?

### 4. ExecutionFunnelTracker (ST-05a)
- Check `logs/events_usd/` voor funnel events
- Hoeveel candidates worden considered → allowed → approved → started?
- Waar vallen de meeste af? (rejection reasons)

### 5. Welke coins gehandeld?
- Top coins by trade count deze sessie
- Zijn er coins die veel gekocht maar niet verkocht worden?

### 6. PnL deze sessie
- Gross en net PnL (uit Executors tabel)
- Fees betaald
- Gemiddelde PnL per gevulde executor

### 7. Grid gedrag
- Worden alle 3 grid levels gevuld of alleen level 1?
- Hoe lang duurt een typische grid cycle (buy → sell)?
- Worden TP LIMIT orders geplaatst via het nieuwe ST-05b grace systeem?

### 8. Logs check
- Zoek in logs/ naar: "INSUFFICIENT", "kill_switch", "FAILED", "stuck", "error"
- Zoek naar ExecutionFunnel summary logs
- Zoek naar selection_trace logs (ST-06a)
- Zijn er WebSocket disconnect/reconnect issues?

## Database paden
- TradeFills + Orders + Executors: `data/multi_coin_grid_v2_usd.sqlite`
- Events: `logs/events_usd/`
- Logs: `logs/logs_multi_coin_grid_usd_*.log` (nieuwste)
- Cooldowns: `data/cooldowns_usd.db`

## DB encoding
- TradeFill: amount × 1e-9, price × 1e-8 voor echte waarden
- Executors: net_pnl_quote, cum_fees_quote, filled_amount_quote zijn al in quote currency
- Fees in TradeFill: `json_extract(trade_fee, '$.flat_fees[0].amount')` (al USD string)

## Nuttige queries

### Alleen DEZE sessie (pas timestamp aan):
```sql
-- Executors deze sessie (timestamp > startmoment)
SELECT * FROM Executors WHERE timestamp > unixepoch('2026-04-04 HH:MM:SS');

-- Close type verdeling deze sessie
SELECT close_type, COUNT(*), ROUND(SUM(net_pnl_quote),4), SUM(CASE WHEN filled_amount_quote>0 THEN 1 ELSE 0 END) as filled
FROM Executors WHERE timestamp > unixepoch('2026-04-04 HH:MM:SS')
GROUP BY close_type;

-- Trades deze sessie per coin
SELECT base_asset, COUNT(*), SUM(CASE WHEN trade_type='BUY' THEN 1 ELSE 0 END) as buys,
       SUM(CASE WHEN trade_type='SELL' THEN 1 ELSE 0 END) as sells
FROM TradeFill WHERE timestamp/1000 > unixepoch('2026-04-04 HH:MM:SS')
GROUP BY base_asset ORDER BY COUNT(*) DESC;
```

## CloseType mapping
1=TIME_LIMIT, 2=STOP_LOSS, 3=TAKE_PROFIT, 4=EXPIRED, 5=EARLY_STOP,
6=TRAILING_STOP, 7=INSUFFICIENT_BALANCE, 8=FAILED, 9=COMPLETED,
11=NO_FILL_TIMEOUT, 12=NO_PROGRESS_TIMEOUT, 13=HARD_CAP_TIME,
14=RISK_KILL_SWITCH, 15=MANUAL, 16=SWITCH

## RunnableStatus mapping
1=NOT_STARTED, 2=RUNNING, 3=SHUTTING_DOWN, 4=TERMINATED, 5=CLOSING

## Verwachte verbeteringen
- INSUF_BAL moet drastisch dalen (was 99% → target <10%)
- Fill rate moet stijgen (was 0.5% → target >5% minimaal)
- ATR filter moet coins doorlaten (was 0% door 1.5% bug)
- Bear regime moet entries toelaten (was 0% door bear_allow_meanrev=false)
- Switching moet afnemen (hogere switch_cost en cooldown)
- Bags moeten sneller afgesneden (no_progress_min_loss 1.0→0.5%)

Geef je conclusie als: "FIXES WERKEN" / "DEELS VERBETERD" / "GEEN VERBETERING" met onderbouwing per punt.
```

---

*Prompt gegenereerd op 4 april 2026, na afronding van alle 14 pre-masterplan items.*
