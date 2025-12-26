# 🔐 Security Setup - Environment Variables

## ✅ Changes Applied

### 1. API Keys Secured
- ✅ Created `.env` file with all API keys
- ✅ Created `.env.example` template (safe for git)
- ✅ Updated `.gitignore` to exclude `.env` files
- ✅ Removed hardcoded keys from scripts
- ✅ Updated config files to use environment variables

### 2. File Permissions Fixed
```bash
-rw------- (600) .env                    # Only owner can read/write
-rw-r--r-- (644) .env.example           # Everyone can read template
-rwx------ (700) start_bot.sh           # Only owner can execute
```

### 3. Scripts Updated
- ✅ `start_bot.sh` - Loads from .env, validates keys
- ✅ `scripts/start_telegram_handler.sh` - Loads from .env
- ✅ `multi_coin_grid_pro/monitoring/config.py` - Uses env vars only
- ✅ `multi_coin_grid_pro/config/risk_monitor.yaml` - No hardcoded tokens

---

## 🚀 Quick Start

### First Time Setup

1. **Copy environment template:**
   ```bash
   cd /home/mo/repos/hummingbot
   cp .env.example .env
   ```

2. **Edit .env with your actual keys:**
   ```bash
   nano .env  # or vim .env
   ```

   Fill in:
   - KRAKEN_API_KEY
   - KRAKEN_SECRET_KEY
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHAT_ID
   - (Optional) Other exchange keys

3. **Secure permissions (already done):**
   ```bash
   chmod 600 .env
   ```

4. **Start bot:**
   ```bash
   ./start_bot.sh
   ```

---

## 📋 Environment Variables

### Required (for spot bot):
- `KRAKEN_API_KEY` - Your Kraken API key
- `KRAKEN_SECRET_KEY` - Your Kraken secret key
- `BOT_ENV` - Environment (dev/test/prod)

### Optional (for monitoring):
- `TELEGRAM_BOT_TOKEN` - Telegram bot token (for alerts)
- `TELEGRAM_CHAT_ID` - Your Telegram chat ID

### Optional (for other strategies):
- `BITSTAMP_API_KEY` - Bitstamp API key
- `BITSTAMP_API_SECRET` - Bitstamp secret key
- `BITVAVO_API_KEY` - Bitvavo API key
- `BITVAVO_API_SECRET` - Bitvavo secret key

---

## ⚠️ Security Best Practices

### ✅ DO:
- Keep `.env` file permissions at `600` (only owner can read)
- Use different API keys for dev/test/prod
- Regularly rotate API keys
- Use read-only API keys when possible
- Limit API key permissions (trading only, no withdrawals)
- Back up `.env` file securely (encrypted USB, password manager)

### ❌ DON'T:
- NEVER commit `.env` to git
- NEVER share `.env` via email/chat
- NEVER hardcode keys in source code
- NEVER use production keys in development
- NEVER give API keys withdrawal permissions

---

## 🔍 Verify Setup

### Check if .env is loaded:
```bash
./start_bot.sh
# Should show: "Loading environment variables from .env..."
```

### Check if keys are set:
```bash
source .env
echo $KRAKEN_API_KEY  # Should print your key
```

### Check git ignores .env:
```bash
git status
# Should NOT show .env as untracked
```

### Check file permissions:
```bash
ls -la .env
# Should show: -rw------- (600)
```

---

## 🆘 Troubleshooting

### "ERROR: .env file not found!"
```bash
cp .env.example .env
nano .env  # Fill in your keys
```

### "ERROR: KRAKEN_API_KEY not set"
- Open `.env` and verify keys are filled in
- No quotes needed around values
- No spaces around `=` sign

### Bot can't connect to exchange
- Verify API keys are correct
- Check API key permissions on exchange
- Ensure keys are not expired

---

## 📝 What Changed

### Before (❌ INSECURE):
```bash
# start_bot.sh
export KRAKEN_API_KEY="actual_key_here"  # Hardcoded!
```

### After (✅ SECURE):
```bash
# start_bot.sh
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)  # Load from .env
fi
```

---

## 🔄 Migration Notes

**Your existing keys have been:**
1. ✅ Moved to `.env` file (secure)
2. ✅ Removed from `start_bot.sh`
3. ✅ Removed from config files
4. ✅ Added to `.gitignore`

**Git history is clean:**
- `.env` was never committed (good!)
- Old API keys in `start_bot.sh` should be rotated

---

## 🎯 Next Steps

### Recommended (High Priority):
1. **Rotate Kraken API keys** (old keys were in plain text files)
   - Go to Kraken → Settings → API
   - Revoke old keys
   - Create new keys with minimal permissions
   - Update `.env` with new keys

2. **Test bot startup:**
   ```bash
   ./start_bot.sh
   # Should load .env and start without errors
   ```

3. **Backup .env securely:**
   ```bash
   # Option 1: Encrypted USB
   gpg -c .env  # Creates .env.gpg

   # Option 2: Password manager (1Password, LastPass, etc.)
   # Copy/paste .env contents to secure note
   ```

### Optional (Future):
4. Use Secrets Manager (AWS Secrets Manager, HashiCorp Vault)
5. Set up key rotation schedule (every 3-6 months)
6. Add 2FA to exchange accounts
7. Monitor API key usage via exchange dashboards

---

## 📞 Support

If you have issues:
1. Check permissions: `ls -la .env`
2. Verify .env syntax: `cat .env | grep -v '^#'`
3. Test loading: `source .env && env | grep KRAKEN`

---

**Last updated:** December 7, 2025
**Security level:** 🔐 Production-ready
