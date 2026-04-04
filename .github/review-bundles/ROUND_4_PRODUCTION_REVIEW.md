# Round 4: Production Readiness & Observability Review

**Reviewer role:** DevOps/SRE Engineer & Trading Infrastructure Architect
**Date:** 2026-03-12
**Scope:** Deployment, operations, monitoring, testing, scaling, database, documentation
**Prior rounds:** [Round 1](ROUND_1_STRATEGY_REVIEW.md) Strategy (negative EV) · [Round 2](ROUND_2_ARCHITECTURE_REVIEW.md) Architecture (2.5/10) · [Round 3](ROUND_3_RISK_REVIEW.md) Risk (1.5/10)

---

## Table of Contents

1. [Maturity Scorecard](#1-maturity-scorecard)
2. [Top 10 Operational Risks](#2-top-10-operational-risks)
3. [Scaling Bottlenecks](#3-scaling-bottlenecks)
4. [Phase 1/2/3 Roadmap](#4-phase-123-roadmap)
5. [Infrastructure Recommendations](#5-infrastructure-recommendations)
6. [What to Keep](#6-what-to-keep)
7. [Capital Scaling Verdict](#7-capital-scaling-verdict)
8. [Final Verdict](#8-final-verdict)
9. [Confidence Classification](#9-confidence-classification)

---

## 1. Maturity Scorecard

| Dimension | Rating | Score | Evidence |
|-----------|--------|-------|----------|
| **Code quality & maintainability** | Hobby → Intermediate | 3/10 | 9,182-line God class, duplicate logging bug (L8453–8462), `gc.collect()` in hot path, but good Pydantic model (1,611 lines) and semantic validator |
| **Testing & CI/CD** | Intermediate | 5/10 | 79 well-structured tests with assertions, GitHub Actions CI with 80% diff-cover, pre-commit hooks — but root-level "tests" are diagnostic scripts (12/15 no assertions), flake8 excludes all root scripts, no integration tests run against live-like infra |
| **Monitoring & alerting** | Hobby → Intermediate | 4/10 | 4-service monitoring stack (collector, dashboard, Telegram, risk monitor), JSONL event logging, WHY-NO-TRADE hourly reports — but no Prometheus/Grafana, no centralized logging, no retention policy (monitoring.db at 320 MB), no cross-bot dashboard |
| **Deployment & operations** | Hobby | 2/10 | Manual `nohup` processes, no systemd/supervisord, Docker restart policy commented out, manual deploy script, no auto-restart, start scripts exit on error with no recovery |
| **Disaster recovery** | Hobby | 1/10 | No automated backups, no DB migration framework, no tested restore procedure, monitoring.db has no retention, 6.3 GB unmanaged logs, entry prices lost on restart |
| **Documentation** | Intermediate → Advanced | 6/10 | Operational runbook (239 lines), architecture docs, DOCUMENTATION_INDEX.md, phase docs, setup guides, daily audit trail (68 JSONL files) — but no incident response playbook, no deployment checklist, runbook not tested |

### Overall Maturity: **Late Hobby / Early Intermediate**

The codebase has significant investment in monitoring and documentation — more than typical hobby projects. But the deployment story (manual nohup, no supervision, no auto-restart) and disaster recovery (no backups, no restore testing) keep it firmly below intermediate for production readiness.

---

## 2. Top 10 Operational Risks

### #1: No Process Supervision — Bot Dies Silently

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| No systemd, supervisord, or Docker restart policy | Start scripts use `set -e` + direct `python3 bot_v2.py` — exit on any error. Docker Compose `restart: always` is commented out. No `.service` files exist | Bot crashes → stays dead until manual restart. Positions unprotected (see Round 3: no exchange-side stops on spot) | Create systemd service with `Restart=always` and `RestartSec=10` | ✅ High |

**Impact on PnL:** High — unprotected positions during downtime
**Impact on safety:** Critical — spot positions have no exchange-side stops
**Effort:** 2 hours
**Urgency:** Immediate

### #2: 320 MB Monitoring Database with No Retention

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| `monitoring.db` grows at ~107 MB/month with no cleanup | `multi_coin_grid_pro/data/monitoring.db` is 320 MB (3 months). No purge, archive, or max_age logic in `database.py`. `bot_status` table gets a row every 10 seconds = 8,640 rows/day | Disk fills → monitoring crashes → no alerts during critical events. SQLite query performance degrades as tables grow | Add `DELETE FROM bot_status WHERE timestamp < datetime('now', '-7 days')` on startup + daily. Same for `bot_events` | ✅ High |

**Impact on PnL:** Medium (monitoring failure during crisis)
**Impact on safety:** High (losing alerts at worst time)
**Effort:** 2 hours
**Urgency:** Immediate

### #3: 6.3 GB Unmanaged Log Directory

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| `logs/` is 6.3 GB with 149 files. Event JSONL files (399 MB) have no rotation. Only cleanup is manual interactive script (`cleanup_old_logs.sh`) | `TimedRotatingFileHandler` with `backupCount: 30` rotates main logs, but JSONL events and report logs are never cleaned. Audit files (8.4 MB) accumulate forever | Disk full → bot cannot write logs → logging errors → potential crashes. On a small VPS, 6.3 GB is significant | Cron job: `find logs/ -name "*.jsonl" -mtime +14 -delete`. Add size-based rotation to EventLogger. Archive old audits monthly | ✅ High |

**Impact on PnL:** Low
**Impact on safety:** Medium (cascading failure on disk full)
**Effort:** 1 hour
**Urgency:** Immediate

### #4: No Automated Database Backups

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| `data/backup/` has 6 files — all from a single migration event (Dec 2025). No cron, no scheduled backup script. Only `migrate_database_precision.py` creates backups before migration | Four production SQLite databases (29 MB total) contain all trade history. Loss = complete loss of historical data, entry prices, executor state | DB corruption during crash → no recovery path. SQLite without WAL mode is especially vulnerable to crash corruption | Daily cron: `sqlite3 data/X.sqlite ".backup data/backup/X_$(date +%Y%m%d).sqlite"`. Keep 7 days. Test restore quarterly | ✅ High |

**Impact on PnL:** Medium (state loss compounds risk)
**Impact on safety:** High
**Effort:** 1 hour
**Urgency:** Immediate

### #5: No Health Checks or Watchdog

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| No liveness probe, no health endpoint, no heartbeat monitoring. Flask dashboard has `/api/status` but it's informational — not a health check. Monitoring processes also run via `nohup` with no supervision | `start_monitoring.sh` uses `pgrep` to check if already running but has no restart logic. If collector dies, no new events are stored, no alerts sent | Monitoring system can silently die → operator unaware of bot issues. Bot can hang (not crash) with no detection | Add `/health` endpoint returning last-tick timestamp. Systemd watchdog with `WatchdogSec=60`. External ping check (UptimeKuma/healthchecks.io) | ✅ High |

**Impact on PnL:** High (silent failure = unnoticed losses)
**Impact on safety:** High
**Effort:** 4 hours
**Urgency:** Immediate

### #6: Manual Code Deployment

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| `deploy_stale_detection.sh` is a manual 6-step deploy: syntax check → test → backup logs → generate monitoring script → manual restart. No git tag, no rollback, no atomic deploy | Deploy script ends with `echo "To deploy, restart your bot(s)"` — operator must manually restart. No version tracking between what's deployed vs what's in git | Partial deployments, version drift between bot instances, no rollback capability. "Manual sync between two code directories" mentioned in operational setup | Git tag deploys: `git tag -a v1.X.X`, restart via systemd `systemctl restart bot-kraken-usd`. Rollback = `git checkout v1.X.(X-1)` + restart | ✅ High |

**Impact on PnL:** Low
**Impact on safety:** Medium (wrong code running = unknown risk)
**Effort:** 4 hours
**Urgency:** Next sprint

### #7: Stuck Order Blocks Capital — No Auto-Resolution

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| Bitget Spot: stuck SONIC LIMIT SELL @ $0.046419 locks ~$71. Bot logs 368 identical "Insufficient capital: $3.62 < $30.00 minimum" errors. Stale order detection is alert-only | `_cleanup_stale_orders()` stores stale orders in `self._stale_orders` for "future enhancement." No auto-cancel. Same pattern for Bitget Futures ($9 free < $15 minimum) | 2 of 3 active bots are capital-blocked and unable to trade. Bot is burning compute + API calls achieving nothing. 368 identical log entries = noise | Auto-cancel stale orders after configurable timeout (default 30 min). Log distinct errors with count instead of per-tick repeat | ✅ High |

**Impact on PnL:** High (2 bots unable to generate any returns)
**Impact on safety:** Medium
**Effort:** 4 hours
**Urgency:** Immediate

### #8: WebSocket Instability on Kraken

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| 336 WebSocket-related events in a 3-day Kraken USD session. `MQTT is already stopped!` errors. Repeated "Unexpected error while listening to user stream. Retrying after 5 seconds..." | Log analysis: 225 ERROR + 277 WARNING in current session. Reconnection logic exists (exponential backoff) but errors are persistent | Stale market data → NO_ORDERBOOK_DATA rejection (35–44% of all intents). Delayed fill notifications → risk checks on stale data. 112+ errors degrade performance | Investigate root cause: Kraken WS API version, keepalive settings, MTU issues. Consider fallback to REST polling when WS unstable. Add WS health metric | 🟡 Medium |

**Impact on PnL:** High (data pipeline is #1 bottleneck)
**Impact on safety:** Medium
**Effort:** 1–3 days (investigation + fix)
**Urgency:** Next sprint

### #9: No Config Change Audit Trail

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| YAML configs are 800+ lines each. No `schema_version` field (documented as requirement but not implemented). Config hash logged at startup via `compute_config_hash()` but no diff/history | `copilot-instructions.md` requires `schema_version` — not in any config file. Executor audit trail exists (68 JSONL files) but config changes are not tracked | Unknown what config was running when a loss occurred. Cannot correlate config changes with performance changes. Cannot rollback config | Git-track configs (separate repo or directory). Add `schema_version` field. Log full config diff on startup | ✅ High |

**Impact on PnL:** Medium (can't diagnose config-related losses)
**Impact on safety:** Medium
**Effort:** 4 hours
**Urgency:** Next sprint

### #10: Rotation Timeout Loop (SONIC-USDT)

| Finding | Evidence | Impact | Recommendation | Confidence |
|---------|----------|--------|----------------|------------|
| SONIC-USDT rotates 19 times in 57 minutes (every ~3.1 min) with no progress. Bot doesn't detect it's selecting the same stuck coin repeatedly | Data snapshot Section 8: 19 consecutive "MONITORING TIMEOUT" events for SONIC-USDT between 12:08–13:07 on March 8 | Wasted API calls, log pollution, prevents other coins from being evaluated. Combined with stuck order → infinite loop of futility | Add "recently rotated" cooldown: if coin was just timed-out, skip it for N minutes. Track rotation count per coin per session | ✅ High |

**Impact on PnL:** Low (wasted opportunity cost)
**Impact on safety:** Low
**Effort:** 2 hours
**Urgency:** Next sprint

---

## 3. Scaling Bottlenecks

### 3.1 What Breaks at €50K Capital?

| Component | Current State | At €50K | Projected Failure |
|-----------|--------------|---------|-------------------|
| **Kill switch** | Dead (Round 3) | Same — PnL tracker unfed | €50K with no loss limit = catastrophic risk |
| **SQLite concurrency** | `check_same_thread=False`, no WAL | More fills → more writes | Write contention under load. WAL mode required |
| **Risk checks** | Fail-open | Same | 100× the capital with same fail-open risk = 100× the exposure |
| **Emergency exit** | -12% per coin | 4 coins × -12% = €24K loss | Single flash crash → potential €24K loss with no kill switch |
| **API rate limits** | Already 336 WS errors in 3 days | More orders → more API calls | Rate limit blocking → stale data → bad decisions |

**Verdict:** The system cannot safely scale to €50K without fixing Round 3 P0 items (kill switch, fail-closed, stop-loss). The infrastructure issues are secondary to the risk management gaps.

### 3.2 What Breaks at €500K?

Everything from €50K, plus:

| Component | Projected Failure |
|-----------|-------------------|
| **Single-machine architecture** | Machine failure = total loss of control. No redundancy |
| **SQLite** | WAL mode or not, SQLite is fundamentally single-writer. At high fill rates, DB becomes bottleneck |
| **Manual operations** | Operator is single point of failure. Vacation = unmonitored bot |
| **No exchange-side stops (spot)** | €500K in spot positions with only bot-side protection → unacceptable |
| **Secrets in .env** | Machine compromise = API key theft = fund drainage |

**Verdict:** €500K requires: PostgreSQL, redundant infrastructure, HSM/vault for keys, exchange-side stops, 24/7 monitoring.

### 3.3 What Breaks at 50–100 Coins?

| Component | Current (4–6 coins) | At 50 coins | At 100 coins |
|-----------|---------------------|-------------|--------------|
| **Control tick** | 6× `for symbol in monitored_coins` loops per tick | 50× per loop = 300 iterations/tick | 600 iterations/tick |
| **Orderbook data** | 35–44% NO_ORDERBOOK_DATA already | Exponentially worse — WS subscriptions don't scale linearly | System-wide data starvation |
| **Memory** | Cleanup every 300s, caps at 50 price histories | 50 price histories × 50 coins × multiple timeframes | ~250 MB RAM estimate. Manageable but `gc.collect()` pauses increase |
| **SQLite writes** | ~270 KB/day (USD bot) | ~7 MB/day at 50 coins | WAL required, possibly concurrent DB |
| **Decision time** | 10s control_task interval | May exceed 10s with 50 coins | Tick overrun → stale decisions |

**Projected failure point for tick overrun: ~30–40 coins** (based on 6 loops × N iterations + trend calculations + API calls per tick).

### 3.4 What Breaks at 3 Exchanges Simultaneously?

| Component | Gap |
|-----------|-----|
| **No cross-exchange coordination** | No IPC, no shared state, no aggregated portfolio view |
| **Port contention** | Dashboard hardcoded to port 5000 — second instance fails |
| **Shared monitoring.db** | Single file, not per-instance — concurrent writes will corrupt |
| **API key management** | All in single `.env` — compromise one key, compromise all |
| **Correlation risk** | Already hardcoded to 0.0 for single exchange. Cross-exchange = even more correlated exposure |

### 3.5 Database at 1 GB / 10 GB

| Size | Impact | Evidence |
|------|--------|---------|
| **1 GB** (monitoring.db in ~7 months at current rate) | SQLite queries slow without VACUUM. Dashboard API responses degrade. Backup takes seconds | monitoring.db already at 320 MB with no retention |
| **10 GB** (trading DBs after years of operation) | SQLite file locking becomes bottleneck. Backup requires minutes. No migration framework = stuck with current schema | No indexes on trading DB visible in code. Query patterns scan full tables |

**Fix:** Add retention policy (7d status, 30d events, 90d trades). Run `VACUUM` weekly. Enable WAL mode. Add composite indexes.

---

## 4. Phase 1/2/3 Roadmap

### Phase 1 — Must-Fix Before Increasing Capital (1–2 Weeks)

| # | Task | Impact PnL | Impact Safety | Effort | Urgency | Priority Score |
|---|------|-----------|---------------|--------|---------|----------------|
| **1.1** | **systemd service for each bot** — `Restart=always`, `RestartSec=10`, `WatchdogSec=60` | High | Critical | 2h | Immediate | **P0** |
| **1.2** | **Auto-cancel stale orders** — cancel after 30min timeout, free locked capital | High | Medium | 4h | Immediate | **P0** |
| **1.3** | **Daily SQLite backup cron** — `.backup` command, 7-day retention, test restore | Medium | High | 1h | Immediate | **P0** |
| **1.4** | **Monitoring DB retention** — delete status >7d, events >30d, trades >90d. Run on startup + daily | Medium | High | 2h | Immediate | **P0** |
| **1.5** | **Log cleanup cron** — delete JSONL events >14d, compress logs >7d | Low | Medium | 1h | Immediate | **P0** |
| **1.6** | **SQLite WAL mode** — add `PRAGMA journal_mode=WAL` to all SQLite connections | Low | Medium | 30min | Immediate | **P0** |
| **1.7** | **Fix Round 3 P0 items** — wire kill switch, fail-closed, stop-loss (see Round 3 Appendix B) | High | Critical | 4d | Immediate | **P0** |
| **1.8** | **Health check endpoint** — `/health` returning `{"ok": true, "last_tick": <timestamp>}` on dashboard | High | High | 2h | Immediate | **P1** |
| **1.9** | **Distinct error logging** — suppress repeated identical errors (e.g., 368× "Insufficient capital"), log count instead | Low | Low | 2h | Immediate | **P1** |
| **1.10** | **Fix duplicate logging** — remove copy-paste duplicate at controller L8453–8462 | Low | Low | 5min | Immediate | **P1** |

**Total Phase 1 effort: ~6 days** (including Round 3 P0 items)

### Phase 2 — Robustness for Unattended Operation (2–4 Weeks)

| # | Task | Impact PnL | Impact Safety | Effort | Urgency |
|---|------|-----------|---------------|--------|---------|
| **2.1** | **External uptime monitoring** — healthchecks.io or UptimeKuma pinging `/health` every 60s, alert on miss | High | High | 4h | Next sprint |
| **2.2** | **WebSocket stability investigation** — root cause 336 WS errors, fix keepalive/reconnect, add WS health metric | High | Medium | 2d | Next sprint |
| **2.3** | **Cross-bot portfolio view** — single dashboard aggregating all bot instances' PnL, exposure, status | Medium | Medium | 3d | Next sprint |
| **2.4** | **Config versioning** — add `schema_version` to all YAMLs, log full config on startup, git-track configs | Medium | Medium | 4h | Next sprint |
| **2.5** | **Rotation cooldown** — skip coins that timed-out within last N minutes, log rotation loops as anomaly | Low | Low | 2h | Next sprint |
| **2.6** | **Instance-isolate monitoring** — per-bot monitoring.db, per-bot dashboard port (configurable) | Medium | Medium | 4h | Next sprint |
| **2.7** | **Remove `gc.collect()` from hot path** — move to cleanup routine only (already runs every 300s) | Low | Low | 30min | Next sprint |
| **2.8** | **Integration tests for deploy** — pytest suite that verifies config loads, risk checks work, DB connects | Medium | High | 3d | Next sprint |
| **2.9** | **Deploy script with git tags** — `git tag v1.X.X`, systemctl restart, rollback = checkout previous tag | Low | Medium | 4h | Next sprint |
| **2.10** | **Telegram alert for monitoring process death** — external watchdog (systemd) for collector/dashboard | Medium | High | 2h | Next sprint |

**Total Phase 2 effort: ~3 weeks**

### Phase 3 — Professional Infrastructure (1–2 Months)

| # | Task | Impact PnL | Impact Safety | Effort | Urgency |
|---|------|-----------|---------------|--------|---------|
| **3.1** | **Prometheus + Grafana** — export metrics (PnL, exposure, fill rate, latency, error rate), dashboard with alerts | High | High | 1w | Backlog |
| **3.2** | **Containerize all bots** — Docker Compose with restart policies, health checks, log drivers | Medium | Medium | 1w | Backlog |
| **3.3** | **Centralized logging** — Loki + Promtail or ELK, structured JSON logs, cross-bot search | Medium | Medium | 1w | Backlog |
| **3.4** | **A/B testing framework** — run paper + live bot with same market data, compare fill rates and PnL | High | Low | 2w | Backlog |
| **3.5** | **Performance regression detection** — track fill rate, tick duration, memory per deploy, alert on degradation | Medium | Medium | 1w | Backlog |
| **3.6** | **Secret management** — HashiCorp Vault or AWS Secrets Manager for API keys, remove `.env` files | Low | High | 3d | Backlog |
| **3.7** | **Database migration framework** — Alembic or custom versioned migrations, automated schema upgrades | Low | Medium | 1w | Backlog |
| **3.8** | **Split the God class** — Round 2 recommendation: extract coordinator, entry logic, exit logic, risk module | High | High | 3w | Backlog |
| **3.9** | **Redundant infrastructure** — standby machine with DB replication, automatic failover | Low | High | 2w | Backlog |
| **3.10** | **Incident response playbook** — tested procedures for: bot crash, exchange down, flash crash, DB corruption, API key compromise | Low | High | 3d | Backlog |

**Total Phase 3 effort: ~2 months**

---

## 5. Infrastructure Recommendations

Concrete tools, not generic advice. Each chosen for: minimal overhead, single-operator-friendly, open-source.

### 5.1 Process Supervision: systemd

```ini
# /etc/systemd/system/bot-kraken-usd.service
[Unit]
Description=Multi-Coin Grid Bot (Kraken USD)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=mo
WorkingDirectory=/home/mo/repos/hummingbot
EnvironmentFile=/home/mo/repos/hummingbot/.env
ExecStart=/home/mo/.venvs/bot/bin/python bin/hummingbot.py
Restart=always
RestartSec=10
WatchdogSec=120
StandardOutput=append:/home/mo/repos/hummingbot/logs/systemd-kraken-usd.log
StandardError=append:/home/mo/repos/hummingbot/logs/systemd-kraken-usd-err.log

[Install]
WantedBy=multi-user.target
```

**Why systemd:** Already on every Linux machine. No extra dependencies. Automatic restart, journal integration, watchdog support.

### 5.2 External Health Monitoring: healthchecks.io

Free tier (20 checks). Bot pings a URL every 60s from the health check endpoint. If ping misses 2× in a row → email/Telegram alert.

**Why healthchecks.io:** Zero infrastructure to maintain. Free. Integrates with Telegram.

### 5.3 Database Backup: cron + sqlite3 .backup

```bash
# /etc/cron.d/bot-backup
0 3 * * * mo cd /home/mo/repos/hummingbot && ./scripts/backup_dbs.sh
```

```bash
#!/bin/bash
# scripts/backup_dbs.sh
BACKUP_DIR="data/backup/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"
for db in data/*.sqlite; do
    sqlite3 "$db" ".backup $BACKUP_DIR/$(basename $db)"
done
# Retain 7 days
find data/backup -maxdepth 1 -mindepth 1 -type d -mtime +7 -exec rm -rf {} +
```

**Why sqlite3 .backup:** Consistent snapshot even during writes. Built-in SQLite command.

### 5.4 Monitoring (Phase 3): Prometheus + Grafana

- **node_exporter** for system metrics (CPU, RAM, disk)
- **Custom Python exporter** exposing: daily PnL, exposure per coin, fill rate, tick duration, WS error count, kill switch status
- **Grafana** dashboards with alert rules: PnL < -3%, fill rate < 1%, tick duration > 10s, no heartbeat

**Why Prometheus/Grafana:** Industry standard. Single binary each. Can run on same machine.

### 5.5 Log Aggregation (Phase 3): Loki + Promtail

Lightweight compared to ELK. Grafana integration. Labels per bot instance. Query language (LogQL) for cross-bot search.

### 5.6 Uptime Check: UptimeKuma (self-hosted alternative)

If preferring self-hosted: UptimeKuma in a Docker container. Monitors `/health` endpoints for all bots + monitoring services.

---

## 6. What to Keep

### 6.1 Monitoring Stack Architecture — ⭐ Good Foundation

The 4-service monitoring design (collector + dashboard + Telegram + risk monitor) is well-architected for a single-operator setup:

| Component | Verdict | Why |
|-----------|---------|-----|
| **DataCollector** (446 lines) | Keep | Clean separation of concerns. Regex-based log parsing is pragmatic. 10s collection interval is appropriate |
| **Flask Dashboard** (403 lines) | Keep | Simple, functional. Chart.js for PnL visualization. Auto-refresh every 5s |
| **TelegramBotHandler** (452 lines) | Keep | Good command set (`/vertel`, `/status`, `/trades`, `/pnl`). Dutch-first UX matches operator. Polling-based (simple) |
| **RiskMonitor** (546 lines) | Keep | Standalone ccxt-based market scanner. Exchange-agnostic. Configurable universe. Good separation from bot process |

**What to fix:** Add retention, instance isolation, and health endpoints — but the foundation is solid.

### 6.2 EventLogger — Good Design

- Feature-flagged (safe default: off) ✅
- JSONL format (machine-parseable) ✅
- Buffered writes with auto-flush ✅
- Config hash for run tracking ✅
- Silent failure (never breaks trading) ✅
- Correlation ID tracking ✅

**Missing:** File rotation and retention. Currently creates a new file per bot start but never deletes old ones.

### 6.3 WHY-NO-TRADE Reporting — Unique Strength

Hourly diagnostic reports showing rejection reasons per pipeline stage are genuinely useful and uncommon even in professional setups. The breakdown by `ReasonCode` (NO_ORDERBOOK_DATA, RSI_OVERBOUGHT, etc.) provides immediate diagnostic value.

**This single feature has more operational value than all the trading results combined** — it correctly identifies that the #1 problem is data pipeline (35–44% NO_ORDERBOOK_DATA), not strategy.

### 6.4 TradeAnalyzer — Solid FIFO Matching

The `TradeAnalyzer` (666 lines) implements proper FIFO buy/sell matching with proportional fee allocation. It reads directly from SQLite (primary) with log file fallback. The dual-source approach is robust.

### 6.5 Audit Trail — Good Start

68 daily JSONL files with executor-level audit data including config snapshots, MFE/MAE, duration, fees. Version-tagged records (`"version": "1.0"`).

**Missing:** Tamper evidence, config change auditing, retention policy.

### 6.6 Pydantic Config Model — Well-Structured

1,611-line model with field validators, `ge`/`le` constraints, aliases, `extra="forbid"`. Plus a separate semantic `ConfigValidator` checking expectancy, RSI thresholds, min notional.

**Missing:** Schema versioning (documented but not implemented).

### 6.7 Pre-commit Hooks — Good Gates

Flake8, private key detection, autopep8, isort, detect-wallet-private-key. **But:** the broad regex exclusion pattern (`^(analyze_.*|test_.*|demo_.*|fix_.*|...)$`) exempts all root-level scripts from linting.

### 6.8 CI/CD Pipeline — Functional

GitHub Actions with: pre-commit, pytest + coverage, 80% diff-cover requirement, Docker builds on merge. Discord notifications.

---

## 7. Capital Scaling Verdict

### Current Controls → **Paper Trading Only**

**Maximum capital I would trust with CURRENT operational maturity: €0 (paper only)**

This is the same verdict as Round 3, now further reinforced by:

| Criterion | Status |
|-----------|--------|
| Process supervision | ❌ No auto-restart — bot dies silently |
| Health monitoring | ❌ No liveness checks — operator unaware of failures |
| Database backups | ❌ No automated backups — data loss on corruption |
| Disk management | ❌ 6.3 GB logs, 320 MB monitoring DB, no retention |
| Deploy process | ❌ Manual copy + restart — no rollback |
| Kill switch | ❌ Dead (Round 3 — PnL tracker unfed) |
| Stale order recovery | ❌ Alert-only — 2/3 bots blocked |

### Upgrade Path

#### Tier 1: Paper → Small Live (< €500)
**Requires Phase 1 complete:**

| Item | Round | Effort |
|------|-------|--------|
| Wire kill switch (Round 3 #1) | R3 | 4h |
| Fail-closed risk checks (Round 3 #2) | R3 | 30min |
| Kill switch closes positions (Round 3 #3) | R3 | 1d |
| Enable stop-loss (Round 3 #7) | R3 | 15min |
| Emergency exit cooldown (Round 3 #4) | R3 | 2h |
| Daily loss limit to 3% (Round 3 #6) | R3 | 15min |
| systemd service (Round 4 #1.1) | R4 | 2h |
| Auto-cancel stale orders (Round 4 #1.2) | R4 | 4h |
| Daily DB backups (Round 4 #1.3) | R4 | 1h |
| Monitoring DB retention (Round 4 #1.4) | R4 | 2h |
| Log cleanup cron (Round 4 #1.5) | R4 | 1h |
| WAL mode (Round 4 #1.6) | R4 | 30min |
| Health check endpoint (Round 4 #1.8) | R4 | 2h |

**Total: ~6 days. After this, bot is safe for ≤ €500 with daily monitoring.**

#### Tier 2: Small → Medium (€500–€5,000)
**Requires Phase 1 + Phase 2 core:**

| Additional Items | Round | Effort |
|-----------------|-------|--------|
| External uptime monitoring (Round 4 #2.1) | R4 | 4h |
| WebSocket stability fix (Round 4 #2.2) | R4 | 2d |
| Cross-bot dashboard (Round 4 #2.3) | R4 | 3d |
| Config versioning (Round 4 #2.4) | R4 | 4h |
| HWM drawdown (Round 3 #7) | R3 | 1d |
| Correlation risk (Round 3 #6) | R3 | 2d |
| Exchange-side stops for spot (Round 3 #5) | R3 | 3d |
| Integration test suite (Round 4 #2.8) | R4 | 3d |
| Persist entry prices (Round 3 #9) | R3 | 4h |
| **Fix the 98% no-fill rate** (Round 1) | R1 | Variable |

**Additional ~3 weeks. Requires operator monitoring 1x/day minimum.**

#### Tier 3: Medium → Larger (€5,000–€50,000)
**Requires Phase 1 + 2 + Phase 3 core:**

| Additional Items | Effort |
|-----------------|--------|
| Prometheus + Grafana | 1w |
| Containerized deployment | 1w |
| Secret management (Vault/similar) | 3d |
| Incident response playbook (tested) | 3d |
| Split God class (Round 2) | 3w |
| Redundant infrastructure | 2w |
| Proven positive EV over 1000+ fills | Variable |

#### Tier 4: Professional (> €50,000)
**Not achievable with current architecture.** Would require:
- Ground-up rewrite of the controller
- PostgreSQL with proper ORM
- HSM for key management
- Multi-region deployment
- 24/7 monitoring team or on-call rotation
- Formal risk model with exchange-certified controls
- Regulatory compliance review

---

## 8. Final Verdict

### What Is the Ceiling of This System?

**With current state: €0 (paper trading).** Two of three bots can't even trade due to stuck orders.

**With Phase 1 complete (~6 days): €500.** Functional risk controls, process supervision, basic backups. Still manual operations, still a hobby project — but a safe one.

**With Phase 1+2 complete (~1 month): €5,000.** Monitored, versioned, tested. WebSocket stability addressed. Cross-bot visibility. Still single-machine, still SQLite, still requires daily operator attention.

**With Phase 1+2+3 complete (~3 months): €50,000 theoretical ceiling.** Professional monitoring, containerized, redundant. But this assumes the core strategy produces positive expected value — which Round 1 found it does not.

### The Honest Assessment

The infrastructure investment is premature. The system has:
- A monitoring stack more sophisticated than most hobby bots ✅
- 79 well-structured tests ✅
- Good diagnostic tools (WHY-NO-TRADE, audit trail) ✅
- Thorough documentation ✅

But it also has:
- A dead kill switch ❌
- 98.3% of executors never fill ❌
- Negative expected value across all instances ❌
- 2/3 bots unable to trade ❌
- No process supervision on a system managing real money ❌

**The monitoring infrastructure is watching a bot that doesn't work.** The priority order should be:

1. **Fix risk controls** (Round 3 P0) — so it can't lose catastrophically
2. **Fix the fill rate** (Round 1) — so it can actually trade
3. **Add process supervision** (Round 4 Phase 1) — so it stays running
4. **Everything else** — monitoring, containerization, scaling

The ceiling is not determined by infrastructure — it's determined by whether the strategy can produce positive returns. No amount of Prometheus/Grafana will fix a 98.3% no-fill rate.

---

## 9. Confidence Classification

### Confirmed Findings (Direct Evidence)

| Finding | Evidence |
|---------|----------|
| No systemd/supervisord | Grep for `.service`, `supervisord`, `Procfile` — zero results |
| Docker restart policy disabled | `docker-compose.yml` L33: `restart: always` commented out |
| monitoring.db at 320 MB with no retention | `ls -lh multi_coin_grid_pro/data/monitoring.db` → 320M, `database.py` has no DELETE/purge |
| 6.3 GB log directory | `du -sh logs/` → 6.3G |
| No automated backups | `data/backup/` has 6 files from Dec 2025 migration only |
| 336 WebSocket errors in 3 days | Log analysis from data snapshot |
| 368 identical "Insufficient capital" errors | Data snapshot Section 6: Bitget Spot |
| 79 test files with assertions in multi_coin_grid_pro | `find` + `grep assert` count |
| 12/15 root test files have no assertions | Direct grep of each root test file |
| Pre-commit excludes root scripts from flake8 | `.pre-commit-config.yaml` L12: broad regex pattern |
| No `schema_version` in any config | Documented as requirement, not implemented |
| Duplicate logging at L8453–8462 | Code inspection: identical block copy-pasted |
| `gc.collect()` in control_task hot path | L2129–2131 |
| monitoring.db grows ~3.5 MB/day | 320 MB / ~3 months |
| No WAL mode on any SQLite DB | Grep for `journal_mode`, `wal` → zero results in Python code |
| Dashboard port hardcoded to 5000 | `config.py` L48: `DASHBOARD_PORT = 5000` |
| Single shared monitoring.db not instance-isolated | Only one DB path, no instance_id parameter |
| Audit trail exists (68 files) | `audits/` directory with daily JSONL files |

### Reasonable Inferences (High Confidence)

| Finding | Basis |
|---------|-------|
| Bot has crashed and gone unnoticed before | No auto-restart + no external monitoring + no operator alerting on process death |
| Disk will fill within ~6 months at current rate | 6.3 GB logs + 320 MB monitoring DB + 399 MB events + ~3.5 MB/day growth |
| Second bot instance would have port conflict | Hardcoded port + shared monitoring.db + `pgrep` check doesn't differentiate instances |
| Config changes have caused losses that weren't diagnosed | 800+ line configs with no versioning, no diff logging, "temporary" 30% loss limit unchanged for 13 months |

### Unknowns — Requires More Data

| Question | Data Needed |
|----------|-------------|
| Actual bot crash frequency in production | Systemd journal or `uptime` tracking (currently none) |
| Has monitoring.db corruption occurred? | `PRAGMA integrity_check` on monitoring.db |
| Are WebSocket errors causing the 35–44% NO_ORDERBOOK_DATA? | Correlation analysis: WS error timestamps vs NO_ORDERBOOK_DATA events |
| What is the tick duration under current load? | Profile `control_task()` execution time. Is it exceeding the 10s interval? |
| Is the `gc.collect()` actually causing measurable latency? | Benchmark with and without the call |
| How does memory grow over multi-day runs? | RSS tracking over 7+ days (hourly logs exist in code but need analysis) |

---

## Appendix A: Quick-Reference for Phase 1 Implementation Order

Execute in this order to minimize risk window:

| Step | Task | Time | Cumulative |
|------|------|------|------------|
| 1 | `systemctl` service for each bot | 2h | 2h |
| 2 | Wire kill switch (Round 3) | 4h | 6h |
| 3 | Fail-closed risk checks (Round 3) | 30min | 6.5h |
| 4 | Enable stop-loss, reduce daily limit | 30min | 7h |
| 5 | Kill switch closes positions (Round 3) | 1d | 2d |
| 6 | Emergency exit cooldown (Round 3) | 2h | 2.3d |
| 7 | Auto-cancel stale orders | 4h | 2.8d |
| 8 | WAL mode on all SQLite | 30min | 2.8d |
| 9 | DB backup cron | 1h | 2.9d |
| 10 | Monitoring DB retention | 2h | 3.2d |
| 11 | Log cleanup cron | 1h | 3.3d |
| 12 | Health check endpoint | 2h | 3.5d |
| 13 | Persist entry prices (Round 3) | 4h | 4d |
| 14 | Suppress repeated errors | 2h | 4.3d |
| 15 | Fix duplicate logging bug | 5min | 4.3d |
| | **Total** | | **~4.5 days** |

After step 7, restart both blocked bots — they should be able to trade again.
