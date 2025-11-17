#!/bin/bash
cd /home/mo/repos/hummingbot
export KRAKEN_API_KEY="ld98d1D80ekCuThGZvFZnPQf4yKmuflpsn3PRLOFazNw2Jd/ECFl/6Sk"
export KRAKEN_SECRET_KEY="4izpj+vDx6wmF6UelTAyVZLH3QwyyqKY3tvO7M9rrOQRjIKm6/It87aWEG/F2xTJnKU8miPn39EGCKockuG6jw=="
echo "✓ API keys exported"
~/.venvs/bot/bin/python bin/hummingbot.py
