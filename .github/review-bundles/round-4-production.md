# Round 4: Production Readiness & Observability Review

> **Hoe te gebruiken**: Open een VERSE Claude Opus (of o3) sessie.
> Plak deze volledige inhoud als eerste bericht.
> Alles zit erin — geen extra file uploads nodig.
>
> **Snapshot datum**: 2026-03-08

---

## Prompt

## Round 4: Production Readiness & Roadmap

```
Act as a DevOps/SRE engineer and trading infrastructure architect who
has deployed and operated crypto trading bots at scale. You evaluate
production readiness, operational maturity, and what separates a
hobby bot from professional infrastructure.

## Current operational setup
- Runs on a single Linux machine
- Python 3.11+, Hummingbot framework
- **3 active bot instances**: Kraken USD, Bitget Spot, Bitget Futures
- 4 SQLite trade databases (3–12 MB each) + 3 cooldown DBs
- Telegram bot for alerts (critical, warnings, status)
- Structured event logging via custom EventLogger
- WHY-NO-TRADE diagnostic reports (hourly)
- Console status reporting via to_format_status()
- No containerization in production
- Manual sync between two code directories
- Start scripts: start_bot.sh, start_bot_usd.sh, start_hummingbot.sh

## Current state of bots (March 8, 2026)
- **Kraken USD**: Running but Risk Manager blocks most trades (WR 30%)
- **Bitget Spot**: BLOCKED — insufficient capital ($3.62 free)
- **Bitget Futures**: BLOCKED — insufficient capital ($9 free)
- Only 1 of 3 bots is actively attempting to trade

## Current monitoring & observability
- EventLogger: structured events for signals, risk blocks, orders, fills, PnL
- WhyNoTrade diagnostics: hourly summaries per bot with rejection breakdown
- Console status: multi-section formatted output (positions, PnL, regime, slots)
- Telegram: real-time alerts for trades, risk events, anomalies
- Per-bot report logs: bitget_multi_coin_grid_report_*.log, kraken_*_report_*.log
- No Prometheus/Grafana, no centralized logging, no alerting rules
- No cross-bot dashboard or aggregated P&L view

## Known operational issues
- WebSocket instability on Kraken (112+ errors in current session)
- Bitget Spot: stuck LIMIT SELL order blocks all trading ($71 locked)
- Bitget Futures: insufficient capital after losses ($9 of $50 remains)
- Memory leak (fixed but indicates potential for regression)
- Manual code deployment (copy files between two directories)
- No automated testing in CI/CD
- No config validation beyond Pydantic (no semantic validation)
- Restart recovery: orphan detection + stale cleanup exist but alert-only
- Rotation timeout loops: SONIC-USDT rotates every 3 min without progress
- Risk Manager pause has no automatic recovery path
- NO_ORDERBOOK_DATA is #1 rejection reason across all bots (35–44%)

## What I need you to evaluate

### 1. Maturity assessment
Rate on a scale: hobby → intermediate → advanced → professional → institutional
For each dimension:
- Code quality and maintainability
- Testing and CI/CD
- Monitoring and alerting
- Deployment and operations
- Disaster recovery
- Documentation

### 2. What would break at scale?
- What if capital grows to €50K? €500K?
- What if number of coins grows to 50? 100?
- What if running on 3 exchanges simultaneously?
- Database performance at 1 GB? 10 GB?
- Memory usage with 50 concurrent executors?

### 3. Operational gaps
- No health checks, no auto-restart, no process supervision
- No database backup strategy
- No config change audit trail
- No A/B testing framework for strategy changes
- No performance regression detection

### 4. Professionalization roadmap
Build a phased plan with effort estimates:

**Phase 1 — Must-fix (1–2 weeks)**
What needs to happen before increasing capital?

**Phase 2 — Robustness (2–4 weeks)**
What makes this bot reliable for unattended operation?

**Phase 3 — Professional (1–2 months)**
What turns this into infrastructure you'd trust with serious money?

## Attachments I'll provide
- [ ] Start scripts and deployment setup
- [ ] Monitoring module source
- [ ] EventLogger source
- [ ] **Data snapshot** (`.github/data-snapshot-YYYY-MM-DD.md` — operational state + logs)

## Output format requirements (apply to all findings)

For every major conclusion, provide an evidence table:

| Finding | Evidence (code/config/logs/data) | Impact | Recommendation | Confidence (high/med/low) |
|---------|----------------------------------|--------|----------------|---------------------------|
| ...     | ...                              | ...    | ...            | ...                       |

Separate clearly between:
- **Confirmed findings** — directly proven from code, logs, or data
- **Reasonable inferences** — likely true but not fully proven
- **Unknowns** — requires more data to determine (state what data is needed)

For each roadmap item, rate:
- **Impact on PnL** (high / medium / low)
- **Impact on safety** (high / medium / low)
- **Implementation effort** (hours / days / weeks)
- **Urgency** (immediate / next sprint / backlog)

## What to keep
Identify which operational components, monitoring tools, or infrastructure
choices are already good and should be preserved. Avoid recommending
replacement of things that work well.

## Capital scaling verdict
Based on the production readiness review, state the maximum capital you
would trust this bot with given the CURRENT operational maturity:
- [ ] Paper trading only
- [ ] Small live capital (< €500)
- [ ] Medium live capital (€500–€5,000)
- [ ] Larger serious capital (€5,000–€50,000)
- [ ] Professional capital (> €50,000)

State which Phase roadmap items must complete for each tier upgrade.

## Expected output
1. **Maturity scorecard** (per dimension)
2. **Top 10 operational risks** ranked (evidence table format)
3. **Scaling bottlenecks** with projected failure points
4. **Phase 1/2/3 roadmap** with specific tasks, effort estimates, and priority×effort scores
5. **Infrastructure recommendations** (concrete tools, not generic advice)
6. **What to keep**: operational choices that are already working well
7. **Capital scaling verdict**: current max safe capital + phase gates
8. **Final verdict**: what's the ceiling of this system?
```

---

## Data Extraction

All queries and commands are documented in the data snapshot file.
Before each review round:

1. Copy `.github/data-snapshot-2026-03-08.md` to a new file with today's date
2. Re-run the queries from the "How to regenerate" section at the top
3. Update the tables with fresh results
4. Attach the new snapshot file with the review round


---

## Attachment: start_bot.sh (Bitget Spot) (68 lines)

```bash
#!/bin/bash
# Multi-Coin Grid Pro - Direct Launcher (All-in-One)
# Loads .env and starts bot_v2.py directly

set -e  # Exit on error

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "🚀 Multi-Coin Grid Pro Bot - Quick Start"
echo "=================================================="
echo ""

# Load .env for API keys
if [ -f .env ]; then
    echo "✅ Loading environment variables from .env..."
    set -a
    source .env
    set +a
else
    echo "❌ ERROR: .env file not found!"
    echo "   Copy .env.example to .env and fill in your API keys"
    exit 1
fi

# Verify required variables
if [ -z "$KRAKEN_API_KEY" ] || [ -z "$KRAKEN_SECRET_KEY" ]; then
    echo "❌ ERROR: KRAKEN_API_KEY or KRAKEN_SECRET_KEY not set in .env"
    exit 1
fi

echo "✅ API keys loaded from .env"
echo ""

# Check if virtualenv exists
if [ ! -d "multi_coin_grid_pro/venv" ]; then
    echo "📦 Creating virtual environment..."
    cd multi_coin_grid_pro
    python3 -m venv venv
    source venv/bin/activate
    echo "📥 Installing dependencies..."
    pip install --upgrade pip > /dev/null 2>&1
    pip install -r requirements.txt > /dev/null 2>&1
    echo "✅ Virtual environment created & dependencies installed"
    cd ..
else
    echo "✅ Virtual environment exists"
fi

echo ""
echo "=================================================="
echo "🏃 Starting Multi-Coin Grid Bot V2"
echo "=================================================="
echo ""
echo "Config: multi_coin_grid_pro/config/config.prod.yaml"
echo "Logs: logs/logs_multi_coin_grid_v2_*.log"
echo ""
echo "Press Ctrl+C to stop the bot"
echo ""
echo "=================================================="
echo ""

# Activate venv and run bot
cd multi_coin_grid_pro
source venv/bin/activate
python3 bot_v2.py

```

## Attachment: start_bot_usd.sh (Kraken USD) (68 lines)

```bash
#!/bin/bash
# Multi-Coin Grid Pro - USD Research Bot (Option C)
# Parallel test with USD pairs for liquidity comparison

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "🔬 Multi-Coin Grid Pro - USD RESEARCH Bot"
echo "=================================================="
echo ""
echo "⚠️  RESEARCH MODE: USD pairs for comparison"
echo "   EUR bot should be running in parallel"
echo ""

# Load .env for API keys
if [ -f .env ]; then
    echo "✅ Loading environment variables from .env..."
    set -a
    source .env
    set +a
else
    echo "❌ ERROR: .env file not found!"
    exit 1
fi

# Verify API keys
if [ -z "$KRAKEN_API_KEY" ] || [ -z "$KRAKEN_SECRET_KEY" ]; then
    echo "❌ ERROR: KRAKEN_API_KEY or KRAKEN_SECRET_KEY not set in .env"
    exit 1
fi

echo "✅ API keys loaded"
echo ""

# Set environment for USD config
export BOT_ENV="usd"

echo "=================================================="
echo "🏃 Starting USD Research Bot"
echo "=================================================="
echo ""
echo "Config: multi_coin_grid_pro/config/config.usd.yaml"
echo "Quote: USD"
echo "Capital: ~$110 (€100 equivalent)"
echo "Logs: logs/multi_coin_grid_usd.log"
echo ""
echo "Press Ctrl+C to stop the bot"
echo ""
echo "=================================================="
echo ""

# Activate venv and run bot
cd multi_coin_grid_pro
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip > /dev/null 2>&1
    pip install -r requirements.txt > /dev/null 2>&1
    echo "✅ Virtual environment ready"
else
    source venv/bin/activate
fi

python3 bot_v2.py

```

## Attachment: start_hummingbot.sh (5 lines)

```bash
#!/bin/bash
# Hummingbot launcher with python3

cd /home/mo/repos/hummingbot
exec ~/.venvs/bot/bin/python bin/hummingbot.py "$@"

```

## Attachment: event_logger.py (388 lines)

```python
"""
Structured event logger for observability (JSONL format).

Writes events to JSONL file (one event per line) for offline analysis.
Feature-flagged via config: observability.structured_events_enabled

Design principles:
- Synchronous buffered writes (simple, reliable)
- One event per line (JSONL format)
- Feature-flagged (safe default: off)
- Correlation ID tracking for intent lineage
"""

import hashlib
import json
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage
except ImportError:
    # Fallback for tests/standalone usage
    ReasonCode = None
    Stage = None


class EventLogger:
    """
    Lightweight JSONL event logger with buffered writes.

    Usage:
        logger = EventLogger(enabled=True, output_dir="logs/events")
        logger.emit_gate_denied(
            correlation_id="abc123",
            symbol="BTC-EUR",
            stage=Stage.SMART_ENTRY,
            reason_code=ReasonCode.RSI_OVERBOUGHT,
            metadata={"rsi": 75.3}
        )
        logger.flush()  # Force write buffer to disk
    """

    def __init__(
        self,
        enabled: bool = False,
        output_dir: str = "logs/events",
        buffer_size: int = 100,
        config_hash: Optional[str] = None,
    ):
        """
        Initialize EventLogger.

        Args:
            enabled: Enable event logging (default: False for safety)
            output_dir: Directory for event files
            buffer_size: Number of events to buffer before auto-flush
            config_hash: Config hash for run tracking
        """
        self.enabled = enabled
        self.output_dir = Path(output_dir)
        self.buffer_size = buffer_size
        self.config_hash = config_hash

        self.buffer = []
        self.file_handle = None
        self.logger = logging.getLogger(__name__)

        if self.enabled:
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"events_{timestamp}.jsonl"
                self.file_path = self.output_dir / filename
                self.file_handle = open(self.file_path, "a", buffering=1)  # Line buffered
                self.logger.info(f"📝 EventLogger initialized: {self.file_path}")

                # Emit config_loaded event
                if config_hash:
                    self.emit_config_loaded(config_hash)
            except Exception as e:
                # If we can't initialize, disable gracefully
                self.logger.error(f"EventLogger initialization failed - disabling: {e}")
                self.enabled = False
                self.file_handle = None

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Internal: emit event to buffer.

        Args:
            event_type: Event type identifier
            data: Event data dict
        """
        if not self.enabled:
            return

        try:
            event = {
                "ts": time.time(),
                "event_type": event_type,
                "config_hash": self.config_hash,
                **data
            }

            # Convert Decimal/Enum to JSON-safe types
            event = self._serialize(event)

            self.buffer.append(event)

            if len(self.buffer) >= self.buffer_size:
                self.flush()
        except Exception as e:
            # CRITICAL: Never let event logging break trading
            self.logger.error(f"EventLogger._emit failed (non-fatal): {e}")
            # Continue silently - observability is nice-to-have, not critical

    def _serialize(self, obj: Any) -> Any:
        """
        Recursively convert Decimal/Enum types to JSON-safe types.

        Args:
            obj: Object to serialize

        Returns:
            JSON-safe representation
        """
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: self._serialize(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._serialize(v) for v in obj]
        elif Stage and isinstance(obj, Stage):
            return obj.value
        elif ReasonCode and isinstance(obj, ReasonCode):
            return obj.value
        else:
            return obj

    def flush(self) -> None:
        """Write buffer to disk and clear."""
        if not self.enabled or not self.buffer:
            return

        # Check if file_handle is valid before writing
        if not self.file_handle:
            self.logger.debug("EventLogger file handle not available, clearing buffer")
            self.buffer.clear()
            return

        try:
            for event in self.buffer:
                json_line = json.dumps(event)
                self.file_handle.write(json_line + "\n")
            self.file_handle.flush()
            self.buffer.clear()
        except Exception as e:
            # Non-fatal: log but don't raise
            self.logger.error(f"Failed to flush events (non-fatal): {e}")
            # Clear buffer anyway to prevent memory buildup
            self.buffer.clear()

    def close(self) -> None:
        """Close the event logger and flush any remaining events."""
        try:
            self.flush()
            if self.file_handle:
                self.file_handle.close()
                self.file_handle = None
        except Exception as e:
            # Best effort close - log but don't raise
            self.logger.error(f"EventLogger.close failed (non-fatal): {e}")

    # ===== Event Emission Methods =====

    def emit_config_loaded(self, config_hash: str, config_keys: Optional[Dict] = None) -> None:
        """
        Emit config_loaded event at startup.

        Args:
            config_hash: Hash of config for run tracking
            config_keys: Optional dict of key config values
        """
        self._emit("config_loaded", {
            "config_hash": config_hash,
            "config_keys": config_keys or {}
        })

    def emit_intent_created(
        self,
        correlation_id: str,
        symbol: str,
        side: str,
        size: float,
        urgency: str = "NORMAL"
    ) -> None:
        """
        Emit intent_created event.

        Args:
            correlation_id: Intent correlation ID
            symbol: Trading pair
            side: BUY or SELL
            size: Intent size (quote currency)
            urgency: Urgency level
        """
        self._emit("intent_created", {
            "correlation_id": correlation_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "urgency": urgency
        })

    def emit_gate_denied(
        self,
        correlation_id: str,
        symbol: str,
        stage: 'Stage',
        reason_code: 'ReasonCode',
        reason_msg: str,
        metadata: Optional[Dict] = None,
        connector: Optional[str] = None
    ) -> None:
        """
        Emit gate_denied event (rejection).

        Args:
            correlation_id: Intent correlation ID
            symbol: Trading pair
            stage: Pipeline stage where rejection occurred
            reason_code: Structured reason code
            reason_msg: Human-readable reason
            metadata: Optional additional context
            connector: Exchange connector name (kraken, bitget, etc.)
        """
        self._emit("gate_denied", {
            "correlation_id": correlation_id,
            "symbol": symbol,
            "stage": stage,
            "reason_code": reason_code,
            "reason_msg": reason_msg,
            "metadata": metadata or {},
            "connector": connector
        })

    def emit_gate_passed(
        self,
        correlation_id: str,
        symbol: str,
        stage: 'Stage',
        metadata: Optional[Dict] = None,
        connector: Optional[str] = None
    ) -> None:
        """
        Emit gate_passed event (approval at stage).

        Args:
            correlation_id: Intent correlation ID
            symbol: Trading pair
            stage: Pipeline stage that passed
            metadata: Optional additional context
            connector: Exchange connector name (kraken, bitget, etc.)
        """
        self._emit("gate_passed", {
            "correlation_id": correlation_id,
            "symbol": symbol,
            "stage": stage,
            "metadata": metadata or {},
            "connector": connector
        })

    def emit_order_submitted(
        self,
        correlation_id: str,
        symbol: str,
        order_id: str,
        side: str,
        price: float,
        amount: float
    ) -> None:
        """
        Emit order_submitted event.

        Args:
            correlation_id: Intent correlation ID
            symbol: Trading pair
            order_id: Exchange order ID
            side: BUY or SELL
            price: Order price
            amount: Order amount
        """
        self._emit("order_submitted", {
            "correlation_id": correlation_id,
            "symbol": symbol,
            "order_id": order_id,
            "side": side,
            "price": price,
            "amount": amount
        })

    def emit_entry_guard_evaluation(
        self,
        connector: str,
        symbol: str,
        decision: str,
        regime: str = "NEUTRAL",
        reject_reason: Optional[str] = None,
        metrics: Optional[Dict[str, Optional[float]]] = None,
        thresholds: Optional[Dict[str, float]] = None,
        cooldown_remaining_sec: Optional[int] = None,
        mode: str = "live",
        correlation_id: Optional[str] = None
    ) -> None:
        """
        Emit entry_guard_evaluation event (EPIC v3.4 Story 6).

        Logs momentum health guard decisions for analysis and tuning.

        Args:
            connector: Exchange connector name ("kraken", "bitget")
            symbol: Trading pair (e.g., "PEPE-EUR", "BTC-USDT")
            decision: "ACCEPTED" or "REJECTED"
            regime: Market regime ("BULL", "CHOP", "BEAR", "NEUTRAL")
            reject_reason: Rejection reason code (e.g., "VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH")
            metrics: Momentum metrics dict with keys:
                - vwap_deviation_pct
                - vwap_slope_5m_pct (optional, for Story 9)
                - vwap_slope_15m_pct
                - accel_5m_pct
                - accel_15m_pct
            thresholds: Thresholds used for evaluation:
                - deviation_high_pct
                - slope_min_pct_5m (optional, for Story 9)
                - slope_min_pct_15m
                - accel_5m_min_pct
                - accel_15m_min_pct
            cooldown_remaining_sec: Remaining cooldown time (if applicable)
            mode: "shadow" or "live"
            correlation_id: Optional correlation ID for intent tracking
        """
        self._emit("entry_guard_evaluation", {
            "connector": connector,
            "symbol": symbol,
            "regime": regime,
            "decision": decision,
            "reject_reason": reject_reason,
            "metrics": metrics or {},
            "thresholds": thresholds or {},
            "cooldown_remaining_sec": cooldown_remaining_sec,
            "mode": mode,
            "correlation_id": correlation_id
        })


def compute_config_hash(config_dict: Dict, logger: Optional[logging.Logger] = None) -> str:
    """
    Compute stable hash of config for run tracking.

    Only includes relevant keys (excludes secrets/timestamps).

    Args:
        config_dict: Config dictionary (typically config.__dict__)
        logger: Optional logger to log hash to

    Returns:
        12-character hex hash string
    """
    relevant_keys = [
        "max_simultaneous_coins", "total_amount_quote",
        "trend_min_change_pct", "min_grid_spread_pct",
        "smart_entry_filter", "use_multi_timeframe_buy",
        "risk_limits", "observability"
    ]

    relevant_config = {k: config_dict.get(k) for k in relevant_keys if k in config_dict}
    config_str = json.dumps(relevant_config, sort_keys=True, default=str)
    config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:12]

    # Log to normal logger for visibility
    if logger:
        logger.info(f"📋 Config hash: {config_hash}")
        logger.debug(f"   Hashed keys: {list(relevant_config.keys())}")

    return config_hash

```

## Attachment: monitoring/collector.py (446 lines)

```python
"""
Data Collector Service

Background service that collects bot status, parses logs, and stores data in database.
Runs every N seconds (default: 10s).
"""

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from .config import MonitoringConfig
from .database import MonitoringDatabase
from .telegram_bot import TelegramBot


class DataCollector:
    """Collects bot data and stores in database"""

    def __init__(self, db: MonitoringDatabase, log_file: str, telegram_bot: Optional[TelegramBot] = None):
        """
        Initialize data collector

        Args:
            db: MonitoringDatabase instance
            log_file: Path to bot log file
            telegram_bot: Optional TelegramBot instance for alerts
        """
        self.db = db
        self.log_file = Path(log_file)
        self.logger = logging.getLogger(__name__)
        self.telegram_bot = telegram_bot

        # Start from END of file to avoid processing old events
        # Only monitor NEW events from this point forward
        self.last_position = 0
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(0, 2)  # Seek to end of file
                    self.last_position = f.tell()
                self.logger.info(f"📍 Starting from end of log file (position: {self.last_position})")
            except Exception as e:
                self.logger.warning(f"Could not seek to end of log file: {e}")

        # Event patterns to detect
        self.event_patterns = {
            "stop_loss": re.compile(r"STOP LOSS TRIGGERED|stop-loss triggered", re.IGNORECASE),
            "circuit_breaker": re.compile(r"CIRCUIT BREAKER ACTIVE|circuit breaker", re.IGNORECASE),
            "error": re.compile(r"ERROR|CRITICAL|Exception|Traceback", re.IGNORECASE),
            "trend_switch": re.compile(r"SWITCH APPROVED|Selected coin|🔍 Selected coin", re.IGNORECASE),
            "executor_created": re.compile(r"STARTING new grid|Creating grid|CREATING GRID", re.IGNORECASE),
            "executor_stopped": re.compile(r"Stopping executor|executor stopped|STOPPING executor", re.IGNORECASE),
            # Note: API rate limit warnings are normal - don't alert on them
            "api_error": re.compile(r"API.*error|API.*failed", re.IGNORECASE),
        }

        # Events that should NOT trigger alerts (too noisy)
        self.noisy_events = {
            "api_rate_limit",  # Normal rate limit warnings
        }

    def read_new_log_lines(self) -> list:
        """Read new lines from log file since last check"""
        if not self.log_file.exists():
            return []

        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                # Seek to last position
                f.seek(self.last_position)
                lines = f.readlines()
                # Update position
                self.last_position = f.tell()
                return lines
        except Exception as e:
            self.logger.error(f"Error reading log file: {e}")
            return []

    def parse_log_line(self, line: str) -> Optional[Dict[str, Any]]:
        """
        Parse a log line and detect events

        Returns:
            Dict with event_type, coin, message if event detected, else None
        """
        # Extract timestamp if present
        timestamp_match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)

        # Check for event patterns
        for event_type, pattern in self.event_patterns.items():
            if pattern.search(line):
                # Try to extract coin symbol - FIXED: Better pattern matching
                coin = None

                # First try to find coin in "Selected coin:" pattern
                selected_match = re.search(r'Selected coin:\s*([A-Z0-9]+-EUR)', line, re.IGNORECASE)
                if selected_match:
                    coin = selected_match.group(1)
                else:
                    # Fallback: look for any coin symbol pattern
                    coin_match = re.search(r'([A-Z0-9]+-EUR)', line)
                    coin = coin_match.group(1) if coin_match else None

                # Special handling for "Selected coin" messages
                if event_type == "trend_switch" and "Selected coin" in line:
                    # Extract the coin name or "None" message
                    selected_match = re.search(r'Selected coin:\s*(.+?)(?:\s|$)', line)
                    if selected_match:
                        coin_info = selected_match.group(1).strip()
                        # If coin_info contains a coin symbol, extract it
                        coin_symbol_match = re.search(r'([A-Z0-9]+-EUR)', coin_info)
                        if coin_symbol_match:
                            coin = coin_symbol_match.group(1)
                        # Create a cleaner message
                        message = f"Selected coin: {coin_info}"
                    else:
                        message = line.strip()
                else:
                    # For other events, use full line but clean it up
                    message = line.strip()
                    # Remove excessive whitespace
                    message = re.sub(r'\s+', ' ', message)
                    # Limit message length to prevent database issues (but keep more than dashboard shows)
                    if len(message) > 500:
                        message = message[:497] + "..."

                return {
                    "event_type": event_type,
                    "coin": coin,
                    "message": message,
                    "timestamp": timestamp_match.group(1) if timestamp_match else None
                }

        return None

    def get_bot_status_from_logs(self) -> Dict[str, Any]:
        """
        Extract bot status from recent log lines

        Returns:
            Dict with status information
        """
        status = {
            "active_coin": None,
            "pnl": 0.0,
            "exposure": 0.0,
            "mode": "running",
            "grid_level": None,
            "connection_status": "ok"
        }

        # Read last 500 lines to find status (increased from 100 for better coverage)
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()[-500:]

                    # Look for active coin - FIXED: Search for "Selected coin:" pattern
                    for line in reversed(lines):
                        # Pattern 1: "📊 MONITORING: Active Coin: FET-EUR" (new explicit format)
                        monitoring_coin_match = re.search(r'MONITORING:.*?Active Coin:\s*([A-Z0-9]+-EUR)', line)
                        if monitoring_coin_match:
                            coin = monitoring_coin_match.group(1)
                            if coin.upper() != "NONE":
                                status["active_coin"] = coin
                                break

                        # Pattern 2: "🔍 Selected coin: FET-EUR" or "Selected coin: FET-EUR"
                        selected_match = re.search(r'Selected coin:\s*([A-Z0-9]+-EUR)', line, re.IGNORECASE)
                        if selected_match:
                            coin = selected_match.group(1)
                            # Skip if it says "None"
                            if coin.upper() != "NONE":
                                status["active_coin"] = coin
                                break

                        # Pattern 3: "active_coin.*?([A-Z0-9]+-EUR)" (fallback)
                        coin_match = re.search(r'active_coin.*?([A-Z0-9]+-EUR)', line)
                        if coin_match:
                            status["active_coin"] = coin_match.group(1)
                            break

                        # Pattern 4: "Active Coin: FET-EUR" from status output
                        active_coin_match = re.search(r'Active Coin:\s*([A-Z0-9]+-EUR)', line)
                        if active_coin_match:
                            coin = active_coin_match.group(1)
                            if coin.upper() != "NONE":
                                status["active_coin"] = coin
                                break

                    # Look for P&L - FIXED: Search for P&L patterns in logs
                    for line in reversed(lines):
                        # Pattern 1: "📊 MONITORING: Total P&L: €+1.23" (new explicit format)
                        monitoring_pnl_match = re.search(r'MONITORING:.*?Total P&L:\s*€([+-]?[\d.]+)', line)
                        if monitoring_pnl_match:
                            try:
                                status["pnl"] = float(monitoring_pnl_match.group(1))
                                break
                            except ValueError:
                                pass

                        # Pattern 2: "📊 MONITORING: Executor P&L: €+1.23" (executor P&L)
                        executor_pnl_match = re.search(r'MONITORING:.*?Executor P&L:\s*€([+-]?[\d.]+)', line)
                        if executor_pnl_match:
                            try:
                                status["pnl"] = float(executor_pnl_match.group(1))
                                break
                            except ValueError:
                                pass

                        # Pattern 3: "💰 P&L: €+1.23 (+2.45%)" or "📉 P&L: €-1.23 (-2.45%)"
                        pnl_match = re.search(r'P&L:\s*€([+-]?[\d.]+)', line)
                        if pnl_match:
                            try:
                                status["pnl"] = float(pnl_match.group(1))
                                break
                            except ValueError:
                                pass

                        # Pattern 4: "Total P&L: €+1.23"
                        total_pnl_match = re.search(r'Total P&L:\s*€([+-]?[\d.]+)', line)
                        if total_pnl_match:
                            try:
                                status["pnl"] = float(total_pnl_match.group(1))
                                break
                            except ValueError:
                                pass

                        # Pattern 5: "net_pnl_quote.*?([+-]?[\d.]+)"
                        net_pnl_match = re.search(r'net_pnl_quote[:\s]+([+-]?[\d.]+)', line)
                        if net_pnl_match:
                            try:
                                status["pnl"] = float(net_pnl_match.group(1))
                                break
                            except ValueError:
                                pass

                    # Look for exposure - FIXED: Better pattern matching
                    for line in reversed(lines):
                        # Pattern 1: "Total Exposure: €50.00"
                        exposure_match = re.search(r'Total Exposure:\s*€([\d.]+)', line)
                        if exposure_match:
                            try:
                                status["exposure"] = float(exposure_match.group(1))
                                break
                            except ValueError:
                                pass

                        # Pattern 2: "exposure.*?€([\d.]+)"
                        exposure_match2 = re.search(r'exposure.*?€([\d.]+)', line, re.IGNORECASE)
                        if exposure_match2:
                            try:
                                status["exposure"] = float(exposure_match2.group(1))
                                break
                            except ValueError:
                                pass

                        # Pattern 3: "Reset exposure: FET-EUR (was €50.00)"
                        reset_exposure_match = re.search(r'Reset exposure.*?€([\d.]+)', line)
                        if reset_exposure_match:
                            try:
                                status["exposure"] = float(reset_exposure_match.group(1))
                                break
                            except ValueError:
                                pass

                    # Look for mode (paused, error, etc)
                    for line in reversed(lines):
                        if "CIRCUIT BREAKER" in line or "paused" in line.lower():
                            status["mode"] = "paused"
                            break
                        if "ERROR" in line or "CRITICAL" in line:
                            status["mode"] = "error_safe_mode"
                            break
            except Exception as e:
                self.logger.error(f"Error reading status from logs: {e}")

        return status

    def measure_latency(self) -> float:
        """
        Measure exchange latency (Kraken ping)

        Returns:
            Latency in milliseconds
        """
        try:
            import time
            start = time.time()
            # Simple HTTP request to Kraken public endpoint
            response = requests.get("https://api.kraken.com/0/public/Time", timeout=5)
            elapsed = (time.time() - start) * 1000  # Convert to ms

            if response.status_code == 200:
                return elapsed
            else:
                return 9999.0  # Error indicator
        except Exception as e:
            self.logger.debug(f"Latency measurement failed: {e}")
            return 9999.0

    def collect_and_store(self):
        """Main collection cycle: read logs, detect events, store status"""
        # Read new log lines
        new_lines = self.read_new_log_lines()

        # Parse and store events
        for line in new_lines:
            # Skip API rate limit warnings completely (too noisy)
            if "API rate limit" in line or "rate limit" in line.lower():
                continue

            event = self.parse_log_line(line)
            if event:
                # Skip storing noisy events
                if event["event_type"] in self.noisy_events:
                    continue

                self.db.add_event(
                    event_type=event["event_type"],
                    message=event["message"],
                    coin=event.get("coin"),
                    data={"timestamp": event.get("timestamp")}
                )

                # Log important events
                if event["event_type"] in ["stop_loss", "error", "circuit_breaker"]:
                    self.logger.warning(f"⚠️  Event detected: {event['event_type']} - {event['message'][:100]}")

                # Send Telegram alert for critical events only
                if self.telegram_bot:
                    coin = event.get("coin")
                    event_type = event["event_type"]

                    # Only alert for:
                    # 1. Critical events (always alert, even without coin)
                    # 2. Trend switches (only if coin is valid)
                    if event_type in ["stop_loss", "circuit_breaker", "error"]:
                        # Critical events - always alert
                        self.telegram_bot.check_and_alert(
                            event_type=event_type,
                            message=event["message"][:200],
                            coin=coin
                        )
                    elif event_type == "trend_switch" and coin:
                        # Trend switches - only if coin is valid
                        self.telegram_bot.check_and_alert(
                            event_type=event_type,
                            message=event["message"][:200],
                            coin=coin
                        )

        # Get and store bot status
        status = self.get_bot_status_from_logs()
        latency = self.measure_latency()

        self.db.add_status(
            active_coin=status["active_coin"],
            pnl=status["pnl"],
            exposure=status["exposure"],
            mode=status["mode"],
            grid_level=status["grid_level"],
            heartbeat_latency=latency,
            connection_status="ok" if latency < 5000 else "reconnecting"
        )

    def run_continuous(self, interval: int = 10):
        """
        Run collector continuously

        Args:
            interval: Seconds between collection cycles
        """
        self.logger.info(f"🚀 Starting data collector (interval: {interval}s)")
        self.logger.info(f"📁 Monitoring log file: {self.log_file}")

        try:
            while True:
                try:
                    self.collect_and_store()
                except Exception as e:
                    self.logger.error(f"Error in collection cycle: {e}")

                time.sleep(interval)
        except KeyboardInterrupt:
            self.logger.info("🛑 Data collector stopped by user")


def main():
    """Main entry point for collector"""
    import argparse

    parser = argparse.ArgumentParser(description="Bot Monitoring Data Collector")
    parser.add_argument(
        "--interval",
        type=int,
        default=MonitoringConfig.COLLECTOR_INTERVAL,
        help="Collection interval in seconds (default: 10)"
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=MonitoringConfig.LOG_FILE,
        help="Path to bot log file"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database (default: auto)"
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Initialize database and collector
    db = MonitoringDatabase(db_path=args.db_path)

    # Initialize Telegram bot if configured
    telegram_bot = None
    if MonitoringConfig.TELEGRAM_BOT_TOKEN and MonitoringConfig.TELEGRAM_CHAT_ID:
        telegram_bot = TelegramBot(
            bot_token=MonitoringConfig.TELEGRAM_BOT_TOKEN,
            chat_id=MonitoringConfig.TELEGRAM_CHAT_ID,
            db=db
        )
        logging.info("✅ Telegram bot initialized")

    collector = DataCollector(db=db, log_file=args.log_file, telegram_bot=telegram_bot)

    # Run collector
    collector.run_continuous(interval=args.interval)


if __name__ == "__main__":
    main()

```

## Attachment: monitoring/risk_monitor.py (546 lines)

```python
"""
Background risk monitor that feeds ArbitrageRiskScanner with live market data and
pushes Telegram notifications whenever the trade status changes.

This module intentionally lives outside the main bot loop so it can be executed as
a stand-alone process:

    python -m multi_coin_grid_pro.monitoring.risk_monitor \
        --config /home/mo/repos/hummingbot/multi_coin_grid_pro/config/risk_monitor.yaml
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Dict, Iterable, List, Optional

import ccxt
import yaml

from multi_coin_grid_pro.core.risk_scanner import ArbitrageRiskScanner
from multi_coin_grid_pro.monitoring.telegram_notifier import TelegramNotifier

LOGGER = logging.getLogger("risk_monitor")
DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "risk_monitor.yaml"
)


@dataclass
class MarketMetrics:
    returns_1m: List[float]
    avg_spread_bps: float
    latency_ms_by_exchange: Dict[str, float]
    total_volume_24h_usd: float
    status_by_exchange: Dict[str, str]
    symbols_count_by_exchange: Dict[str, int]


def load_config(path: Path) -> Dict:
    if not path.exists():
        raise FileNotFoundError(f"Risk monitor config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def build_exchange_clients(
    exchanges_cfg: Iterable,
) -> Dict[str, ccxt.Exchange]:
    """
    Build ccxt exchange clients from config.

    Config items can be:
      - plain strings (exchange ids, e.g. "kraken")
      - dictionaries:
            id: bitget           # ccxt id
            name: bitget_spot    # internal label (used in metrics/notifications)
            params: {...}        # passed to ccxt constructor

    When name is omitted, id is used as the label.
    """
    clients: Dict[str, ccxt.Exchange] = {}
    for entry in exchanges_cfg:
        if isinstance(entry, str):
            exchange_id = entry
            client_name = exchange_id
            params = {}
        elif isinstance(entry, dict):
            exchange_id = entry.get("id") or entry.get("name")
            client_name = entry.get("name") or exchange_id
            params = entry.get("params", {})
        else:
            raise ValueError(f"Unsupported exchange config entry: {entry}")

        if not exchange_id:
            raise ValueError("Exchange entry requires an 'id' or 'name'")

        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"ccxt has no exchange id '{exchange_id}'")

        params = {"enableRateLimit": True, **params}
        exchange_cls = getattr(ccxt, exchange_id)
        client: ccxt.Exchange = exchange_cls(params)
        client.load_markets()
        clients[client_name] = client
        LOGGER.info(
            "Connected ccxt exchange '%s' (id=%s, %d markets)",
            client_name,
            exchange_id,
            len(client.markets),
        )
    return clients


def resolve_symbol(exchange: ccxt.Exchange, pair: str) -> Optional[str]:
    """
    Convert configuration pair notation (BTC-EUR / BTC/EUR) into a ccxt symbol
    that exists on the exchange. Includes special-casing for Kraken's XBT ticker.

    This is mainly used when you explicitly configure trading_pairs in YAML.
    For the dynamic whole-market scan we directly use the exchange.markets symbols.
    """
    candidates = [
        pair.replace("-", "/"),
        pair.replace("-", "/").replace("BTC", "XBT"),
    ]

    for candidate in candidates:
        if candidate in exchange.markets:
            return candidate
    return None


def compute_returns_from_ohlcv(ohlcv: List[List[float]]) -> List[float]:
    returns: List[float] = []
    if len(ohlcv) < 2:
        return returns
    closes = [candle[4] for candle in ohlcv if candle and len(candle) >= 5]
    for prev, curr in zip(closes, closes[1:]):
        if prev:
            returns.append((curr - prev) / prev)
    return returns


def build_trading_universe(
    exchanges: Dict[str, ccxt.Exchange],
    monitor_cfg: Dict,
) -> Dict[str, List[str]]:
    """
    Determine which symbols to monitor per exchange.

    If risk_monitor.trading_pairs is set in YAML, we:
      - map those pairs to real ccxt symbols per exchange (resolve_symbol)
    Else:
      - dynamic universe: scan the entire market for each exchange
        and filter on:
            - quote currencies (risk_monitor.quotes)
            - include_futures flag
            - max_symbols_per_exchange cap
    """
    trading_pairs_cfg = monitor_cfg.get("trading_pairs") or []
    quotes = monitor_cfg.get("quotes") or ["EUR", "USD", "USDT"]
    include_futures = bool(monitor_cfg.get("include_futures", True))
    max_symbols_per_exchange = int(monitor_cfg.get("max_symbols_per_exchange", 100))

    trading_pairs_by_exchange: Dict[str, List[str]] = {}

    if trading_pairs_cfg:
        # Use manually configured universe; resolve per exchange.
        LOGGER.info("Using manually configured trading_pairs from YAML")
        for name, client in exchanges.items():
            symbols: List[str] = []
            for pair in trading_pairs_cfg:
                symbol = resolve_symbol(client, pair)
                if symbol is not None:
                    symbols.append(symbol)
                else:
                    LOGGER.debug("Pair %s not available on %s", pair, name)
            # Deduplicate and cap
            symbols = sorted(set(symbols))
            if max_symbols_per_exchange and len(symbols) > max_symbols_per_exchange:
                LOGGER.info(
                    "Capping %s symbols for %s from %d to %d",
                    len(symbols),
                    name,
                    len(symbols),
                    max_symbols_per_exchange,
                )
                symbols = symbols[:max_symbols_per_exchange]
            trading_pairs_by_exchange[name] = symbols
    else:
        # Dynamic whole-market universe (filtered)
        LOGGER.info("Building dynamic trading universe from exchange markets")
        for name, client in exchanges.items():
            symbols: List[str] = []

            for market in client.markets.values():
                if not market.get("active", True):
                    continue

                quote = market.get("quote")
                if quote not in quotes:
                    continue

                mtype = market.get("type")
                # Fallback for some exchanges
                if not mtype:
                    if market.get("swap"):
                        mtype = "swap"
                    else:
                        mtype = "spot"

                if mtype == "spot":
                    symbols.append(market["symbol"])
                elif include_futures and mtype in ("swap", "future", "perpetual"):
                    symbols.append(market["symbol"])

            symbols = sorted(set(symbols))
            original_count = len(symbols)
            if max_symbols_per_exchange and original_count > max_symbols_per_exchange:
                LOGGER.info(
                    "Capping symbols for %s from %d to %d",
                    name,
                    original_count,
                    max_symbols_per_exchange,
                )
                symbols = symbols[:max_symbols_per_exchange]

            trading_pairs_by_exchange[name] = symbols
            LOGGER.info(
                "Exchange %s – using %d symbols (filtered by quotes=%s, include_futures=%s)",
                name,
                len(symbols),
                ",".join(quotes),
                include_futures,
            )

    return trading_pairs_by_exchange


def collect_market_metrics(
    exchanges: Dict[str, ccxt.Exchange],
    trading_pairs_by_exchange: Dict[str, List[str]],
    ohlcv_limit: int,
) -> MarketMetrics:
    returns_1m: List[float] = []
    spreads_bps: List[float] = []
    latency_ms: Dict[str, float] = {}
    total_volume_usd = 0.0
    exchange_status: Dict[str, str] = {}
    symbols_count_by_exchange: Dict[str, int] = {}

    for name, client in exchanges.items():
        pairs = trading_pairs_by_exchange.get(name, [])
        symbols_count_by_exchange[name] = len(pairs)

        if not pairs:
            LOGGER.warning("No trading pairs configured for exchange %s", name)
            latency_ms[name] = 9999.0
            exchange_status[name] = "down"
            continue

        per_exchange_spreads: List[float] = []
        per_exchange_latency: List[float] = []
        per_exchange_returns: List[float] = []
        per_exchange_volume = 0.0
        status = "ok"

        for symbol in pairs:
            # Spread + latency sample
            try:
                start = time.time()
                ticker = client.fetch_ticker(symbol)
                per_exchange_latency.append((time.time() - start) * 1000)

                bid = ticker.get("bid")
                ask = ticker.get("ask")
                if bid and ask and bid > 0:
                    mid = (bid + ask) / 2
                    spread_bps = ((ask - bid) / mid) * 10_000
                    per_exchange_spreads.append(spread_bps)

                base_volume = ticker.get("baseVolume") or 0
                last_price = ticker.get("last") or ticker.get("close") or 0
                if base_volume and last_price:
                    # Rough USD approximation (assume EUR≈USD)
                    per_exchange_volume += float(base_volume) * float(last_price)
            except Exception as exc:
                status = "degraded"
                LOGGER.warning(
                    "Failed to fetch ticker for %s on %s: %s", symbol, name, exc
                )

            # Returns sample (1m candles)
            try:
                ohlcv = client.fetch_ohlcv(symbol, timeframe="1m", limit=ohlcv_limit)
                per_exchange_returns.extend(compute_returns_from_ohlcv(ohlcv))
            except Exception as exc:
                status = "degraded"
                LOGGER.debug(
                    "Failed to fetch OHLCV for %s on %s: %s", symbol, name, exc
                )

        if not per_exchange_latency:
            latency_ms[name] = 9999.0
            if status == "ok":
                status = "down"
        else:
            latency_ms[name] = sum(per_exchange_latency) / len(per_exchange_latency)

        if per_exchange_returns:
            returns_1m.extend(per_exchange_returns)
        if per_exchange_spreads:
            spreads_bps.extend(per_exchange_spreads)

        total_volume_usd += per_exchange_volume
        exchange_status[name] = status

    avg_spread = sum(spreads_bps) / len(spreads_bps) if spreads_bps else 0.0

    if not latency_ms:
        latency_ms = {"kraken": 9999.0}
    if not exchange_status:
        exchange_status = {"kraken": "down"}
    if not symbols_count_by_exchange:
        symbols_count_by_exchange = {name: 0 for name in exchanges.keys()}

    return MarketMetrics(
        returns_1m=returns_1m or [0.0],
        avg_spread_bps=avg_spread,
        latency_ms_by_exchange=latency_ms,
        total_volume_24h_usd=total_volume_usd,
        status_by_exchange=exchange_status,
        symbols_count_by_exchange=symbols_count_by_exchange,
    )


def build_telegram_notifier(config: Dict) -> Optional[TelegramNotifier]:
    telegram_cfg = config.get("telegram", {})
    enabled = telegram_cfg.get("enabled", True)
    if not enabled:
        return None

    bot_token = telegram_cfg.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = telegram_cfg.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID")

    if not (bot_token and chat_id):
        LOGGER.warning("Telegram notifier disabled (missing bot token or chat id)")
        return None

    return TelegramNotifier(
        bot_token=bot_token,
        chat_id=chat_id,
        notify_on_status_change=telegram_cfg.get("notify_on_status_change", True),
        notify_on_do_not_trade=telegram_cfg.get("notify_on_do_not_trade", True),
    )


def build_detailed_explanation(result, metrics: MarketMetrics) -> str:
    """
    Build a human-readable explanation string that combines:
      - global risk score
      - volatility summary (min/max/avg |return|)
      - liquidity & spreads
      - per-exchange status / latency / universe size
      - simple pump/dump hints
      - trade guidance based on status
    """

    returns = metrics.returns_1m or [0.0]
    max_ret = max(returns)
    min_ret = min(returns)
    avg_abs = mean([abs(r) for r in returns]) if returns else 0.0

    lines: List[str] = []

    lines.append(f"📊 Global Risk Score: {result.score:.1f} ({result.status.value})")
    lines.append("")
    lines.append("📈 Volatility snapshot (1m returns across sampled markets)")
    lines.append(f"• Samples: {len(returns)}")
    lines.append(f"• Max 1m move: {max_ret * 100:.2f}%")
    lines.append(f"• Min 1m move: {min_ret * 100:.2f}%")
    lines.append(f"• Avg |1m return|: {avg_abs * 100:.2f}%")
    lines.append("")
    lines.append("💧 Liquidity & spreads")
    lines.append(f"• Approx. 24h volume: ${metrics.total_volume_24h_usd:,.0f}")
    lines.append(f"• Avg spread: {metrics.avg_spread_bps:.2f} bps")
    lines.append("")
    lines.append("🏦 Exchange status")

    for ex, st in metrics.status_by_exchange.items():
        lat = metrics.latency_ms_by_exchange.get(ex, 0.0)
        n_pairs = metrics.symbols_count_by_exchange.get(ex, 0)
        lines.append(
            f"• {ex}: {st}, latency ~{lat:.0f} ms, markets sampled: {n_pairs}"
        )

    lines.append("")

    # Guidance based on status
    status_str = str(result.status.value).lower()
    if "do_not_trade" in status_str or status_str == "do_not_trade":
        lines.append(
            "⚠️ Marktomstandigheden zijn vijandig. "
            "Overweeg om geen nieuwe posities te openen en risico's strakker te managen."
        )
    elif "caution" in status_str:
        lines.append(
            "⚠️ Voorzichtigheid geboden. Condities zijn schokkerig; "
            "kleinere posities en ruimere stops zijn verstandiger."
        )
    else:
        lines.append(
            "✅ Condities lijken acceptabel voor trading, binnen je normale risk rules."
        )

    # Simple pump/dump hints
    dump_threshold = -0.03  # -3% in 1m
    pump_threshold = 0.03   # +3% in 1m
    has_dumps = any(r < dump_threshold for r in returns)
    has_pumps = any(r > pump_threshold for r in returns)

    if has_dumps:
        lines.append(
            "• Er zijn scherpe neerwaartse bewegingen gedetecteerd (≥ 3% in 1 minuut) "
            "in (een deel van) de markt."
        )
    if has_pumps:
        lines.append(
            "• Er zijn scherpe opwaartse bewegingen gedetecteerd (≥ 3% in 1 minuut)."
        )

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Arbitrage risk monitor daemon")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to risk_monitor.yaml",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Override evaluation interval in seconds",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single evaluation and exit",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console log level",
    )
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )


def main():
    args = parse_args()
    configure_logging(args.log_level)

    config = load_config(args.config)
    monitor_cfg = config.get("risk_monitor", {})
    interval = args.interval or int(monitor_cfg.get("interval_seconds", 120))
    ohlcv_limit = int(monitor_cfg.get("ohlcv_limit", 30))
    exchanges_cfg = monitor_cfg.get("exchanges") or ["kraken"]

    try:
        exchanges = build_exchange_clients(exchanges_cfg)
    except Exception as exc:
        LOGGER.error("Failed to initialize exchanges: %s", exc)
        sys.exit(1)

    # Determine trading universe per exchange (whole-market scan or from config)
    trading_pairs_by_exchange = build_trading_universe(exchanges, monitor_cfg)

    risk_cfg = config.get("risk", {})
    scanner = ArbitrageRiskScanner(
        weights=risk_cfg.get("weights"),
        trade_min_score=risk_cfg.get("trade_min_score", 70),
        caution_min_score=risk_cfg.get("caution_min_score", 40),
    )

    telegram_notifier = build_telegram_notifier(config)
    LOGGER.info(
        "Risk monitor started with %s exchanges (interval=%ss)",
        len(exchanges),
        interval,
    )

    try:
        while True:
            try:
                metrics = collect_market_metrics(
                    exchanges, trading_pairs_by_exchange, ohlcv_limit
                )

                result = scanner.evaluate(
                    returns_1m=metrics.returns_1m,
                    avg_spread_bps=metrics.avg_spread_bps,
                    latency_ms_by_exchange=metrics.latency_ms_by_exchange,
                    total_volume_24h_usd=metrics.total_volume_24h_usd,
                    status_by_exchange=metrics.status_by_exchange,
                )

                # Enrich explanation with global market summary (for logs + Telegram)
                result.explanation = build_detailed_explanation(result, metrics)

                LOGGER.info(
                    "Risk score %.1f (%s) | spreads %.1fbps | volume $%.0f | latency %s",
                    result.score,
                    result.status.value,
                    metrics.avg_spread_bps,
                    metrics.total_volume_24h_usd,
                    ", ".join(
                        f"{ex}:{latency:.0f}ms"
                        for ex, latency in metrics.latency_ms_by_exchange.items()
                    ),
                )

                LOGGER.debug("Explanation:\n%s", result.explanation)

                if telegram_notifier:
                    # Preview the message text for logging/diagnostics
                    try:
                        preview = None
                        if hasattr(telegram_notifier, "format_risk_message"):
                            preview = telegram_notifier.format_risk_message(result)
                        if preview:
                            LOGGER.info("Telegram preview: %s", preview.replace("\n", " | "))
                        telegram_notifier.handle_risk_result(result)
                    except Exception as exc:
                        LOGGER.exception("Telegram notifier failed: %s", exc)
            except Exception as exc:
                LOGGER.error("Risk evaluation failed: %s", exc, exc_info=True)

            if args.once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        LOGGER.info("Risk monitor interrupted by user")


if __name__ == "__main__":
    main()

```

## Attachment: monitoring/trade_analyzer.py (666 lines)

```python
"""
Trade Analyzer - Comprehensive bot analysis for Telegram reporting

Reads trade data directly from SQLite database for accurate real-time data.
Also parses log files for status information (trends, blocks, errors).
"""

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import MonitoringConfig


@dataclass
class Trade:
    """Represents a single trade (buy/sell pair)"""
    coin: str
    buy_price: Decimal
    buy_amount: Decimal
    buy_time: datetime
    sell_price: Optional[Decimal] = None
    sell_amount: Optional[Decimal] = None
    sell_time: Optional[datetime] = None
    buy_fee: Decimal = Decimal("0")
    sell_fee: Decimal = Decimal("0")

    @property
    def is_closed(self) -> bool:
        return self.sell_price is not None

    @property
    def buy_value(self) -> Decimal:
        return self.buy_price * self.buy_amount

    @property
    def sell_value(self) -> Decimal:
        if self.sell_price and self.sell_amount:
            return self.sell_price * self.sell_amount
        return Decimal("0")

    @property
    def profit(self) -> Decimal:
        """Net profit after fees"""
        if not self.is_closed:
            return Decimal("0")
        return self.sell_value - self.buy_value - self.buy_fee - self.sell_fee

    @property
    def profit_pct(self) -> float:
        """Profit as percentage"""
        if not self.is_closed or self.buy_value == 0:
            return 0.0
        return float((self.profit / self.buy_value) * 100)


@dataclass
class BotStatus:
    """Current bot status"""
    is_running: bool = False
    active_coin: Optional[str] = None
    current_position: Optional[Decimal] = None
    entry_price: Optional[Decimal] = None
    target_price: Optional[Decimal] = None
    is_blocked: bool = False
    block_reason: Optional[str] = None
    best_trend_coin: Optional[str] = None
    best_trend_pct: float = 0.0
    top_trends: List[Tuple[str, float]] = field(default_factory=list)
    last_update: Optional[datetime] = None


@dataclass
class AnalysisReport:
    """Complete analysis report"""
    trades: List[Trade]
    status: BotStatus
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    win_count: int = 0
    loss_count: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class TradeAnalyzer:
    """
    Analyzes bot data from SQLite database and log files.

    Reads trades directly from database for accuracy.
    Uses log files for status information (trends, blocks, etc.)
    """

    # Database path - prices and amounts stored as integers (multiply by divisor)
    DB_PATH = "/home/mo/repos/hummingbot/data/multi_coin_grid_v2.sqlite"
    PRICE_DIVISOR = Decimal("1000000")  # Prices stored as micro-EUR

    def __init__(self, log_path: Optional[str] = None, db_path: Optional[str] = None):
        """
        Initialize analyzer

        Args:
            log_path: Path to log file (default: from config)
            db_path: Path to SQLite database (default: standard path)
        """
        self.log_path = Path(log_path or MonitoringConfig.LOG_FILE)
        self.db_path = db_path or self.DB_PATH
        self.logger = logging.getLogger(__name__)

        # Regex patterns for parsing log files (status info only)
        self.patterns = {
            'top_trends': re.compile(
                r'(\d+)\. (\w+-EUR): ([+-]?[\d.]+)%.*24h: ([+-]?[\d.]+)%'
            ),
            'best_coin': re.compile(
                r'BEST: (\w+-EUR) with ([+-]?[\d.]+)% trend'
            ),
            'active_coin': re.compile(
                r'Active Coin: (\w+-EUR)'
            ),
            'active_coin_alt': re.compile(
                r'🎯 Active: (\w+-EUR)'
            ),
            'risk_blocked': re.compile(
                r'Risk manager blocked.*\(([^)]+)\)'
            ),
            'drawdown_blocked': re.compile(
                r'DRAWDOWN LIMIT|Trading paused'
            ),
            'error': re.compile(
                r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*ERROR.*-\s*(.+)'
            ),
            'warning': re.compile(
                r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*CRITICAL.*-\s*(.+)'
            ),
        }

    def analyze(self, hours: int = 24) -> AnalysisReport:
        """
        Perform comprehensive analysis

        Reads trades from SQLite database (accurate, real-time data).
        Reads status from log files (trends, blocks, etc.)

        Args:
            hours: Number of hours to analyze (default: 24)

        Returns:
            AnalysisReport with all findings
        """
        # Read trades from database (primary source)
        trades = self._read_trades_from_db(hours)

        # Read status from log file
        status = BotStatus()
        errors = []
        warnings = []

        if self.log_path.exists():
            cutoff_time = datetime.now() - timedelta(hours=hours)
            lines = self._read_recent_lines(cutoff_time)
            status = self._parse_status(lines)
            errors, warnings = self._parse_issues(lines)

        # Calculate statistics
        report = self._build_report(trades, status, errors, warnings)

        return report

    def _read_trades_from_db(self, hours: int = 24) -> List[Trade]:
        """
        Read trades directly from SQLite database

        This is more accurate than parsing logs.

        Args:
            hours: Number of hours to look back

        Returns:
            List of Trade objects
        """
        trades = []

        if not Path(self.db_path).exists():
            self.logger.warning(f"Database not found: {self.db_path}")
            return trades

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get trades from last N hours
            cutoff_ms = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)

            cursor.execute('''
                SELECT symbol, trade_type, price, amount, trade_fee_in_quote, timestamp
                FROM TradeFill
                WHERE timestamp > ?
                ORDER BY timestamp ASC
            ''', (cutoff_ms,))

            rows = cursor.fetchall()
            conn.close()

            # Use FIFO matching for grid trading
            open_buys: Dict[str, List[Tuple]] = {}  # coin -> [(amount, price, fee, timestamp)]

            for symbol, trade_type, price, amount, fee, ts in rows:
                # Convert from database format
                ts_dt = datetime.fromtimestamp(ts / 1000)
                price_dec = Decimal(str(price)) / self.PRICE_DIVISOR
                amount_dec = Decimal(str(amount)) / self.PRICE_DIVISOR
                fee_dec = Decimal(str(fee)) / self.PRICE_DIVISOR if fee else Decimal("0")

                coin = symbol.replace("-EUR", "")

                if trade_type == 'BUY':
                    # Add to FIFO queue
                    if coin not in open_buys:
                        open_buys[coin] = []
                    open_buys[coin].append((amount_dec, price_dec, fee_dec, ts_dt, symbol))

                elif trade_type == 'SELL':
                    # Match with oldest buys (FIFO)
                    if coin not in open_buys or not open_buys[coin]:
                        self.logger.debug(f"Sell without matching buy for {symbol}")
                        continue

                    remaining_sell = amount_dec
                    remaining_fee = fee_dec

                    while remaining_sell > Decimal("0.0001") and open_buys[coin]:
                        buy_amt, buy_price, buy_fee, buy_time, buy_symbol = open_buys[coin][0]
                        match_amt = min(buy_amt, remaining_sell)

                        # Proportional fees
                        buy_fee_portion = (match_amt / buy_amt) * buy_fee
                        sell_fee_portion = (match_amt / amount_dec) * remaining_fee

                        # Create matched trade
                        matched_trade = Trade(
                            coin=symbol,
                            buy_price=buy_price,
                            buy_amount=match_amt,
                            buy_time=buy_time,
                            buy_fee=buy_fee_portion,
                            sell_price=price_dec,
                            sell_amount=match_amt,
                            sell_time=ts_dt,
                            sell_fee=sell_fee_portion
                        )
                        trades.append(matched_trade)

                        # Update remaining
                        remaining_sell -= match_amt
                        remaining_fee -= sell_fee_portion

                        # Update or remove buy
                        new_buy_amt = buy_amt - match_amt
                        if new_buy_amt <= Decimal("0.0001"):
                            open_buys[coin].pop(0)
                        else:
                            open_buys[coin][0] = (new_buy_amt, buy_price, buy_fee
                                                  - buy_fee_portion, buy_time, buy_symbol)

            # Add remaining open buy positions
            for coin, buy_list in open_buys.items():
                for buy_amt, buy_price, buy_fee, buy_time, buy_symbol in buy_list:
                    if buy_amt > Decimal("0.0001"):
                        open_trade = Trade(
                            coin=buy_symbol,
                            buy_price=buy_price,
                            buy_amount=buy_amt,
                            buy_time=buy_time,
                            buy_fee=buy_fee
                        )
                        trades.append(open_trade)

        except Exception as e:
            self.logger.error(f"Error reading trades from database: {e}")

        # If database is empty, parse from log file
        if not trades:
            self.logger.info("Database empty, parsing trades from log file...")
            trades = self._parse_trades_from_log(hours)

        return trades

    def _parse_trades_from_log(self, hours: int) -> List[Trade]:
        """Parse trades from log file using FIFO matching for grid trading"""
        trades = []
        cutoff_time = datetime.now() - timedelta(hours=hours)

        # Pattern to match trade fills
        trade_pattern = re.compile(
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?(BUY|SELL) order.*?(\d+\.\d+)/[\d.]+ (\w+) has been filled at ([\d.]+) EUR'  # noqa: E501
        )

        open_buys: Dict[str, List[Trade]] = {}  # coin -> list of open buy orders (FIFO queue)

        try:
            with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    match = trade_pattern.search(line)
                    if not match:
                        continue

                    timestamp_str, side, amount_str, coin_symbol, price_str = match.groups()
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')

                    if timestamp < cutoff_time:
                        continue

                    symbol = f"{coin_symbol}-EUR"
                    price = Decimal(price_str)
                    amount = Decimal(amount_str)
                    fee = amount * price * Decimal("0.0026")  # Kraken 0.26% fee estimate

                    if side == 'BUY':
                        trade = Trade(
                            coin=symbol,
                            buy_price=price,
                            buy_amount=amount,
                            buy_time=timestamp,
                            buy_fee=fee
                        )
                        if coin_symbol not in open_buys:
                            open_buys[coin_symbol] = []
                        open_buys[coin_symbol].append(trade)

                    elif side == 'SELL':
                        if coin_symbol not in open_buys or not open_buys[coin_symbol]:
                            self.logger.debug(f"Sell without matching buy for {coin_symbol}")
                            continue

                        remaining_sell = amount
                        remaining_fee = fee

                        # Match with oldest buys first (FIFO)
                        while remaining_sell > Decimal("0.0001") and open_buys[coin_symbol]:
                            buy_trade = open_buys[coin_symbol][0]
                            match_amount = min(buy_trade.buy_amount, remaining_sell)

                            # Proportional fees
                            buy_fee_portion = (match_amount / buy_trade.buy_amount) * buy_trade.buy_fee
                            sell_fee_portion = (match_amount / amount) * remaining_fee

                            # Create matched trade
                            closed_trade = Trade(
                                coin=symbol,
                                buy_price=buy_trade.buy_price,
                                buy_amount=match_amount,
                                buy_time=buy_trade.buy_time,
                                buy_fee=buy_fee_portion,
                                sell_price=price,
                                sell_amount=match_amount,
                                sell_time=timestamp,
                                sell_fee=sell_fee_portion
                            )
                            trades.append(closed_trade)

                            # Update remaining amounts
                            remaining_sell -= match_amount
                            remaining_fee -= sell_fee_portion
                            buy_trade.buy_amount -= match_amount
                            buy_trade.buy_fee -= buy_fee_portion

                            # Remove buy if fully consumed
                            if buy_trade.buy_amount <= Decimal("0.0001"):
                                open_buys[coin_symbol].pop(0)

            # Add remaining open positions
            for coin, buy_list in open_buys.items():
                for buy_trade in buy_list:
                    if buy_trade.buy_amount > Decimal("0.0001"):
                        trades.append(buy_trade)

        except Exception as e:
            self.logger.error(f"Error parsing trades from log: {e}")

        return trades

    def _read_recent_lines(self, cutoff_time: datetime) -> List[str]:
        """Read lines from log file after cutoff time"""
        relevant_lines = []

        try:
            with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # Quick check for timestamp
                    if len(line) > 19:
                        try:
                            timestamp_str = line[:19]
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                            if timestamp >= cutoff_time:
                                relevant_lines.append(line)
                        except ValueError:
                            # Not a timestamped line, include if we're past cutoff
                            if relevant_lines:
                                relevant_lines.append(line)
        except Exception as e:
            self.logger.error(f"Error reading log file: {e}")

        return relevant_lines

    def _parse_status(self, lines: List[str]) -> BotStatus:
        """Parse current status from recent log lines"""
        status = BotStatus()

        # Scan last 1000 lines for current status
        recent_lines = lines[-1000:] if len(lines) > 1000 else lines

        for line in reversed(recent_lines):
            # Check for active coin (multiple patterns)
            if status.active_coin is None:
                match = self.patterns['active_coin'].search(line)
                if match:
                    status.active_coin = match.group(1)
                    status.is_running = True
                else:
                    match = self.patterns['active_coin_alt'].search(line)
                    if match:
                        status.active_coin = match.group(1)
                        status.is_running = True

            # Check for best trend
            if status.best_trend_coin is None:
                match = self.patterns['best_coin'].search(line)
                if match:
                    status.best_trend_coin = match.group(1)
                    status.best_trend_pct = float(match.group(2))

            # Check for risk blocked
            if not status.is_blocked:
                match = self.patterns['risk_blocked'].search(line)
                if match:
                    status.is_blocked = True
                    status.block_reason = match.group(1)
                elif self.patterns['drawdown_blocked'].search(line):
                    status.is_blocked = True
                    status.block_reason = "Drawdown limit"

            # Get timestamp for last update
            if status.last_update is None and len(line) > 19:
                try:
                    status.last_update = datetime.strptime(line[:19], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pass

        # Parse top trends from last occurrence
        for line in reversed(recent_lines):
            if "Top 10 trends" in line or "Top Trends" in line:
                # Get next 10 lines for trends
                try:
                    idx = recent_lines.index(line)
                    trend_lines = recent_lines[idx:idx + 12]
                    for trend_line in trend_lines:
                        match = self.patterns['top_trends'].search(trend_line)
                        if match:
                            rank = int(match.group(1))
                            coin = match.group(2)
                            trend = float(match.group(3))
                            if rank <= 5:
                                status.top_trends.append((coin, trend))
                except (ValueError, IndexError):
                    pass
                break

        return status

    def _parse_issues(self, lines: List[str]) -> Tuple[List[str], List[str]]:
        """Parse errors and critical warnings"""
        errors = []
        warnings = []

        for line in lines[-1000:]:  # Last 1000 lines
            # Check for errors
            if 'ERROR' in line:
                match = self.patterns['error'].search(line)
                if match:
                    errors.append(f"{match.group(1)}: {match.group(2)[:100]}")

            # Check for critical warnings
            if 'CRITICAL' in line:
                match = self.patterns['warning'].search(line)
                if match:
                    warnings.append(f"{match.group(1)}: {match.group(2)[:100]}")

        return errors[-5:], warnings[-5:]  # Last 5 of each

    def _build_report(
        self,
        trades: List[Trade],
        status: BotStatus,
        errors: List[str],
        warnings: List[str]
    ) -> AnalysisReport:
        """Build complete analysis report"""

        # Calculate P&L
        realized_pnl = Decimal("0")
        win_count = 0
        loss_count = 0

        for trade in trades:
            if trade.is_closed:
                realized_pnl += trade.profit
                if trade.profit > 0:
                    win_count += 1
                else:
                    loss_count += 1

        # Get time range
        start_time = min((t.buy_time for t in trades), default=None)
        end_time = max(
            (t.sell_time or t.buy_time for t in trades),
            default=None
        )

        return AnalysisReport(
            trades=trades,
            status=status,
            start_time=start_time,
            end_time=end_time,
            total_pnl=realized_pnl,
            realized_pnl=realized_pnl,
            win_count=win_count,
            loss_count=loss_count,
            errors=errors,
            warnings=warnings
        )

    def format_telegram_report(self, report: AnalysisReport) -> str:
        """
        Format report for Telegram message

        Args:
            report: AnalysisReport to format

        Returns:
            Formatted HTML string for Telegram
        """
        lines = []

        # Header
        lines.append("📊 <b>BOT ANALYSE RAPPORT</b>")
        lines.append("")

        # Status
        lines.append("━━━ <b>STATUS</b> ━━━")
        if report.status.is_running:
            lines.append("✅ Bot draait")
        else:
            lines.append("❌ Bot status onbekend")

        if report.status.active_coin:
            lines.append(f"📍 Actieve coin: <b>{report.status.active_coin}</b>")

        if report.status.is_blocked:
            lines.append(f"🛑 GEBLOKKEERD: {report.status.block_reason}")

        lines.append("")

        # P&L Summary
        lines.append("━━━ <b>P&L OVERZICHT</b> ━━━")
        pnl_emoji = "✅" if report.realized_pnl >= 0 else "❌"
        lines.append(f"{pnl_emoji} Gerealiseerd: <b>€{report.realized_pnl:.2f}</b>")
        lines.append(f"📈 Winst trades: {report.win_count}")
        lines.append(f"📉 Verlies trades: {report.loss_count}")

        if report.win_count + report.loss_count > 0:
            win_rate = report.win_count / (report.win_count + report.loss_count) * 100
            lines.append(f"🎯 Win rate: {win_rate:.0f}%")

        lines.append("")

        # Trade History
        lines.append("━━━ <b>TRADE GESCHIEDENIS</b> ━━━")
        if not report.trades:
            lines.append("Geen trades gevonden")
        else:
            for i, trade in enumerate(report.trades[-6:], 1):  # Last 6 trades
                "✅" if trade.is_closed else "⏳"
                if trade.is_closed:
                    profit_emoji = "📈" if trade.profit > 0 else "📉"
                    lines.append(
                        f"{i}. {trade.coin} {profit_emoji} "
                        f"€{trade.profit:+.2f} ({trade.profit_pct:+.1f}%)"
                    )
                else:
                    lines.append(
                        f"{i}. {trade.coin} ⏳ OPEN "
                        f"@ €{trade.buy_price:.5f}"
                    )

        lines.append("")

        # Top Trends
        if report.status.top_trends:
            lines.append("━━━ <b>TOP TRENDS</b> ━━━")
            for coin, trend in report.status.top_trends[:5]:
                trend_emoji = "🚀" if trend > 5 else "📈" if trend > 0 else "📉"
                lines.append(f"{trend_emoji} {coin}: <b>{trend:+.2f}%</b>")
            lines.append("")

        # Issues
        if report.errors or report.warnings:
            lines.append("━━━ <b>PROBLEMEN</b> ━━━")
            for err in report.errors[:3]:
                lines.append(f"❌ {err[:60]}...")
            for warn in report.warnings[:3]:
                lines.append(f"⚠️ {warn[:60]}...")
            lines.append("")

        # Footer with current time (shows when analysis was done)
        lines.append(f"<i>📅 Analyse: {datetime.now().strftime('%d-%m %H:%M:%S')}</i>")
        if report.end_time:
            lines.append(f"<i>📈 Laatste trade: {report.end_time.strftime('%d-%m %H:%M')}</i>")

        return "\n".join(lines)

    def format_short_report(self, report: AnalysisReport) -> str:
        """Format a shorter summary for quick status"""
        status_emoji = "🟢" if report.status.is_running and not report.status.is_blocked else "🔴"

        lines = [
            f"{status_emoji} <b>Quick Status</b>",
            f"💰 P&L: <b>€{report.realized_pnl:.2f}</b>",
            f"📊 Trades: {report.win_count}W / {report.loss_count}L",
        ]

        if report.status.active_coin:
            lines.append(f"📍 {report.status.active_coin}")

        if report.status.is_blocked:
            lines.append("🛑 Blocked!")

        return "\n".join(lines)


def main():
    """CLI for testing analyzer"""
    import argparse

    parser = argparse.ArgumentParser(description="Trade Analyzer")
    parser.add_argument("--hours", type=int, default=24, help="Hours to analyze")
    parser.add_argument("--log", type=str, default=None, help="Log file path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    analyzer = TradeAnalyzer(log_path=args.log)
    report = analyzer.analyze(hours=args.hours)

    print(analyzer.format_telegram_report(report))


if __name__ == "__main__":
    main()

```

## Attachment: monitoring/dashboard.py (403 lines)

```python
"""
Flask Dashboard for Bot Monitoring

Simple web dashboard showing bot status, events, and P&L charts.
Runs on localhost:5000 by default.
"""

from flask import Flask, jsonify, render_template_string

from .config import MonitoringConfig
from .database import MonitoringDatabase

app = Flask(__name__)
db = None


def init_dashboard(database: MonitoringDatabase):
    """Initialize dashboard with database instance"""
    global db
    db = database


@app.route('/')
def index():
    """Main dashboard page"""
    return render_template_string(DASHBOARD_HTML)


@app.route('/api/status')
def api_status():
    """Get latest bot status"""
    if not db:
        return jsonify({"error": "Database not initialized"}), 500

    status = db.get_latest_status()
    if status:
        # Convert datetime strings to ISO format
        if 'timestamp' in status:
            status['timestamp'] = status['timestamp']
        return jsonify(status)
    return jsonify({"error": "No status found"}), 404


@app.route('/api/events')
def api_events():
    """Get recent events"""
    if not db:
        return jsonify({"error": "Database not initialized"}), 500

    limit = 30
    events = db.get_recent_events(limit=limit)
    return jsonify({"events": events, "count": len(events)})


@app.route('/api/trades')
def api_trades():
    """Get trades from today"""
    if not db:
        return jsonify({"error": "Database not initialized"}), 500

    trades = db.get_trades_today()
    return jsonify({"trades": trades, "count": len(trades)})


@app.route('/api/pnl_chart')
def api_pnl_chart():
    """Get P&L history for chart"""
    if not db:
        return jsonify({"error": "Database not initialized"}), 500

    hours = 24
    history = db.get_pnl_history(hours=hours)

    # Format for Chart.js
    chart_data = {
        "labels": [item["timestamp"] for item in history],
        "pnl": [item["pnl"] for item in history],
        "coins": [item["active_coin"] or "None" for item in history]
    }

    return jsonify(chart_data)


def run_dashboard(host: str = None, port: int = None, debug: bool = False):
    """Run Flask dashboard"""
    import socket

    host = host or MonitoringConfig.DASHBOARD_HOST
    port = port or MonitoringConfig.DASHBOARD_PORT

    # Check if port is available, if not try next available port
    original_port = port
    max_attempts = 10
    for attempt in range(max_attempts):
        try:
            # Try to bind to the port to check if it's available
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_socket.bind((host, port))
            test_socket.close()
            # Port is available
            break
        except OSError:
            # Port is in use, try next port
            if attempt == 0:
                print(f"⚠️  Port {port} is already in use, trying alternative port...")
            port = original_port + attempt + 1
            if attempt == max_attempts - 1:
                print(f"❌ Could not find available port after {max_attempts} attempts")
                raise

    if port != original_port:
        print(f"✅ Using alternative port: {port} (original {original_port} was in use)")

    print(f"🚀 Starting dashboard on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


# HTML Template for Dashboard
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Monitoring Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { color: #4CAF50; margin-bottom: 30px; }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .status-card {
            background: #2a2a2a;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #4CAF50;
        }
        .status-card.warning { border-left-color: #ff9800; }
        .status-card.error { border-left-color: #f44336; }
        .status-card h3 {
            font-size: 14px;
            color: #888;
            margin-bottom: 10px;
            text-transform: uppercase;
        }
        .status-card .value {
            font-size: 24px;
            font-weight: bold;
            color: #4CAF50;
        }
        .status-card .value.negative { color: #f44336; }
        .events-section {
            background: #2a2a2a;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
        }
        .events-section h2 { margin-bottom: 15px; }
        .event-item {
            padding: 10px;
            border-bottom: 1px solid #333;
            font-size: 14px;
        }
        .event-item:last-child { border-bottom: none; }
        .event-type {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 12px;
            margin-right: 10px;
        }
        .event-type.error { background: #f44336; color: white; }
        .event-type.stop_loss { background: #ff9800; color: white; }
        .event-type.trend_switch { background: #2196F3; color: white; }
        .chart-container {
            background: #2a2a2a;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
        }
        .chart-container canvas { max-height: 400px; }
        .refresh-info {
            text-align: center;
            color: #888;
            margin-top: 20px;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 Bot Monitoring Dashboard</h1>

        <!-- Status Cards -->
        <div class="status-grid" id="statusGrid">
            <div class="status-card">
                <h3>Active Coin</h3>
                <div class="value" id="activeCoin">-</div>
            </div>
            <div class="status-card">
                <h3>P&L</h3>
                <div class="value" id="pnl">€0.00</div>
            </div>
            <div class="status-card">
                <h3>Exposure</h3>
                <div class="value" id="exposure">€0.00</div>
            </div>
            <div class="status-card" id="modeCard">
                <h3>Mode</h3>
                <div class="value" id="mode">-</div>
            </div>
            <div class="status-card">
                <h3>Latency</h3>
                <div class="value" id="latency">-</div>
            </div>
            <div class="status-card">
                <h3>Connection</h3>
                <div class="value" id="connection">-</div>
            </div>
        </div>

        <!-- P&L Chart -->
        <div class="chart-container">
            <h2>P&L History (24h)</h2>
            <canvas id="pnlChart"></canvas>
        </div>

        <!-- Recent Events -->
        <div class="events-section">
            <h2>Recent Events</h2>
            <div id="eventsList"></div>
        </div>

        <div class="refresh-info">
            Auto-refresh every 5 seconds | Last update: <span id="lastUpdate">-</span>
        </div>
    </div>

    <script>
        let pnlChart = null;

        function updateStatus() {
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('activeCoin').textContent = data.active_coin || '-';
                    document.getElementById('pnl').textContent = '€' + (data.pnl || 0).toFixed(2);
                    document.getElementById('pnl').className = 'value' + (data.pnl < 0 ? ' negative' : '');
                    document.getElementById('exposure').textContent = '€' + (data.exposure || 0).toFixed(2);
                    document.getElementById('mode').textContent = data.mode || '-';
                    document.getElementById('latency').textContent = data.heartbeat_latency ?
                        data.heartbeat_latency.toFixed(0) + 'ms' : '-';
                    document.getElementById('connection').textContent = data.connection_status || '-';

                    const modeCard = document.getElementById('modeCard');
                    modeCard.className = 'status-card';
                    if (data.mode === 'paused') modeCard.classList.add('warning');
                    if (data.mode === 'error_safe_mode') modeCard.classList.add('error');

                    document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
                })
                .catch(e => console.error('Status error:', e));
        }

        function updateEvents() {
            fetch('/api/events')
                .then(r => r.json())
                .then(data => {
                    const list = document.getElementById('eventsList');
                    list.innerHTML = data.events.slice(0, 20).map(event => {
                        const time = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : '-';
                        // Show more characters for better visibility (200 instead of 100)
                        // Also add word wrapping for long messages
                        const message = event.message || '';
                        const displayMessage = message.length > 1200 ? message.substring(0, 1197) + '...' : message;
                        return `
                            <div class="event-item" title="${message.replace(/"/g, '&quot;')}">
                                <span class="event-type ${event.event_type}">${event.event_type}</span>
                                <span>${time}</span>
                                <span style="margin-left: 10px; word-wrap: break-word; max-width: 800px; display: inline-block;">${displayMessage}</span>  # noqa: E501
                            </div>
                        `;
                    }).join('');
                })
                .catch(e => console.error('Events error:', e));
        }

        function updateChart() {
            fetch('/api/pnl_chart')
                .then(r => r.json())
                .then(data => {
                    if (!pnlChart) {
                        const ctx = document.getElementById('pnlChart').getContext('2d');
                        pnlChart = new Chart(ctx, {
                            type: 'line',
                            data: {
                                labels: data.labels,
                                datasets: [{
                                    label: 'P&L (€)',
                                    data: data.pnl,
                                    borderColor: '#4CAF50',
                                    backgroundColor: 'rgba(76, 175, 80, 0.1)',
                                    tension: 0.4
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: true,
                                scales: {
                                    y: {
                                        beginAtZero: false,
                                        ticks: { color: '#888' },
                                        grid: { color: '#333' }
                                    },
                                    x: {
                                        ticks: { color: '#888', maxTicksLimit: 10 },
                                        grid: { color: '#333' }
                                    }
                                },
                                plugins: {
                                    legend: { labels: { color: '#e0e0e0' } }
                                }
                            }
                        });
                    } else {
                        pnlChart.data.labels = data.labels;
                        pnlChart.data.datasets[0].data = data.pnl;
                        pnlChart.update();
                    }
                })
                .catch(e => console.error('Chart error:', e));
        }

        function refreshAll() {
            updateStatus();
            updateEvents();
            updateChart();
        }

        // Initial load
        refreshAll();

        // Auto-refresh every 5 seconds
        setInterval(refreshAll, 5000);
    </script>
</body>
</html>
"""


def main():
    """Main entry point for dashboard"""
    import argparse

    parser = argparse.ArgumentParser(description="Bot Monitoring Dashboard")
    parser.add_argument(
        "--host",
        type=str,
        default=MonitoringConfig.DASHBOARD_HOST,
        help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=MonitoringConfig.DASHBOARD_PORT,
        help="Port to bind to (default: 5000)"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database (default: auto)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )

    args = parser.parse_args()

    # Initialize database
    database = MonitoringDatabase(db_path=args.db_path)
    init_dashboard(database)

    # Run dashboard
    run_dashboard(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()

```

## Attachment: monitoring/telegram_bot_handler.py (452 lines)

```python
"""
Telegram Bot Command Handler

Listens for incoming Telegram messages and handles commands.
Runs as a separate service that polls Telegram for new messages.

Commands:
- /vertel - Full analysis report (Dutch: "tell me")
- /status - Quick status
- /trades - Recent trades
- /trends - Current trends
- /events - Recent events
- /help - Show commands
"""

import logging
import time
from typing import Any, Dict

import requests

from .config import MonitoringConfig
from .database import MonitoringDatabase
from .telegram_bot import TelegramBot
from .trade_analyzer import TradeAnalyzer


class TelegramBotHandler:
    """Handles incoming Telegram commands via polling"""

    def __init__(self, bot: TelegramBot, log_path: str = None):
        """
        Initialize command handler

        Args:
            bot: TelegramBot instance
            log_path: Path to bot log file (optional)
        """
        self.bot = bot
        self.base_url = bot.base_url
        self.logger = logging.getLogger(__name__)
        self.last_update_id = 0

        # Initialize analyzer
        self.analyzer = TradeAnalyzer(log_path=log_path)

        # Command handlers
        self.commands = {
            "/start": self._handle_start,
            "/status": self._handle_status,
            "/events": self._handle_events,
            "/help": self._handle_help,
            "/vertel": self._handle_vertel,
            "/analyse": self._handle_vertel,  # Alias
            "/analyze": self._handle_vertel,  # English alias
            "/trades": self._handle_trades,
            "/trends": self._handle_trends,
            "/quick": self._handle_quick,
            "/pnl": self._handle_pnl,
        }

    def get_updates(self, timeout: int = 10) -> list:
        """
        Get new updates from Telegram

        Args:
            timeout: Long polling timeout in seconds

        Returns:
            List of updates
        """
        try:
            url = f"{self.base_url}/getUpdates"
            params = {
                "offset": self.last_update_id + 1,
                "timeout": timeout,
                "allowed_updates": ["message"]
            }

            response = requests.get(url, params=params, timeout=timeout + 5)
            response.raise_for_status()
            data = response.json()

            if data.get("ok"):
                return data.get("result", [])
            return []
        except Exception as e:
            self.logger.error(f"Error getting updates: {e}")
            return []

    def process_update(self, update: Dict[str, Any]):
        """Process a single update"""
        message = update.get("message", {})
        if not message:
            return

        text = message.get("text", "").strip()
        chat_id = str(message.get("chat", {}).get("id"))

        # Only respond to messages from configured chat ID
        if chat_id != self.bot.chat_id:
            self.logger.debug(f"Ignoring message from chat {chat_id} (not configured)")
            return

        # Check if it's a command
        if text.startswith("/"):
            command = text.split()[0].lower()
            handler = self.commands.get(command)
            if handler:
                try:
                    handler(message)
                except Exception as e:
                    self.logger.error(f"Error handling command {command}: {e}")
                    self.bot.send_message(f"❌ Error processing command: {e}")
            else:
                self.bot.send_message(f"❓ Unknown command: {command}\n\nType /help for available commands")
        else:
            # Regular message - send help
            self.bot.send_message("👋 Hi! Send /help to see available commands.")

    def _handle_start(self, message: Dict[str, Any]):
        """Handle /start command"""
        help_text = """
🤖 <b>Multi-Coin Grid Bot Monitor</b>

<b>Belangrijkste commands:</b>
/vertel - 📊 Uitgebreide analyse rapport
/quick - ⚡ Snelle status
/trades - 📈 Recente trades
/trends - 📊 Top trending coins
/pnl - 💰 P&L overzicht

Type /help voor alle commands.

<b>Automatische alerts:</b>
🛑 Stop-loss | ⚡ Circuit breaker | ❌ Errors
"""
        self.bot.send_message(help_text)

    def _handle_status(self, message: Dict[str, Any]):
        """Handle /status command"""
        self.bot.send_status()

    def _handle_events(self, message: Dict[str, Any]):
        """Handle /events command"""
        # Parse optional limit from command: /events 10
        text = message.get("text", "")
        parts = text.split()
        limit = 5
        if len(parts) > 1:
            try:
                limit = int(parts[1])
                limit = min(limit, 20)  # Max 20 events
            except ValueError:
                pass

        self.bot.send_recent_events(limit=limit)

    def _handle_help(self, message: Dict[str, Any]):
        """Handle /help command"""
        help_text = """
📋 <b>Beschikbare Commands:</b>

<b>📊 Analyse:</b>
/vertel - Uitgebreide analyse (trades, P&L, trends)
/quick - Snelle status samenvatting
/pnl - Alleen P&L overzicht

<b>📈 Trading:</b>
/trades [N] - Laatste N trades (default: 5)
/trends - Huidige top trends
/status - Bot status

<b>📋 Logs:</b>
/events [N] - Laatste N events (default: 5)

<b>ℹ️ Info:</b>
/help - Dit menu

<b>Automatische Alerts:</b>
🛑 Stop-loss triggers
⚡ Circuit breaker
❌ Kritieke errors
🔄 Coin switches
"""
        self.bot.send_message(help_text)

    def _handle_vertel(self, message: Dict[str, Any]):
        """Handle /vertel command - Full analysis report"""
        self.bot.send_message("🔍 <i>Analyseren... even geduld...</i>")

        try:
            # Parse optional hours parameter
            text = message.get("text", "")
            parts = text.split()
            hours = 24
            if len(parts) > 1:
                try:
                    hours = int(parts[1])
                    hours = min(hours, 72)  # Max 72 hours
                except ValueError:
                    pass

            # Run analysis
            report = self.analyzer.analyze(hours=hours)

            # Format and send
            formatted = self.analyzer.format_telegram_report(report)
            self.bot.send_message(formatted)

        except Exception as e:
            self.logger.error(f"Error in /vertel: {e}")
            self.bot.send_message(f"❌ Analyse fout: {e}")

    def _handle_trades(self, message: Dict[str, Any]):
        """Handle /trades command - Show recent trades"""
        try:
            text = message.get("text", "")
            parts = text.split()
            limit = 5
            if len(parts) > 1:
                try:
                    limit = int(parts[1])
                    limit = min(limit, 15)
                except ValueError:
                    pass

            report = self.analyzer.analyze(hours=24)

            if not report.trades:
                self.bot.send_message("📭 Geen trades gevonden in de laatste 24 uur")
                return

            lines = [f"📈 <b>Laatste {min(limit, len(report.trades))} Trades:</b>", ""]

            for i, trade in enumerate(report.trades[-limit:], 1):
                if trade.is_closed:
                    profit_emoji = "✅" if trade.profit > 0 else "❌"
                    lines.append(
                        f"{i}. <b>{trade.coin}</b> {profit_emoji}\n"
                        f"   Buy: €{trade.buy_price:.5f} → Sell: €{trade.sell_price:.5f}\n"
                        f"   P&L: <b>€{trade.profit:+.2f}</b> ({trade.profit_pct:+.1f}%)\n"
                        f"   {trade.buy_time.strftime('%H:%M')} - {trade.sell_time.strftime('%H:%M')}"
                    )
                else:
                    lines.append(
                        f"{i}. <b>{trade.coin}</b> ⏳ OPEN\n"
                        f"   Entry: €{trade.buy_price:.5f}\n"
                        f"   Amount: {trade.buy_amount:.2f}\n"
                        f"   Since: {trade.buy_time.strftime('%H:%M')}"
                    )
                lines.append("")

            self.bot.send_message("\n".join(lines))

        except Exception as e:
            self.logger.error(f"Error in /trades: {e}")
            self.bot.send_message(f"❌ Error: {e}")

    def _handle_trends(self, message: Dict[str, Any]):
        """Handle /trends command - Show current trends"""
        try:
            report = self.analyzer.analyze(hours=1)  # Just need current status

            if not report.status.top_trends:
                self.bot.send_message("📊 Geen trend data beschikbaar")
                return

            lines = ["📊 <b>Top Trends (24h)</b>", ""]

            for i, (coin, trend) in enumerate(report.status.top_trends, 1):
                if trend > 10:
                    emoji = "🚀"
                elif trend > 5:
                    emoji = "📈"
                elif trend > 0:
                    emoji = "📊"
                else:
                    emoji = "📉"

                lines.append(f"{i}. {emoji} <b>{coin}</b>: {trend:+.2f}%")

            if report.status.best_trend_coin:
                lines.append("")
                lines.append(f"🏆 Best: <b>{report.status.best_trend_coin}</b> ({report.status.best_trend_pct:+.2f}%)")

            if report.status.is_blocked:
                lines.append("")
                lines.append(f"🛑 <b>GEBLOKKEERD:</b> {report.status.block_reason}")

            self.bot.send_message("\n".join(lines))

        except Exception as e:
            self.logger.error(f"Error in /trends: {e}")
            self.bot.send_message(f"❌ Error: {e}")

    def _handle_quick(self, message: Dict[str, Any]):
        """Handle /quick command - Quick status summary"""
        try:
            report = self.analyzer.analyze(hours=24)
            formatted = self.analyzer.format_short_report(report)
            self.bot.send_message(formatted)
        except Exception as e:
            self.logger.error(f"Error in /quick: {e}")
            self.bot.send_message(f"❌ Error: {e}")

    def _handle_pnl(self, message: Dict[str, Any]):
        """Handle /pnl command - P&L summary"""
        try:
            report = self.analyzer.analyze(hours=24)

            pnl_emoji = "✅" if report.realized_pnl >= 0 else "❌"

            lines = [
                "💰 <b>P&L Overzicht (24h)</b>",
                "",
                f"{pnl_emoji} Gerealiseerd: <b>€{report.realized_pnl:.2f}</b>",
                "",
                f"📈 Winstgevende trades: {report.win_count}",
                f"📉 Verliesgevende trades: {report.loss_count}",
            ]

            if report.win_count + report.loss_count > 0:
                win_rate = report.win_count / (report.win_count + report.loss_count) * 100
                lines.append(f"🎯 Win rate: <b>{win_rate:.0f}%</b>")

                # Calculate average win/loss
                wins = [t.profit for t in report.trades if t.is_closed and t.profit > 0]
                losses = [t.profit for t in report.trades if t.is_closed and t.profit < 0]

                if wins:
                    avg_win = sum(wins) / len(wins)
                    lines.append(f"📈 Gem. winst: €{avg_win:.2f}")
                if losses:
                    avg_loss = sum(losses) / len(losses)
                    lines.append(f"📉 Gem. verlies: €{avg_loss:.2f}")

            self.bot.send_message("\n".join(lines))

        except Exception as e:
            self.logger.error(f"Error in /pnl: {e}")
            self.bot.send_message(f"❌ Error: {e}")

    def run_polling(self, poll_interval: int = 1):
        """
        Run command handler with polling

        Args:
            poll_interval: Seconds between polls (when no updates)
        """
        self.logger.info("🤖 Starting Telegram command handler (polling mode)")
        self.logger.info(f"📱 Listening for commands in chat {self.bot.chat_id}")

        try:
            while True:
                updates = self.get_updates(timeout=10)

                for update in updates:
                    update_id = update.get("update_id")
                    if update_id > self.last_update_id:
                        self.last_update_id = update_id
                        self.process_update(update)

                # Small sleep to avoid busy waiting
                if not updates:
                    time.sleep(poll_interval)

        except KeyboardInterrupt:
            self.logger.info("🛑 Telegram command handler stopped by user")
        except Exception as e:
            self.logger.error(f"Error in polling loop: {e}")
            raise


def main():
    """Main entry point for command handler"""
    import argparse

    parser = argparse.ArgumentParser(description="Telegram Bot Command Handler")
    parser.add_argument(
        "--token",
        type=str,
        default=MonitoringConfig.TELEGRAM_BOT_TOKEN,
        help="Telegram bot token"
    )
    parser.add_argument(
        "--chat-id",
        type=str,
        default=MonitoringConfig.TELEGRAM_CHAT_ID,
        help="Telegram chat ID"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database (default: auto)"
    )
    parser.add_argument(
        "--log-path",
        type=str,
        default=MonitoringConfig.LOG_FILE,
        help="Path to bot log file for analysis"
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=1,
        help="Poll interval in seconds (default: 1)"
    )

    args = parser.parse_args()

    if not args.token or not args.chat_id:
        print("❌ Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        return

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("=" * 50)
    print("🤖 TELEGRAM BOT COMMAND HANDLER")
    print("=" * 50)
    print(f"📱 Chat ID: {args.chat_id}")
    print(f"📁 Log file: {args.log_path}")
    print("")
    print("📋 Available commands:")
    print("  /vertel  - Full analysis report")
    print("  /quick   - Quick status")
    print("  /trades  - Recent trades")
    print("  /trends  - Top trends")
    print("  /pnl     - P&L overview")
    print("  /help    - All commands")
    print("")
    print("🚀 Starting polling...")
    print("=" * 50)

    # Initialize database and bot
    db = MonitoringDatabase(db_path=args.db_path)
    bot = TelegramBot(args.token, args.chat_id, db)

    # Initialize command handler with log path
    handler = TelegramBotHandler(bot, log_path=args.log_path)

    # Run polling
    handler.run_polling(poll_interval=args.poll_interval)


if __name__ == "__main__":
    main()

```

## Attachment: Data Snapshot (2026-03-08)

# Bot Data Snapshot — 8 March 2026

> **Snapshot date**: 2026-03-08 ~15:00 UTC
> **Purpose**: Attach this file as evidence when running a review round.
> **Shelf life**: Data becomes stale within days. Re-run the queries below
> to generate a fresh snapshot before each review round.

---

## How to regenerate this snapshot

Run from the repo root (`/home/mo/repos/hummingbot`):

```bash
# Activate the venv first
source .venv/bin/activate

# ──────────────────────────────────────────────────
# 1. DATABASE QUERIES  (repeat for each .sqlite DB)
# ──────────────────────────────────────────────────

# Per-pair performance
sqlite3 -header -column data/<DB>.sqlite "
SELECT json_extract(config, '\$.trading_pair') as pair,
    COUNT(*) as trades,
    SUM(CASE WHEN net_pnl_quote > 0 THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN net_pnl_quote < 0 THEN 1 ELSE 0 END) as losses,
    SUM(CASE WHEN filled_amount_quote = 0 THEN 1 ELSE 0 END) as zero_fill,
    ROUND(SUM(net_pnl_quote), 4) as total_pnl,
    ROUND(SUM(cum_fees_quote), 4) as fees,
    ROUND(SUM(filled_amount_quote), 2) as volume
FROM Executors WHERE close_type IS NOT NULL
GROUP BY json_extract(config, '\$.trading_pair') ORDER BY total_pnl DESC;"

# Close type distribution
sqlite3 -header -column data/<DB>.sqlite "
SELECT close_type, COUNT(*) as cnt,
    ROUND(SUM(net_pnl_quote), 4) as sum_pnl,
    ROUND(SUM(filled_amount_quote), 2) as volume
FROM Executors WHERE close_type IS NOT NULL
GROUP BY close_type ORDER BY cnt DESC;"

# Date range + totals
sqlite3 -header -column data/<DB>.sqlite "
SELECT date(MIN(timestamp), 'unixepoch') as first,
    date(MAX(timestamp), 'unixepoch') as last,
    COUNT(*) as total,
    SUM(CASE WHEN filled_amount_quote > 0 THEN 1 ELSE 0 END) as filled,
    ROUND(100.0 * SUM(CASE WHEN filled_amount_quote > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as fill_pct,
    ROUND(SUM(net_pnl_quote), 4) as pnl,
    ROUND(SUM(cum_fees_quote), 4) as fees,
    ROUND(SUM(filled_amount_quote), 2) as vol
FROM Executors WHERE close_type IS NOT NULL;"

# Futures only: filled trades by pair + close type
sqlite3 -header -column data/futures_grid_bitget.sqlite "
SELECT json_extract(config, '\$.trading_pair') as pair, close_type,
    COUNT(*) as cnt,
    SUM(CASE WHEN net_pnl_quote > 0 THEN 1 ELSE 0 END) as wins,
    ROUND(SUM(net_pnl_quote), 4) as total_pnl,
    ROUND(SUM(filled_amount_quote), 2) as volume
FROM Executors WHERE close_type IS NOT NULL AND filled_amount_quote > 0
GROUP BY pair, close_type ORDER BY total_pnl DESC;"

# ──────────────────────────────────────────────────
# 2. LOG ERROR FREQUENCY
# ──────────────────────────────────────────────────

# Find the most recent log for each bot:
ls -t logs/logs_multi_coin_grid_v2_usd_*.log | head -1   # Kraken USD
ls -t logs/logs_spot_grid_bitget_*.log | head -1          # Bitget Spot
ls -t logs/logs_futures_grid_bitget_*.log | head -1       # Bitget Futures

# Then for each:
grep -oP "(ERROR|WARNING|CRITICAL)" <logfile> | sort | uniq -c | sort -rn
grep "ERROR" <logfile> | grep -oP "ERROR - .*" | sort -u | head -15
grep -c "WSS_ERROR\|WebSocket\|websocket" <logfile>       # WebSocket count

# ──────────────────────────────────────────────────
# 3. WHY-NO-TRADE SUMMARIES
# ──────────────────────────────────────────────────

# Find the most recent report log:
ls -t logs/kraken_*report*.log | head -1
ls -t logs/bitget_*report*.log | head -1

# Extract the last few hours:
grep -B1 -A 15 "WHY-NO-TRADE SUMMARY" <report_log> | tail -60

# ──────────────────────────────────────────────────
# 4. ROTATION TIMEOUT EVENTS
# ──────────────────────────────────────────────────

grep -oP "MONITORING TIMEOUT: \K[A-Z]+-[A-Z]+" <logfile> | sort | uniq -c | sort -rn
grep -i "MONITORING TIMEOUT" <logfile> | tail -20
```

Replace `<DB>` with: `multi_coin_grid_v2.sqlite` (Kraken EUR),
`multi_coin_grid_v2_usd.sqlite` (Kraken USD), `spot_grid_bitget.sqlite`
(Bitget Spot), `futures_grid_bitget.sqlite` (Bitget Futures).

---

## Database files

| Database | Bot | Size | Period |
|----------|-----|------|--------|
| `data/multi_coin_grid_v2.sqlite` | Kraken EUR (retired) | 12 MB | 2025-11-20 → 2026-02-05 |
| `data/multi_coin_grid_v2_usd.sqlite` | Kraken USD (active) | 8.0 MB | 2026-01-21 → 2026-01-23 |
| `data/spot_grid_bitget.sqlite` | Bitget Spot (blocked) | 6.0 MB | 2026-01-06 → 2026-01-12 |
| `data/futures_grid_bitget.sqlite` | Bitget Futures (blocked) | 2.9 MB | 2026-02-01 → 2026-02-10 |

## Close type legend

| Code | Meaning |
|------|---------|
| 3 | TAKE_PROFIT |
| 5 | EARLY_STOP (no-fill, soft stop) |
| 7 | EXPIRED / no-fill timeout |
| 8 | STOP_LOSS |
| 11 | FAILED_TO_OPEN |
| 12 | SMART_SWITCH (rotation exit) |

---

## 1. Kraken EUR (historical, retired)

**Period**: 2025-11-20 → 2026-02-05 (77 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 2,209 | 34 | 1.5% | −€73.39 | €3.71 | €2,236.62 |

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 5 (EARLY_STOP) | 1,473 | +€11.83 | €1,767.85 |
| 7 (EXPIRED) | 704 | €0.00 | €0.00 |
| 3 (TAKE_PROFIT) | 11 | +€24.49 | €248.48 |
| 8 (STOP_LOSS) | 7 | −€109.72 | €220.29 |
| 11 (FAILED_TO_OPEN) | 11 | €0.00 | €0.00 |
| 12 (SMART_SWITCH) | 3 | €0.00 | €0.00 |

### Per-pair performance (pairs with fills only)
| Pair | Trades | Wins | Losses | Zero-fill | PnL | Fees | Volume |
|------|--------|------|--------|-----------|-----|------|--------|
| STRK-EUR | 10 | 1 | 0 | 9 | +€24.40 | €0.96 | €216.94 |
| TAO-EUR | 45 | 2 | 2 | 41 | +€1.96 | €0.00 | €115.44 |
| XTZ-EUR | 56 | 1 | 1 | 54 | −€0.30 | €0.01 | €139.54 |
| ATOM-EUR | 303 | 0 | 3 | 300 | −€0.32 | €0.01 | €174.54 |
| POL-EUR | 236 | 1 | 3 | 232 | −€0.50 | €0.01 | €279.26 |
| JASMY-EUR | 2 | 0 | 1 | 1 | −€0.68 | €0.00 | €104.09 |
| UNI-EUR | 13 | 0 | 1 | 12 | −€1.11 | €0.97 | €215.79 |
| SOL-EUR | 122 | 1 | 4 | 117 | −€2.32 | €1.73 | €557.85 |
| SUI-EUR | 95 | 0 | 1 | 94 | −€0.01 | €0.00 | €34.96 |
| DOT-EUR | 89 | 0 | 1 | 88 | −€0.02 | €0.00 | €34.95 |
| ALGO-EUR | 4 | 0 | 1 | 3 | −€15.56 | €0.00 | €31.47 |
| RENDER-EUR | 103 | 0 | 2 | 101 | −€15.63 | €0.00 | €66.40 |
| ADA-EUR | 104 | 0 | 1 | 103 | −€15.63 | €0.00 | €31.47 |
| CC-EUR | 26 | 1 | 4 | 21 | −€15.70 | €0.01 | €170.98 |
| AAVE-EUR | 30 | 0 | 1 | 29 | −€15.93 | €0.00 | €31.47 |
| PEPE-EUR | 1 | 0 | 1 | 0 | −€16.02 | €0.00 | €31.47 |

### Per-pair (zero-fill only, no trades — top 10 by executor count)
| Pair | Executors | All zero-fill |
|------|-----------|---------------|
| SAND-EUR | 152 | 152 |
| FIL-EUR | 157 | 157 |
| MANA-EUR | 127 | 127 |
| SNX-EUR | 124 | 124 |
| BNB-EUR | 92 | 92 |
| ZRO-EUR* | — | — |
| DOGE-EUR | 42 | 42 |
| KAS-EUR | 31 | 31 |
| BCH-EUR | 33 | 33 |
| OPEN-EUR | 29 | 29 |

---

## 2. Kraken USD (active, limited data)

**Period**: 2026-01-21 → 2026-01-23 (2 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 212 | 1 | 0.5% | −$0.26 | $0.00 | $33.04 |

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 7 (EXPIRED) | 210 | $0.00 | $0.00 |
| 11 (FAILED_TO_OPEN) | 1 | $0.00 | $0.00 |
| 5 (EARLY_STOP) | 1 | −$0.26 | $33.04 |

### Per-pair performance
| Pair | Trades | Wins | Losses | Zero-fill | PnL |
|------|--------|------|--------|-----------|-----|
| ZRO-USD | 68 | 0 | 0 | 68 | $0.00 |
| XCN-USD | 48 | 0 | 0 | 48 | $0.00 |
| TAO-USD | 8 | 0 | 0 | 8 | $0.00 |
| SOL-USD | 14 | 0 | 0 | 14 | $0.00 |
| SAND-USD | 8 | 0 | 0 | 8 | $0.00 |
| MANA-USD | 7 | 0 | 0 | 7 | $0.00 |
| AVAX-USD | 7 | 0 | 0 | 7 | $0.00 |
| ADA-USD | 10 | 0 | 0 | 10 | $0.00 |
| AXS-USD | 42 | 0 | 1 | 41 | −$0.26 |

---

## 3. Bitget Spot (capital-blocked)

**Period**: 2026-01-06 → 2026-01-12 (6 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 400 | 6 | 1.5% | −$0.72 | $0.36 | $242.77 |

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 5 (EARLY_STOP) | 382 | −$0.31 | $132.83 |
| 12 (SMART_SWITCH) | 9 | −$0.41 | $109.93 |
| 11 (FAILED_TO_OPEN) | 9 | $0.00 | $0.00 |

### Per-pair performance (pairs with fills only)
| Pair | Trades | Wins | Losses | Zero-fill | PnL | Fees | Volume |
|------|--------|------|--------|-----------|-----|------|--------|
| AVA-USDT | 99 | 0 | 1 | 98 | −$0.03 | $0.03 | $22.17 |
| ASTR-USDT | 4 | 0 | 1 | 3 | −$0.04 | $0.03 | $22.18 |
| CHZ-USDT | 8 | 0 | 1 | 7 | −$0.08 | $0.07 | $44.39 |
| SWCH-USDT | 57 | 0 | 3 | 54 | −$0.56 | $0.23 | $154.02 |

**Current state**: BLOCKED — $3.62 free capital < $30.00 minimum.
Stuck SONIC LIMIT SELL @ $0.046419 (1533 units) locking ~$71.

---

## 4. Bitget Futures (capital-depleted)

**Period**: 2026-02-01 → 2026-02-10 (9 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 932 | 23 | 2.5% | −$155.39 | −$0.09* | $472.90 |

*Negative fees = maker rebates on some trades.

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 3 (TAKE_PROFIT) | 737 | +$0.57 | $33.85 |
| 7 (EXPIRED) | 171 | $0.00 | $0.00 |
| 8 (STOP_LOSS) | 22 | −$155.96 | $439.05 |
| 11 (FAILED_TO_OPEN) | 2 | $0.00 | $0.00 |

### Per-pair performance
| Pair | Trades | Wins | Losses | Zero-fill | PnL | Fees | Volume |
|------|--------|------|--------|-----------|-----|------|--------|
| SOL-USDT | 101 | 2 | 0 | 99 | +$9.31 | −$0.01 | $67.83 |
| SUI-USDT | 72 | 1 | 1 | 70 | +$0.09 | −$0.01 | $31.53 |
| AVAX-USDT | 113 | 0 | 1 | 112 | −$5.42 | $0.00 | $10.90 |
| LINK-USDT | 175 | 0 | 1 | 174 | −$9.56 | $0.00 | $19.26 |
| DOGE-USDT | 28 | 1 | 3 | 24 | −$10.57 | −$0.01 | $42.33 |
| XRP-USDT | 217 | 1 | 2 | 214 | −$11.96 | −$0.01 | $46.37 |
| OP-USDT | 1 | 0 | 1 | 0 | −$12.61 | −$0.01 | $24.86 |
| ARB-USDT | 116 | 0 | 3 | 113 | −$23.05 | −$0.01 | $45.90 |
| BTC-USDT | 59 | 0 | 3 | 56 | −$28.84 | −$0.01 | $57.73 |
| ETH-USDT | 50 | 0 | 3 | 47 | −$62.78 | −$0.03 | $126.18 |

### Filled trades detail (close type breakdown)
| Pair | Close type | Count | Wins | PnL | Volume |
|------|------------|-------|------|-----|--------|
| SOL-USDT | 8 (STOP_LOSS) | 1 | 1 | +$8.74 | $33.98 |
| SOL-USDT | 3 (TAKE_PROFIT) | 1 | 1 | +$0.57 | $33.85 |
| SUI-USDT | 8 (STOP_LOSS) | 2 | 1 | +$0.09 | $31.53 |
| AVAX-USDT | 8 | 1 | 0 | −$5.42 | $10.90 |
| LINK-USDT | 8 | 1 | 0 | −$9.56 | $19.26 |
| DOGE-USDT | 8 | 4 | 1 | −$10.57 | $42.33 |
| XRP-USDT | 8 | 3 | 1 | −$11.96 | $46.37 |
| OP-USDT | 8 | 1 | 0 | −$12.61 | $24.86 |
| ARB-USDT | 8 | 3 | 0 | −$23.05 | $45.90 |
| BTC-USDT | 8 | 3 | 0 | −$28.84 | $57.73 |
| ETH-USDT | 8 | 3 | 0 | −$62.78 | $126.18 |

**Current state**: BLOCKED — $9.09–$9.41 free capital < $15.00 minimum.
−$155 on $50 capital = −310% return in 9 days.

---

## 5. Combined summary

| Bot | Period | Executors | Filled | Fill % | PnL | Capital | Return |
|-----|--------|-----------|--------|--------|-----|---------|--------|
| Kraken EUR | Nov 25 – Feb 26 | 2,209 | 34 | 1.5% | −€73.39 | €300 | −24.5% |
| Kraken USD | Jan 21–23 | 212 | 1 | 0.5% | −$0.26 | ~$300 | −0.1% |
| Bitget Spot | Jan 6–12 | 400 | 6 | 1.5% | −$0.72 | ~$100 | −0.7% |
| Bitget Futures | Feb 1–10 | 932 | 23 | 2.5% | −$155.39 | ~$50 | −310.8% |
| **Combined** | | **3,753** | **64** | **1.7%** | **≈ −€229** | | |

**Key observations**:
- Not a single bot instance is profitable
- 98.3% of all executors across all bots never get a single fill
- Futures shows highest fill rate (2.5%) but worst outcome (96% stopped out)
- Only 1 of 3 active bots can currently attempt to trade (Kraken USD)

---

## 6. Error frequency from logs

### Kraken USD
**Log**: `logs/logs_multi_coin_grid_v2_usd_2026-03-05-16-20-24.log`
**Session**: 2026-03-05 → 2026-03-08

| Level | Count |
|-------|-------|
| WARNING | 277 |
| ERROR | 225 |

**Unique errors**:
- `MQTT is already stopped!` — MQTT connection management issue
- `Unexpected error while listening to user stream. Retrying after 5 seconds...` — WebSocket instability

**WebSocket-related messages**: 336 occurrences

### Bitget Spot
**Log**: `logs/logs_spot_grid_bitget_2026-03-05-16-42-05.log`
**Session**: 2026-03-05 → 2026-03-08

| Level | Count |
|-------|-------|
| WARNING | 1,664 |
| ERROR | 368 |

**Single error (all 368 occurrences)**:
```
❌ Cannot create grid: Insufficient capital: $3.62 < $30.00 minimum (3 grids × $10)
```

### Bitget Futures
**Log**: `logs/logs_futures_grid_bitget_2026-02-28-13-34-36.log`
**Session**: 2026-02-28 → 2026-03-08

| Level | Count |
|-------|-------|
| WARNING | 37 |
| ERROR | 37 |

**Unique errors (all insufficient capital variations)**:
```
❌ Cannot create grid: Insufficient capital: $9.27 < $15.00 minimum (3 grids × $5)
❌ Cannot create grid: Insufficient capital: $9.29 < $15.00 minimum (3 grids × $5)
❌ Cannot create grid: Insufficient capital: $9.34 < $15.00 minimum (3 grids × $5)
❌ Cannot create grid: Insufficient capital: $9.41 < $15.00 minimum (3 grids × $5)
```

---

## 7. WHY-NO-TRADE summaries

### Kraken USD — 2026-03-08 (3 hourly reports)

**09:29 UTC** | 2,561 intents evaluated | 83.1% denied | 16.9% approved
| Rejection reason | Count | % of total |
|-----------------|-------|------------|
| NO_ORDERBOOK_DATA | 1,137 | 44.4% |
| RSI_OVERBOUGHT | 776 | 30.3% |
| STALE_PRICE | 157 | 6.1% |
| ATR_TOO_LOW | 35 | 1.4% |
| SPREAD_TOO_WIDE | 15 | 0.6% |
| RSI_OVERSOLD | 7 | 0.3% |

**10:30 UTC** | 1,827 intents | 57.0% denied | 43.0% approved
| Rejection reason | Count | % of total |
|-----------------|-------|------------|
| NO_ORDERBOOK_DATA | 666 | 36.5% |
| RSI_OVERBOUGHT | 265 | 14.5% |
| ATR_TOO_LOW | 93 | 5.1% |
| STALE_PRICE | 9 | 0.5% |
| RSI_OVERSOLD | 6 | 0.3% |
| SPREAD_TOO_WIDE | 2 | 0.1% |

**11:30 UTC** | 2,359 intents | 74.8% denied | 25.2% approved
| Rejection reason | Count | % of total |
|-----------------|-------|------------|
| NO_ORDERBOOK_DATA | 971 | 41.2% |
| RSI_OVERBOUGHT | 721 | 30.6% |
| STALE_PRICE | 70 | 3.0% |
| SPREAD_TOO_WIDE | 3 | 0.1% |

**Pattern**: NO_ORDERBOOK_DATA is consistently #1 (36–44%), RSI_OVERBOUGHT #2 (14–31%).

### Bitget Spot — 2026-03-05 to 2026-03-08

**20:42 (Mar 5)** | 99 intents | 70.7% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | 40 | 40.4% |
| RSI_OVERBOUGHT | 10 | 10.1% |
| ATR_TOO_LOW | 10 | 10.1% |
| ACCEL_FALLING_KNIFE | 6 | 6.1% |
| VWAP_DEVIATION_TOO_HIGH | 4 | 4.0% |

**22:42 (Mar 5)** | 1,094 intents | 52.7% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | 405 | 37.0% |
| RSI_OVERBOUGHT | 97 | 8.9% |
| ACCEL_FALLING_KNIFE | 60 | 5.5% |
| ATR_TOO_LOW | 12 | 1.1% |
| TREND_24H_OUT_OF_RANGE | 3 | 0.3% |

**10:47 (Mar 8)** | ~2,000 intents | ~70% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | ~40% | — |
| RSI_OVERBOUGHT | ~18% | — |
| ACCEL_FALLING_KNIFE | 83 | 4.0% |
| TREND_24H_OUT_OF_RANGE | 61 | 3.0% |
| SPREAD_TOO_WIDE | 37 | 1.8% |

**11:48 (Mar 8)** | 1,883 intents | 72.1% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | 746 | 39.6% |
| RSI_OVERBOUGHT | 342 | 18.2% |
| ACCEL_FALLING_KNIFE | 109 | 5.8% |
| WICK_RATIO_LOW | 65 | 3.5% |
| TREND_24H_OUT_OF_RANGE | 54 | 2.9% |
| STALE_PRICE | 35 | 1.9% |
| SPREAD_TOO_WIDE | 6 | 0.3% |

**After 12:48 (Mar 8)**: 0 intents evaluated — Bitget Spot stopped evaluating
(likely capital-blocked, no coins being monitored).

---

## 8. Rotation timeout events

### Kraken USD (current session)
| Coin | Timeouts |
|------|----------|
| SUI-USD | 2 |

### Bitget Spot (current session)
| Coin | Timeouts |
|------|----------|
| SONIC-USDT | 19 |
| HYPE-USDT | 2 |

**SONIC-USDT rotation loop**: Rotates every ~3.1 minutes without progress.
Sample (all from March 8):
```
12:08 → 12:12 → 12:15 → 12:18 → 12:21 → 12:24 → 12:28 → 12:31
→ 12:34 → 12:37 → 12:41 → 12:44 → 12:47 → 12:50 → 12:57 → 13:00
→ 13:03 → 13:07 → ...
```
19 consecutive "monitoring timeout" events for the same coin = rotation
logic doesn't detect that it keeps selecting the same stuck coin.

---

## 9. Critical observations

1. **Fill rate crisis**: 98.3% of executors never fill. This is the #1 problem.
2. **NO_ORDERBOOK_DATA**: #1 rejection reason (35–44%) across all bots. Likely a data pipeline issue, not a strategy issue.
3. **Capital adequacy**: 2 of 3 active bots cannot trade due to insufficient capital.
4. **Futures catastrophe**: −$155 on $50 capital. 96% of filled trades hit stop-loss. Grid + leverage = amplified losses.
5. **Rotation loops**: SONIC-USDT rotates 19 times without progress. The bot doesn't learn.
6. **Kraken WebSocket**: 336 WebSocket-related events in a 3-day session.
7. **Only SOL-USDT** is consistently profitable across all bots (+$9.31 futures, positive on spot).

---

## Review Rules

## Review Rules (include at bottom of every round)

```
Important rules for this review:
- Be brutally honest and specific
- Do not praise by default
- Do not give generic best-practice advice unless tied to this bot
- Every major claim must reference evidence from code, config, logs,
  database, or trade data
- Distinguish facts, inferences, and unknowns
- Prioritize recommendations by impact, urgency, and implementation effort
- Explicitly state what should be kept, what should be redesigned,
  and what should be removed
- Assume the goal is to evolve this system toward professional-grade
  live trading, not just academic correctness
- If data is missing to support a conclusion, say exactly what data
  you need rather than speculating
- Use the evidence table format for all major findings
```

---
