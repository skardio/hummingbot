# systemd Service Files for Hummingbot Bot Instances

## Installation

```bash
# Copy service file(s) to systemd
sudo cp deploy/systemd/bot-kraken-usd.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable bot-kraken-usd

# Start the service
sudo systemctl start bot-kraken-usd
```

## Commands

```bash
# Check status
sudo systemctl status bot-kraken-usd

# View logs
journalctl -u bot-kraken-usd -f

# Stop (manual only — never automated)
sudo systemctl stop bot-kraken-usd

# Restart
sudo systemctl restart bot-kraken-usd
```

## Configuration

- **Restart=always**: Auto-restart on crash with 10s delay
- **WatchdogSec=120**: systemd kills the process if it's unresponsive for 120s
- **EnvironmentFile**: Loads API keys from `.env`
- **Security hardening**: `NoNewPrivileges`, `ProtectSystem=strict`

## Notes

- The service runs hummingbot CLI which loads the strategy script
- The hummingbot instance selects the script via its internal config
- To add more instances (EUR, Bitget), duplicate the service file and adjust
  `Description`, `SyslogIdentifier`, and any env vars needed
