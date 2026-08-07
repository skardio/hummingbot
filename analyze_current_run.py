#!/usr/bin/env python3
"""Comprehensive analysis of current USD bot trading run."""
import glob
import json
from collections import defaultdict
from datetime import datetime


def parse_fills(log_files):
    fills = []
    for lf in log_files:
        try:
            with open(lf) as f:
                for line in f:
                    if 'OrderFilledEvent' in line:
                        try:
                            idx = line.index('{')
                            data = json.loads(line[idx:].strip())
                            trade_type = str(data.get('trade_type', ''))
                            side = 'BUY' if 'BUY' in trade_type.upper() else 'SELL'
                            # Parse actual fees
                            fee_amt = 0.0
                            tf = data.get('trade_fee', {})
                            if isinstance(tf, dict):
                                for ff in tf.get('flat_fees', []):
                                    if isinstance(ff, dict):
                                        fee_amt += float(ff.get('amount', 0))
                            fills.append({
                                'ts': data['timestamp'],
                                'pair': data['trading_pair'],
                                'side': side,
                                'price': float(data['price']),
                                'amount': float(data['amount']),
                                'fee': fee_amt,
                            })
                        except Exception:
                            pass
        except Exception:
            pass
    fills.sort(key=lambda x: x['ts'])
    return fills


def parse_events(log_files):
    """Count key events."""
    counts = defaultdict(int)
    risk_blocks = []
    grid_starts = []
    for lf in log_files:
        try:
            with open(lf) as f:
                for line in f:
                    if 'STARTING new grid' in line:
                        counts['grid_starts'] += 1
                        pair = line.split('STARTING new grid on ')[-1].strip() if 'STARTING new grid on' in line else '?'
                        grid_starts.append({'line': line[:19], 'pair': pair})
                    if 'Risk Manager blocked' in line:
                        counts['risk_blocks'] += 1
                        risk_blocks.append(line.strip())
                    if 'BUY APPROVED' in line:
                        counts['buy_approved'] += 1
                    if '_should_create_new_grid returned False' in line:
                        counts['no_new_grid'] += 1
                    if 'rejected by multi-timeframe' in line:
                        counts['mtf_rejected'] += 1
                    if '1h trend too weak' in line:
                        counts['1h_weak'] += 1
                    if 'cooldown' in line.lower() or 'Paused' in line:
                        counts['cooldown'] += 1
                    if 'BuyOrderCreatedEvent' in line:
                        counts['buy_orders'] += 1
                    if 'SellOrderCreatedEvent' in line:
                        counts['sell_orders'] += 1
                    if 'OrderCancelledEvent' in line:
                        counts['cancels'] += 1
                    if 'MarketOrderFailureEvent' in line:
                        counts['failures'] += 1
                    if 'NO_FILL' in line and 'timeout' in line.lower():
                        counts['no_fill_timeout'] += 1
                    if 'NO_PROGRESS' in line:
                        counts['no_progress_timeout'] += 1
                    if 'does not meet multi-timeframe' in line:
                        counts['mtf_fail'] += 1
                    if 'grid_executor' in line and 'INFO' in line and 'timeout check' in line:
                        counts['timeout_checks'] += 1
        except Exception:
            pass
    return counts, risk_blocks, grid_starts


def group_trades(fills):
    """Group fills into trade sessions per pair."""
    pair_sessions = defaultdict(list)
    current_session = {}

    for f in fills:
        pair = f['pair']
        if pair not in current_session:
            current_session[pair] = {'buys': [], 'sells': []}

        session = current_session[pair]
        if f['side'] == 'BUY':
            if session['sells']:
                pair_sessions[pair].append(session)
                current_session[pair] = {'buys': [f], 'sells': []}
            else:
                session['buys'].append(f)
        else:
            session['sells'].append(f)

    for pair, session in current_session.items():
        if session['buys'] or session['sells']:
            pair_sessions[pair].append(session)

    return pair_sessions


def analyze_trade(session):
    """Analyze a single trade session."""
    buy_cost = sum(f['price'] * f['amount'] for f in session['buys'])
    buy_qty = sum(f['amount'] for f in session['buys'])
    sell_revenue = sum(f['price'] * f['amount'] for f in session['sells'])
    sell_qty = sum(f['amount'] for f in session['sells'])

    avg_buy = buy_cost / buy_qty if buy_qty > 0 else 0
    avg_sell = sell_revenue / sell_qty if sell_qty > 0 else 0

    # Use actual fees from exchange
    actual_buy_fees = sum(f['fee'] for f in session['buys'])
    actual_sell_fees = sum(f['fee'] for f in session['sells'])
    est_total_fees = actual_buy_fees + actual_sell_fees

    if sell_qty > 0 and buy_qty > 0:
        fraction_sold = sell_qty / buy_qty
        gross_pnl = sell_revenue - buy_cost * fraction_sold
        net_pnl = gross_pnl - est_total_fees
        status = "CLOSED" if abs(fraction_sold - 1.0) < 0.01 else f"PARTIAL ({fraction_sold:.0%})"
    else:
        gross_pnl = 0
        net_pnl = -actual_buy_fees
        status = "OPEN"

    duration = 0
    if session['buys'] and session['sells']:
        duration = (session['sells'][-1]['ts'] - session['buys'][0]['ts']) / 60

    return {
        'buy_cost': buy_cost, 'buy_qty': buy_qty,
        'sell_revenue': sell_revenue, 'sell_qty': sell_qty,
        'avg_buy': avg_buy, 'avg_sell': avg_sell,
        'gross_pnl': gross_pnl, 'net_pnl': net_pnl,
        'est_fees': est_total_fees,
        'status': status, 'duration': duration,
        'n_buys': len(session['buys']), 'n_sells': len(session['sells']),
        'start_ts': session['buys'][0]['ts'] if session['buys'] else 0,
        'end_ts': session['sells'][-1]['ts'] if session['sells'] else 0,
    }


def main():
    # Find all log files for current USD bot session
    usd_logs = sorted(glob.glob('/home/mo/repos/hummingbot/logs/logs_multi_coin_grid_v2_usd_2026-05-18-23-33-19.log*'))
    eur_logs = sorted(glob.glob('/home/mo/repos/hummingbot/logs/logs_multi_coin_grid_v2_2026-04-02-06-52-05.log*'))

    print("=" * 100)
    print("PROFESSIONELE TRADING ANALYSE - USD BOT (Kraken)")
    print(f"Run gestart: 2026-04-02 22:12 | Analyse op: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 100)

    # Parse USD fills
    fills = parse_fills(usd_logs)
    counts, risk_blocks, grid_starts = parse_events(usd_logs)

    print(f"\n📊 LOG STATISTIEKEN (USD bot)")
    print(f"  Log files: {len(usd_logs)}")
    print(f"  Grid starts: {counts.get('grid_starts', 0)}")
    print(f"  Buy orders placed: {counts.get('buy_orders', 0)}")
    print(f"  Sell orders placed: {counts.get('sell_orders', 0)}")
    print(f"  Fills: {len(fills)} (BUY: {sum(1 for f in fills if f['side'] == 'BUY')}, SELL: {sum(1 for f in fills if f['side'] == 'SELL')})")
    print(f"  Cancels: {counts.get('cancels', 0)}")
    print(f"  Order failures: {counts.get('failures', 0)}")
    print(f"  Risk blocks: {counts.get('risk_blocks', 0)}")
    print(f"  'BUY APPROVED': {counts.get('buy_approved', 0)}")
    print(f"  '_should_create_new_grid False': {counts.get('no_new_grid', 0)}")
    print(f"  MTF rejected: {counts.get('mtf_rejected', 0)}")
    print(f"  1h trend too weak: {counts.get('1h_weak', 0)}")
    print(f"  Cooldown/Paused: {counts.get('cooldown', 0)}")
    print(f"  MTF fail (retry): {counts.get('mtf_fail', 0)}")

    # Fill rate
    if counts.get('buy_orders', 0) > 0:
        buy_fill_rate = sum(1 for f in fills if f['side'] == 'BUY') / counts['buy_orders'] * 100
        print(f"\n  Buy fill rate: {buy_fill_rate:.0f}% ({sum(1 for f in fills if f['side'] == 'BUY')}/{counts['buy_orders']})")
    if counts.get('sell_orders', 0) > 0:
        sell_fill_rate = sum(1 for f in fills if f['side'] == 'SELL') / counts['sell_orders'] * 100
        print(f"  Sell fill rate: {sell_fill_rate:.0f}% ({sum(1 for f in fills if f['side'] == 'SELL')}/{counts['sell_orders']})")

    # Trade analysis
    pair_sessions = group_trades(fills)

    print("\n" + "=" * 100)
    print("TRADE-BY-TRADE ANALYSE")
    print("=" * 100)

    all_trades = []
    for pair in sorted(pair_sessions.keys()):
        for i, session in enumerate(pair_sessions[pair]):
            analysis = analyze_trade(session)
            analysis['pair'] = pair
            analysis['session_idx'] = i + 1
            all_trades.append(analysis)

            start = datetime.fromtimestamp(analysis['start_ts']).strftime('%m-%d %H:%M') if analysis['start_ts'] else '?'
            end = datetime.fromtimestamp(analysis['end_ts']).strftime('%m-%d %H:%M') if analysis['end_ts'] else '?'

            result_emoji = "✅" if analysis['net_pnl'] > 0 else "❌"
            print(f"\n{result_emoji} {pair} #{i + 1} [{analysis['status']}] {start} → {end} ({analysis['duration']:.0f}m)")
            print(f"   Buys:  {analysis['n_buys']}x | cost=${analysis['buy_cost']:.2f} | avg=${analysis['avg_buy']:.5f}")
            if analysis['n_sells'] > 0:
                print(f"   Sells: {analysis['n_sells']}x | rev=${analysis['sell_revenue']:.2f} | avg=${analysis['avg_sell']:.5f}")
                price_move = (analysis['avg_sell'] - analysis['avg_buy']) / analysis['avg_buy'] * 100 if analysis['avg_buy'] > 0 else 0
                print(f"   Prijsbeweging: {price_move:+.3f}%")
                print(f"   Bruto PnL: ${analysis['gross_pnl']:+.4f}")
            print(f"   Fees (werkelijk): ${analysis['est_fees']:.4f}")
            if analysis['buy_cost'] > 0:
                fee_pct = analysis['est_fees'] / analysis['buy_cost'] * 100
                print(f"   Fee %% van notional: {fee_pct:.3f}%")
            print(f"   Netto PnL: ${analysis['net_pnl']:+.4f}")

    # Summary
    closed = [t for t in all_trades if 'CLOSED' in t['status'] or 'PARTIAL' in t['status']]
    open_trades = [t for t in all_trades if t['status'] == 'OPEN']
    winners = [t for t in closed if t['net_pnl'] > 0]
    losers = [t for t in closed if t['net_pnl'] <= 0]

    print("\n" + "=" * 100)
    print("SAMENVATTING")
    print("=" * 100)

    total_net = sum(t['net_pnl'] for t in all_trades)
    total_gross = sum(t['gross_pnl'] for t in closed)
    total_fees = sum(t['est_fees'] for t in all_trades)
    total_volume = sum(t['buy_cost'] for t in all_trades) + sum(t['sell_revenue'] for t in all_trades)

    print(f"\n  Totaal trades: {len(all_trades)} ({len(closed)} gesloten, {len(open_trades)} open)")
    print(f"  Winners: {len(winners)} | Losers: {len(losers)}")
    if closed:
        print(f"  Win rate: {len(winners) / len(closed) * 100:.1f}%")
    print(f"  Bruto PnL: ${total_gross:+.4f}")
    print(f"  Geschatte fees: ${total_fees:.4f}")
    print(f"  Netto PnL: ${total_net:+.4f}")
    print(f"  Totaal volume: ${total_volume:.2f}")
    if total_volume > 0:
        print(f"  Fee/volume ratio: {total_fees / total_volume * 100:.3f}%")

    if winners:
        print(f"\n  Gem. winner: ${sum(t['net_pnl'] for t in winners) / len(winners):.4f}")
    if losers:
        print(f"  Gem. loser: ${sum(t['net_pnl'] for t in losers) / len(losers):.4f}")

    if closed:
        avg_dur = sum(t['duration'] for t in closed) / len(closed)
        print(f"  Gem. hold time (gesloten): {avg_dur:.0f} min")

    # Risk blocks breakdown
    print("\n" + "=" * 100)
    print("RISK MANAGER BLOCKS")
    print("=" * 100)
    block_reasons = defaultdict(int)
    for rb in risk_blocks:
        if 'Win rate + PnL both negative' in rb:
            block_reasons['Win rate + PnL negative'] += 1
        elif 'cooldown' in rb.lower():
            block_reasons['Cooldown'] += 1
        elif 'max_exposure' in rb.lower():
            block_reasons['Max exposure'] += 1
        else:
            block_reasons['Other'] += 1
    for reason, count in sorted(block_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    # Grid starts per pair
    print("\n" + "=" * 100)
    print("GRID STARTS PER PAIR")
    print("=" * 100)
    pair_grid_counts = defaultdict(int)
    for gs in grid_starts:
        pair_grid_counts[gs['pair']] += 1
    for pair, count in sorted(pair_grid_counts.items(), key=lambda x: -x[1]):
        print(f"  {pair}: {count}")

    # EUR bot analysis
    print("\n" + "=" * 100)
    print("EUR BOT ANALYSE")
    print("=" * 100)
    eur_fills = parse_fills(eur_logs)
    eur_counts, eur_risk_blocks, eur_grid_starts = parse_events(eur_logs)
    print(f"  Grid starts: {eur_counts.get('grid_starts', 0)}")
    print(f"  Buy orders: {eur_counts.get('buy_orders', 0)}")
    print(f"  Sell orders: {eur_counts.get('sell_orders', 0)}")
    print(f"  Fills: {len(eur_fills)}")
    print(f"  Risk blocks: {eur_counts.get('risk_blocks', 0)}")

    if eur_fills:
        eur_pair_sessions = group_trades(eur_fills)
        eur_trades = []
        for pair in sorted(eur_pair_sessions.keys()):
            for i, session in enumerate(eur_pair_sessions[pair]):
                analysis = analyze_trade(session)
                analysis['pair'] = pair
                eur_trades.append(analysis)
        eur_closed = [t for t in eur_trades if 'CLOSED' in t['status']]
        eur_total = sum(t['net_pnl'] for t in eur_trades)
        print(f"  EUR trades: {len(eur_trades)} ({len(eur_closed)} closed)")
        print(f"  EUR netto PnL: ${eur_total:+.4f}")


if __name__ == '__main__':
    main()
