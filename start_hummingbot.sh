#!/bin/bash
# Hummingbot launcher with python3

cd /home/mo/repos/hummingbot
exec ~/.venvs/bot/bin/python bin/hummingbot.py "$@"
