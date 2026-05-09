#!/usr/bin/env python3
"""Analyze Kraken USD bot run from log files."""
import glob
import re
from collections import Counter

base = 'logs_multi_coin_grid_v2_usd_2026-04-29-16-43-47'
files = sorted(glob.glob(base + '.log.*'), key=lambda x: -int(x.split('.')[-1])) + [base + '.log']
print(f'Analyzing {len(files)} log files...\n')

regime_counts = Counter()
atr_updates = []
grids_created = []
fills = []
errors = []
pnl_lines = []
smartentry_rejected = Counter()
no_coin_found = 0
balance_entries = []
momentum_allowed = 0
momentum_rejected = Counter()

for fname in files:
    try:
        with open(fname, errors='replace') as f:
            for line in f:
                if 'REGIME_ROUTE' in line:
                    m = re.search(r'normalized=(\w+)', line)
                    bal = re.search(r'balance=([\d.]+)', line)
                    if m:
                        regime_counts[m.group(1)] += 1
                    if bal:
                        balance_entries.append(float(bal.group(1)))

                elif 'min_atr_pct_for_grid:' in line and '->' in line:
                    m = re.search(r'min_atr_pct_for_grid: ([\d.]+)->([\d.]+)', line)
                    if m:
                        atr_updates.append((line[:19], m.group(1), m.group(2)))

                elif ('GRID_CREATED' in line or 'Grid created' in line or
                      'grid for' in line.lower() or 'Starting grid' in line):
                    grids_created.append(line[:120])

                elif ('BUY_FILLED' in line or 'SELL_FILLED' in line or
                      'buy filled' in line.lower() or 'sell filled' in line.lower() or
                      'Order.*filled' in line or 'filled.*order' in line.lower()):
                    fills.append(line[:120])

                elif ('realized_pnl' in line or 'Realized PnL' in line or
                      'pnl' in line.lower() and 'total' in line.lower()):
                    pnl_lines.append(line[:140])

                elif 'No valid coin found' in line or 'All top coins rejected' in line:
                    no_coin_found += 1

                elif 'REJECTED by' in line and 'kraken' in line.lower():
                    m = re.search(r'REJECTED by (\w+)', line)
                    if m:
                        smartentry_rejected[m.group(1)] += 1

                elif 'MOMENTUM_CANDIDATE_ALLOWED' in line:
                    momentum_allowed += 1

                elif 'MOMENTUM_CANDIDATE_REJECTED' in line:
                    m = re.search(r'primary=(\w+)', line)
                    if m:
                        momentum_rejected[m.group(1)] += 1

                elif ' - ERROR - ' in line:
                    errors.append(line[:160])

    except Exception as e:
        print(f'Error reading {fname}: {e}')

# Results
print('=' * 60)
print('REGIME VERDELING')
print('=' * 60)
total_regime = sum(regime_counts.values())
for k, v in regime_counts.most_common():
    print(f'  {k:8}: {v:6} ticks  ({v / total_regime * 100:.1f}%)')

if balance_entries:
    print(f'\n  Balance range: ${min(balance_entries):.2f} → ${max(balance_entries):.2f}')
    print(f'  Laatste balance: ${balance_entries[-1]:.2f}')
    print(f'  Verschil (P&L proxy): ${balance_entries[-1] - balance_entries[0]:+.2f}')

print()
print('=' * 60)
print('ATR FILTER (regime-based, nieuw systeem)')
print('=' * 60)
if atr_updates:
    seen = set()
    for ts, old, new in atr_updates:
        key = f'{old}->{new}'
        if key not in seen:
            print(f'  {ts}: {old}% -> {new}%')
            seen.add(key)
else:
    print('  Geen ATR-updates gevonden in log')

print()
print('=' * 60)
print(f'GRIDS AANGEMAAKT: {len(grids_created)}')
print('=' * 60)
for g in grids_created[:20]:
    print(f'  {g.strip()[:115]}')

print()
print('=' * 60)
print(f'ORDER FILLS: {len(fills)}')
print('=' * 60)
for g in fills[:20]:
    print(f'  {g.strip()[:115]}')

print()
print('=' * 60)
print('PnL REGELS')
print('=' * 60)
seen_pnl = set()
for p in pnl_lines:
    s = p.strip()[:135]
    if s not in seen_pnl:
        print(f'  {s}')
        seen_pnl.add(s)
        if len(seen_pnl) >= 20:
            break

print()
print('=' * 60)
print('SMARTENTRY REJECT REDENEN (top 10)')
print('=' * 60)
total_se = sum(smartentry_rejected.values())
for k, v in smartentry_rejected.most_common(10):
    print(f'  {k:25}: {v:5}  ({v / total_se * 100:.1f}%)')

print()
print('=' * 60)
print('MOMENTUM SLEEVE')
print('=' * 60)
print(f'  ALLOWED: {momentum_allowed}')
print(f'  REJECTED top:')
for k, v in momentum_rejected.most_common(5):
    print(f'    {k}: {v}')

print()
print('=' * 60)
print(f'GEEN COIN GEVONDEN: {no_coin_found}x')
print('=' * 60)

print()
print('=' * 60)
print(f'ERRORS: {len(errors)}')
print('=' * 60)
seen_err = set()
for e in errors:
    key = re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+', '', e)[:100]
    if key not in seen_err:
        print(f'  {e.strip()[:155]}')
        seen_err.add(key)
        if len(seen_err) >= 20:
            break
