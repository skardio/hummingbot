#!/bin/bash
# Auto-start script met wachtwoord
# Gebruik: ./start_auto.sh

# BELANGRIJK: Verander dit wachtwoord naar jouw echte wachtwoord!
export CONFIG_PASSWORD="!Harika@4528"

# Activeer de virtual environment (indien nodig)
if [ -d ".venv" ] && [ -z "$VIRTUAL_ENV" ]; then
    source .venv/bin/activate
fi

# Start hummingbot (wachtwoord wordt automatisch uit CONFIG_PASSWORD gelezen)
./start
