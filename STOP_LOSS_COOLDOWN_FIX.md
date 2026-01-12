# Stop-Loss Cooldown Fix - Root Cause Analysis

**Datum:** 11 januari 2026
**Bug:** Bot verkoopt met verlies (MARKET order) en koopt direct terug (LIMIT order), verliest fees + coins

---

## 📋 Symptomen

Gebruiker observeerde het volgende gedrag:

```
08:53:00 - VERKOCHT: -113.91 POL @ €0.1542 (MARKET) → €17.51 - €0.06 fees
08:53:05 - GEKOCHT:  +113.16 POL @ €0.1544 (LIMIT)  → €17.51 + €0.03 fees

Netto verlies: ~0.75 POL + €0.10 fees
```

**Kernprobleem:** Bot verkocht POL met stop-loss (emergency exit), maar kocht **dezelfde coin** direct weer terug binnen seconden.

---

## 🔍 Root Cause

### Het Probleem

In [`multi_coin_grid_controller.py`](multi_coin_grid_pro/controllers/multi_coin_grid_controller.py#L3323-L3377):

Wanneer een executor stopt (door stop-loss, tijd, of error), werd **alleen** `active_coin` gereset:

```python
# Line 3375-3377 (VOOR FIX)
self.active_executor_id = None
self.active_coin = None
return False
```

Maar `last_switch_time` werd **NIET** geupdatet. Dit betekende:

1. **Stop-loss triggert** → Executor stopt → `active_coin = None`
2. **last_switch_time blijft oud** (bijv. 850.0)
3. **Volgende cyclus** (08:53:05) → Bot zoekt nieuwe coin
4. **POL is nog steeds top coin** → Bot selecteert POL opnieuw
5. **GEEN cooldown check** omdat `active_coin == None`
6. **Nieuwe grid gemaakt** → LIMIT BUY order voor POL

### Waarom gebeurde dit?

`last_switch_time` werd **alleen** gezet bij het **creëren** van een grid (regel 3084):

```python
# Line 3084
self.last_switch_time = self.market_data_provider.time()
```

Maar **NIET** bij het **stoppen** van een grid door stop-loss.

---

## ✅ De Fix

### Wijziging

In [`multi_coin_grid_controller.py`](multi_coin_grid_pro/controllers/multi_coin_grid_controller.py#L3323-L3360):

```python
# Check if executor failed due to insufficient balance OR stop-loss
if failed_executor and not failed_executor.is_active:
    close_type = str(failed_executor.close_type) if failed_executor.close_type else ""
    close_type_str = close_type.upper()

    # Check for insufficient balance indicators
    is_insufficient_balance = (
        'INSUFFICIENT_BALANCE' in close_type_str
        or 'INSUFFICIENT' in close_type_str
        or ('BALANCE' in close_type_str and 'NOT ENOUGH' in close_type_str)
        or 'budget' in close_type.lower()
        or 'Not enough budget' in close_type
    )

    # Check for stop-loss trigger
    is_stop_loss = 'STOP_LOSS' in close_type_str

    if is_insufficient_balance:
        # ... (existing logic)
        pass
    elif is_stop_loss:
        # 🔧 CRITICAL FIX: Stop-loss triggered - set switch cooldown to prevent immediate re-entry
        current_time = self.market_data_provider.time()
        self.last_switch_time = current_time
        if self.active_coin:
            self.logger().critical(
                f"🛑 STOP-LOSS EXIT: {self.active_coin} executor stopped due to stop-loss. "
                f"Setting switch cooldown ({self.config.min_switch_interval_seconds}s) to prevent immediate re-entry."
            )
    else:
        # ... (existing logic)
        pass
```

### Wat doet de fix?

1. **Detecteert stop-loss** in `close_type`
2. **Update `last_switch_time`** naar huidige tijd
3. **Logt melding** met cooldown informatie
4. **Voorkomt immediate re-entry** door cooldown enforcement in `determine_executor_actions()`

---

## 🧪 Testing

### Unit Tests

Gemaakt: [`test_stop_loss_cooldown_fix.py`](multi_coin_grid_pro/tests/unit/test_stop_loss_cooldown_fix.py)

**4 tests, alle PASSED:**

1. ✅ `test_stop_loss_detection` - Detecteert STOP_LOSS correct in close_type
2. ✅ `test_switch_cooldown_logic` - Cooldown berekening werkt correct
3. ✅ `test_immediate_reentry_prevention` - Voorkomt re-entry binnen cooldown
4. ✅ `test_bug_scenario_pol_reentry` - Simuleert exacte POL bug scenario

### Test Resultaat

```bash
$ python -m pytest multi_coin_grid_pro/tests/unit/test_stop_loss_cooldown_fix.py -v

4 passed in 0.02s
```

---

## 📊 Impact

### Voor de Fix

- **Stop-loss trigger** → Directe re-entry mogelijk
- **Geen cooldown** na emergency exit
- **Verlies:** Fees + slippage + coin verschil (0.75 POL + €0.10)

### Na de Fix

- **Stop-loss trigger** → `last_switch_time` updated
- **Cooldown enforced** (5 minuten standaard via `min_switch_interval_seconds`)
- **Voorkomt:** Immediate re-entry van dezelfde verliezende coin
- **Resultaat:** Bot wacht minimaal 5 minuten voordat dezelfde coin opnieuw kan worden geselecteerd

---

## 🚀 Deployment

### Configuratie

De cooldown periode wordt bepaald door:

```yaml
min_switch_interval_seconds: 300  # 5 minuten (standaard)
```

Deze waarde kan worden aangepast in de bot config als een andere cooldown gewenst is.

### Log Melding

Na stop-loss zie je nu:

```
🛑 STOP-LOSS EXIT: POL-EUR executor stopped due to stop-loss.
   Setting switch cooldown (300s) to prevent immediate re-entry.
```

Gevolgd door in volgende cyclus:

```
⏳ Global switch cooldown active - 4.8 min remaining
```

---

## 📝 Gerelateerde Code

- **Controller:** [`multi_coin_grid_controller.py`](multi_coin_grid_pro/controllers/multi_coin_grid_controller.py#L3323-L3360)
- **Tests:** [`test_stop_loss_cooldown_fix.py`](multi_coin_grid_pro/tests/unit/test_stop_loss_cooldown_fix.py)
- **Config:** `min_switch_interval_seconds` parameter

---

## 🎯 Conclusie

**Root Cause:** `last_switch_time` werd niet geupdatet na stop-loss exit
**Symptoom:** Bot verkocht met verlies en kocht direct terug
**Fix:** Update `last_switch_time` bij stop-loss trigger
**Resultaat:** 5-minuten cooldown voorkomt immediate re-entry
**Status:** ✅ Fixed + Tested (4/4 tests passed)
