"""
Flask Dashboard for Bot Monitoring

Simple web dashboard showing bot status, events, and P&L charts.
Runs on localhost:5000 by default.
"""

from datetime import datetime

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


@app.route('/health')
def health():
    """Health check endpoint for external monitoring (systemd, uptime tools)."""
    if not db:
        return jsonify({"status": "unhealthy", "reason": "database not initialized"}), 503

    status = db.get_latest_status()
    if not status:
        return jsonify({"status": "unhealthy", "reason": "no status rows"}), 503

    # Check staleness: if last status is older than 120s, bot is likely stuck
    max_age_seconds = 120
    try:
        ts = datetime.fromisoformat(status["timestamp"])
        # Timestamps from add_status() are naive local time
        age = (datetime.now() - ts).total_seconds()
    except (ValueError, KeyError):
        age = float("inf")

    healthy = age <= max_age_seconds
    return jsonify({
        "status": "healthy" if healthy else "unhealthy",
        "last_update_age_s": round(age, 1),
        "mode": status.get("mode", "unknown"),
        "connection": status.get("connection_status", "unknown"),
    }), 200 if healthy else 503


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
