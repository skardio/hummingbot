# Kraken + Bitstamp Arbitrage Setup Guide for Netherlands Traders

## Complete Step-by-Step Setup

---

## PHASE 1: EXCHANGE ACCOUNT SETUP (30 minutes each)

### 1.1 Create Kraken Account

**Step 1:** Go to https://www.kraken.com/en-us/

**Step 2:** Click "Sign up" and enter:
- Email address
- Strong password (16+ characters, mixed case, numbers, symbols)
- Username (will be used for API identification)

**Step 3:** Verify email address (check inbox + spam folder)

**Step 4:** Two-Factor Authentication (2FA)
```
Required for security:
- Download Authy or Google Authenticator
- Scan QR code from Kraken
- Save backup codes in safe place (critical!)
- Enter 6-digit code to confirm
```

**Step 5:** KYC Verification (Netherlands)
```
Kraken requires Level 2 verification for trading:
- Go to Settings → Verification
- Proof of residence (utility bill, bank statement < 3 months old)
- Government ID (Passport or Driving License)
- Address confirmation
- Processing time: Usually instant to 24 hours
```

### 1.2 Create Bitstamp Account

**Step 1:** Go to https://www.bitstamp.net/

**Step 2:** Click "Register" and enter:
- Email address
- Strong password (16+ characters)
- Full name (as on ID)
- Country: Netherlands
- Accept Terms of Service

**Step 3:** Verify email address

**Step 4:** Two-Factor Authentication (2FA)
```
Same as Kraken:
- Download Authy or Google Authenticator
- Scan QR code
- Save backup codes
- Confirm 6-digit code
```

**Step 5:** KYC Verification (EU resident)
```
Bitstamp requires Level 2 verification:
- Full name
- Date of birth
- Address (Dutch address required)
- Phone number
- Proof of residence (utility bill or bank statement)
- Proof of identity (Passport or ID)
- Processing time: 24-48 hours
```

---

## PHASE 2: API KEY GENERATION

### 2.1 Generate Kraken API Keys

**Navigation:** Settings → API (or /settings/api)

**Step 1:** Click "Generate New Key"

**Step 2:** Fill Key Information:
```
Key Description: "Hummingbot Trading Bot"
Nonce Window: Leave default
2-Factor Authentication: Enable (recommended)
```

**Step 3:** Select Permissions (IMPORTANT - minimum required):
```
✓ Query Funds
✓ Query Open Orders & Trades
✓ Query Closed Orders & Trades
✓ Access Funds
✓ Create & Modify Orders
✓ Cancel/Close Orders
```

**Step 4:** Restrict to IP Address (optional but recommended):
```
Add your home IP: https://whatismyipaddress.com/
Or leave unrestricted for cloud deployment
```

**Step 5:** Copy and SAVE credentials:
```
- API Key (public key - 88 characters)
- Private Key (secret - keep VERY secret!)
- Passphrase
```

**⚠️ CRITICAL:** Save to secure location (password manager, encrypted file)

### 2.2 Generate Bitstamp API Keys

**Navigation:** Account → Security → API Keys

**Step 1:** Click "Add new key"

**Step 2:** Key Permissions:
```
✓ Account balance
✓ User transactions
✓ Open orders
✓ Cancel orders
✓ Create orders
```

**Step 3:** IP Whitelist (optional):
```
Add your home IP for security
```

**Step 4:** Copy and SAVE:
```
- API Key
- API Secret (keep secure!)
- Customer ID (will be shown)
```

---

## PHASE 3: HUMMINGBOT CONFIGURATION

### 3.1 Add Kraken to Hummingbot

**Step 1:** Open terminal in Hummingbot directory:
```powershell
cd C:\Users\Sarah Hazal\papas_source\repos\hummingbot
```

**Step 2:** Start Hummingbot:
```powershell
python bin/hummingbot.py
```

**Step 3:** In Hummingbot interface, run:
```
>>> connect kraken
```

**Step 4:** Enter Kraken credentials when prompted:
```
Enter Kraken API key: [paste API key]
Enter Kraken API secret: [paste secret key]
```

**Step 5:** Test connection:
```
>>> get-balance kraken
```

Expected output:
```
Kraken balances:
BTC: 0.5
ETH: 5.0
USD: 1000.0
USDT: 500.0
```

### 3.2 Add Bitstamp to Hummingbot

**Step 1:** In Hummingbot, run:
```
>>> connect bitstamp
```

**Step 2:** Enter Bitstamp credentials:
```
Enter Bitstamp API key: [paste API key]
Enter Bitstamp API secret: [paste secret]
```

**Step 3:** Test connection:
```
>>> get-balance bitstamp
```

Expected output:
```
Bitstamp balances:
BTC: 0.5
ETH: 5.0
USD: 1000.0
```

---

## PHASE 4: ARBITRAGE STRATEGY CONFIGURATION

### 4.1 Create Configuration File

Create file: `conf/strategies/kraken_bitstamp_arb.yml`

```yaml
# Kraken ↔ Bitstamp Arbitrage Configuration
# ===========================================

# Strategy type
strategy: cross_exchange_market_making

# Market pair (use standardized format)
market_1: kraken
exchange_1: kraken
market_2: bitstamp
exchange_2: bitstamp

# Trading pair (works on both exchanges)
trading_pair: BTC-USD

# Order amounts (in base currency)
order_amount: 0.01  # 0.01 BTC ≈ €300-500

# Profit threshold (minimum profit needed to trade)
min_profitability_pct: 0.5  # 0.5% minimum spread before fees

# Fees (will be deducted from profit)
# Kraken: 0.16% maker, 0.26% taker
# Bitstamp: 0.25% maker, 0.35% taker
# Conservative estimate: 0.5% total fees per cycle

# Safety settings
logging_enabled: true
maximum_order_age_in_seconds: 3600  # Cancel orders older than 1 hour

# Order book depth (higher = better matching, slower updates)
order_book_depth: 10
```

### 4.2 Alternative: Pure Market Making on Kraken

Create file: `conf/strategies/kraken_market_making.yml`

```yaml
# Pure Market Making on Kraken
# ============================

strategy: pure_market_making

exchange: kraken
trading_pair: BTC-USD

# Order amounts
order_amount: 0.01  # Start small

# Spread (profit margins on buy/sell sides)
bid_spread: 0.05   # 0.05% below market (buy side)
ask_spread: 0.05   # 0.05% above market (sell side)

# Order refresh interval
order_refresh_time: 30  # Refresh orders every 30 seconds

# Safety
maximum_order_age_in_seconds: 3600
logging_enabled: true
```

---

## PHASE 5: START TRADING

### 5.1 Paper Trading (Simulated)

**Step 1:** In Hummingbot, enable paper trading mode:
```
>>> set paper_trade_enabled True
```

**Step 2:** Load your strategy:
```
>>> import kraken_bitstamp_arb
```

Or:
```
>>> import kraken_market_making
```

**Step 3:** Monitor for 24-48 hours:
```
>>> status
>>> get_balance
>>> orders
```

**Step 4:** Check logs:
```
tail -f logs/hummingbot_logs_latest.log
```

### 5.2 Live Trading (REAL MONEY - Start Small!)

**⚠️ WARNING:** Before going live:
- Test strategy for 24+ hours in paper trading mode
- Start with minimum amounts (0.001-0.01 BTC)
- Monitor closely for first 10-20 trades
- Have stop-loss plan if unexpected losses occur

**Step 1:** Disable paper trading:
```
>>> set paper_trade_enabled False
```

**Step 2:** Start strategy:
```
>>> start
```

**Step 3:** Monitor actively:
```
>>> orders               # Check active orders
>>> get_balance         # Verify balance across exchanges
>>> status              # Full strategy status
```

---

## IMPORTANT CONFIGURATION PARAMETERS

### Market Making Spreads

```
bid_spread: How much BELOW market price to place buy orders
ask_spread: How much ABOVE market price to place sell orders

Conservative (low risk, low profit):
  bid_spread: 0.1    (0.1% below market)
  ask_spread: 0.1    (0.1% above market)
  = 0.2% profit per cycle, fees ≈ 0.3%, net: -0.1% (loses money)

Moderate (balanced):
  bid_spread: 0.05   (0.05% below market)
  ask_spread: 0.05   (0.05% above market)
  = 0.1% profit per cycle, fees ≈ 0.3%, net: -0.2% (loses money)

Aggressive (higher risk, needs volume):
  bid_spread: 0.2    (0.2% below market)
  ask_spread: 0.2    (0.2% above market)
  = 0.4% profit per cycle, fees ≈ 0.3%, net: 0.1% (profit!)
```

### Arbitrage Thresholds

```
min_profitability_pct: Minimum spread between exchanges before trading

At 0.3% spread with 0.5% fees:
  Spread: 0.3% - Fees: 0.5% = -0.2% (LOSS)

At 0.8% spread with 0.5% fees:
  Spread: 0.8% - Fees: 0.5% = +0.3% (PROFIT)

Recommended: min_profitability_pct: 0.75  (account for price changes)
```

---

## EXPECTED PROFITS & REALISTIC EXPECTATIONS

### Market Making on Kraken (Conservative)

```
Capital: €1,000
Order size: 0.01 BTC (per order)
Trades per day: 20-30 (if market is active)
Profit per trade: 0.1% (€1)
Daily profit: €2-3 (0.2-0.3% of capital)
Monthly profit: €60-90
Annualized: €730-1,095 (73-109% APY)
```

**Reality Check:** 
- These numbers assume consistent 30 trades/day (market dependent)
- Network latency can cause missed opportunities
- Market volatility can cause losses on unfilled orders
- Requires 24/7 monitoring during active trading

### Arbitrage (Kraken ↔ Bitstamp)

```
Capital: €2,000 (€1,000 per exchange)
Order size: 0.01 BTC
Profitable spreads: 0.8%+ between exchanges
Frequency: 2-5 times per day (when spreads available)
Profit per cycle: €2-5 (0.3-0.5% after fees)
Daily profit: €4-25 (0.2-1.25% of capital)
Monthly profit: €120-750
Annualized: €1,460-9,120 (73-456% APY)
```

**Reality Check:**
- Spreads rarely exceed 1% between Kraken/Bitstamp (both liquid EU exchanges)
- Transfer time between exchanges = missed opportunity window
- Execution risk: price changes while order is pending
- 5-10 trades per day is realistic in good market conditions

---

## TROUBLESHOOTING

### "Connection refused" errors

**For Kraken:**
```
1. Check API key and secret (copy-paste carefully, no spaces)
2. Verify Kraken API is enabled in account settings
3. Check system time is synchronized (critical for Kraken nonce)
   Windows: Settings → Date & Time → Set time automatically ON
4. Restart Hummingbot
```

**For Bitstamp:**
```
1. Verify API key format (should be long alphanumeric string)
2. Check API secret is copied correctly
3. Ensure IP whitelist includes your IP (if set)
4. Test connection: curl -X POST https://www.bitstamp.net/api/v2/balance/
```

### Orders not filling

```
Cause 1: Spread too tight
  Solution: Increase bid_spread and ask_spread

Cause 2: Order amount too large (exceeds exchange limits)
  Solution: Reduce order_amount parameter

Cause 3: Insufficient balance
  Solution: Check get_balance output, ensure funds in correct currency

Cause 4: Market inactive (low liquidity)
  Solution: Check order book depth, consider different trading pair
```

### High latency / Slow order execution

```
Cause: Network latency to exchange servers
Solutions:
  1. Use VPN closer to exchange location (Kraken in EU, Bitstamp in Sweden)
  2. Reduce order_refresh_time (refresh orders more frequently)
  3. Increase order amount (larger orders execute faster)
  4. Check local internet connection (run speedtest.net)
```

### Funds not syncing between exchanges

```
Solution 1: Manual transfer
  - Kraken → Generate deposit address for Bitstamp
  - Bitstamp → Generate withdrawal address
  - Transfer BTC/ETH between exchanges manually
  - Wait for confirmation (5-30 minutes typically)

Solution 2: Hummingbot balance tracking
  >>> get_balance kraken
  >>> get_balance bitstamp
  Compare values - note any discrepancies

Solution 3: Check transaction history
  - Kraken: Account → History
  - Bitstamp: Account → User profile → Transactions
```

---

## SECURITY BEST PRACTICES

### API Key Management

```
✓ DO:
  - Store API keys in password manager (Bitwarden, 1Password)
  - Use separate API keys for each bot instance
  - Restrict API keys to specific IPs when possible
  - Enable 2FA on both accounts
  - Use strong passwords (16+ characters)
  - Keep private keys encrypted

✗ DON'T:
  - Paste API keys in chat or emails
  - Store in plain text files
  - Share screenshots containing credentials
  - Use same key for multiple bots
  - Commit credentials to git/GitHub
  - Leave terminal windows open with credentials visible
```

### Fund Security

```
- Keep only trading capital on exchanges (never savings)
- Use exchange's withdrawal whitelist feature
- Regularly move profits to cold storage wallet
- Set withdrawal limits per day (if available)
- Monitor account activity regularly (daily)
- Check connected devices/sessions
```

---

## NEXT STEPS

1. **Create accounts** on Kraken and Bitstamp (24-48 hours for KYC)
2. **Fund accounts** with initial capital (€500-2,000 recommended)
3. **Generate API keys** and save securely
4. **Configure Hummingbot** with credentials
5. **Test connections** and verify balances
6. **Load strategy** and run in paper trading mode
7. **Monitor** for 24+ hours before going live
8. **Start live trading** with smallest amounts first

---

## SUPPORT & RESOURCES

- Kraken Support: https://support.kraken.com/hc/en-us
- Bitstamp Support: https://www.bitstamp.net/support
- Hummingbot Docs: https://docs.hummingbot.org
- Hummingbot Discord: https://discord.gg/hummingbot
- Strategy Examples: `/scripts/` directory in Hummingbot

---

**Version:** 1.0  
**Last Updated:** November 2025  
**For:** Netherlands-based traders using Kraken + Bitstamp
