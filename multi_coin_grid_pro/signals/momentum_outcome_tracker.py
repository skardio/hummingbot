# momentum_outcome_tracker.py — Track price outcomes for BUY_NOW, WATCH and TOO_LATE signals (US-401, US-402).
# Runs on each scan; updates signal_outcomes with current prices.
import logging
import sqlite3
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Time windows in minutes to track outcome prices
_WINDOWS = [1, 3, 5, 10, 30]

# first_hit sentinel values
_HIT_TP1 = "TP1"
_HIT_TP2 = "TP2"
_HIT_STOP = "STOP"
_HIT_TIMEOUT = "TIMEOUT"
_HIT_WIDE_TP = "WIDE_TP"

# --- Shadow-test (v5 prospectief, BUY_NOW-only, puur observationeel) -------
# WIDE_TP is GEEN strategiewijziging: CURRENT (hit_tp1/hit_tp2/hit_stop/first_hit)
# hierboven blijft volledig ongewijzigd en is de enige die live gebruikt wordt.
# WIDE_TP hergebruikt exact dezelfde entry_ref (entry_max) en dezelfde
# invalidation_price als CURRENT; alleen de TP-drempel ligt breder.
# Drempels zijn bruto prijsniveaus t.o.v. entry_max — nooit netto EV-percentages.
_WIDE_TP_PCT = 1.5          # entry_max * 1.015
_OBS_UP_PCTS = {"p07": 0.7, "p10": 1.0}    # entry_max * (1 + pct/100)
_OBS_DOWN_PCTS = {"m10": 1.0, "m15": 1.5}  # entry_max * (1 - pct/100)


class OutcomeTracker:
    """Updates ``signal_outcomes`` for BUY_NOW, WATCH and TOO_LATE signals younger than 30 min.

    One instance per service run.  Call ``update()`` after each scan with
    the current price lookup for all scanned pairs.

    BUY_NOW:  entry_price = entry_max; TP1/TP2/stop hits + first_hit volgorde tracked.
    WATCH:    entry_price = signal price; geen TP/stop levels, geen hit tracking.
    TOO_LATE: entry_price = signal price; TP1/TP2/stop hits tracked (hypothetisch).

    first_hit = welk niveau het eerst geraakt werd (TP1/TP2/STOP/TIMEOUT/NONE).
    *_hit_at_seconds = seconden na entry waarop dat niveau geraakt werd.

    Shadow-test (BUY_NOW only, puur observationeel, geen strategiewijziging):
    hit_wide_tp/wide_tp_hit_at_seconds/wide_first_hit volgen een virtuele
    TP-drempel van entry_max*1.015 met dezelfde invalidation_price als CURRENT.
    p07/p10/m10/m15_hit_at_seconds en mfe/mae_at_seconds zijn extra bruto
    prijs-tijdstippen voor latere event-volgorde-reconstructie; ze beïnvloeden
    CURRENT of WIDE_TP niet.

    DB schema (table is created if it doesn't exist):

        signal_outcomes(id, signal_id, entry_price,
                        max_price_1m … max_price_30m,
                        min_price_1m … min_price_30m,
                        hit_tp1, hit_tp2, hit_stop,
                        best_exit_pct, worst_drawdown_pct, evaluated_at,
                        first_hit, tp1_hit_at_seconds, tp2_hit_at_seconds,
                        stop_hit_at_seconds)
    """

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")

    def update(
        self,
        current_prices: Dict[Tuple[str, str], float],
        now: Optional[float] = None,
    ) -> int:
        """Update outcomes for all pending BUY_NOW, WATCH and TOO_LATE signals.

        Args:
            current_prices: {(exchange, trading_pair): current_price}
            now: injectable clock (defaults to time.time())

        Returns:
            Number of outcome rows updated.
        """
        if now is None:
            now = time.time()
        # Include up to 40-min-old signals so that signals just past the 30-min
        # boundary (e.g., service was briefly down) still get evaluated_at set.
        grace_cutoff = now - 40 * 60

        # Pending = BUY_NOW (entry_max required), WATCH or TOO_LATE (price as ref),
        # not yet fully evaluated.
        pending = self._conn.execute(
            """
            SELECT s.id, s.exchange, s.trading_pair, s.timestamp,
                   s.signal_label, s.price,
                   s.entry_max, s.invalidation_price, s.take_profit_1, s.take_profit_2
            FROM signals s
            LEFT JOIN signal_outcomes o ON o.signal_id = s.id
            WHERE s.signal_label IN ('BUY_NOW', 'WATCH', 'TOO_LATE')
              AND s.accepted = 1
              AND s.timestamp > ?
              AND (o.id IS NULL OR o.evaluated_at IS NULL)
              AND (
                  (s.signal_label = 'BUY_NOW' AND s.entry_max IS NOT NULL)
                  OR s.signal_label IN ('WATCH', 'TOO_LATE')
              )
            ORDER BY s.timestamp ASC
            """,
            (grace_cutoff,),
        ).fetchall()

        updated = 0
        for sig_id, exchange, pair, sig_ts, label, sig_price, entry_max, inv, tp1, tp2 in pending:
            price = current_prices.get((exchange, pair))
            if price is None:
                continue  # pair not scanned this round

            # BUY_NOW/TOO_LATE use entry_max (or signal price for TOO_LATE); WATCH uses signal price
            if label == "BUY_NOW":
                entry_ref = entry_max
            else:
                entry_ref = sig_price
            if entry_ref is None or entry_ref <= 0:
                continue

            age_min = (now - sig_ts) / 60.0
            age_sec = now - sig_ts

            # Get or create outcome row
            oc = self._conn.execute(
                "SELECT id, max_price_1m, max_price_3m, max_price_5m, "
                "max_price_10m, max_price_30m, "
                "min_price_1m, min_price_3m, min_price_5m, "
                "min_price_10m, min_price_30m, "
                "hit_tp1, hit_tp2, hit_stop, "
                "first_hit, tp1_hit_at_seconds, tp2_hit_at_seconds, stop_hit_at_seconds, "
                "best_exit_pct, worst_drawdown_pct, "
                "hit_wide_tp, wide_tp_hit_at_seconds, "
                "p07_hit_at_seconds, p10_hit_at_seconds, m10_hit_at_seconds, m15_hit_at_seconds, "
                "mfe_at_seconds, mae_at_seconds "
                "FROM signal_outcomes WHERE signal_id = ?",
                (sig_id,),
            ).fetchone()

            if oc is None:
                self._conn.execute(
                    "INSERT INTO signal_outcomes (signal_id, entry_price) VALUES (?,?)",
                    (sig_id, entry_ref),
                )
                self._conn.commit()
                oc = self._conn.execute(
                    "SELECT id, max_price_1m, max_price_3m, max_price_5m, "
                    "max_price_10m, max_price_30m, "
                    "min_price_1m, min_price_3m, min_price_5m, "
                    "min_price_10m, min_price_30m, "
                    "hit_tp1, hit_tp2, hit_stop, "
                    "first_hit, tp1_hit_at_seconds, tp2_hit_at_seconds, stop_hit_at_seconds, "
                    "best_exit_pct, worst_drawdown_pct, "
                    "hit_wide_tp, wide_tp_hit_at_seconds, "
                    "p07_hit_at_seconds, p10_hit_at_seconds, m10_hit_at_seconds, m15_hit_at_seconds, "
                    "mfe_at_seconds, mae_at_seconds "
                    "FROM signal_outcomes WHERE signal_id = ?",
                    (sig_id,),
                ).fetchone()

            (oid,
             mx1, mx3, mx5, mx10, mx30,
             mn1, mn3, mn5, mn10, mn30,
             ht1, ht2, hst,
             cur_first_hit, cur_tp1_secs, cur_tp2_secs, cur_stop_secs,
             cur_best_exit_pct, cur_worst_dd_pct,
             cur_hit_wide_tp, cur_wide_tp_secs,
             cur_p07_secs, cur_p10_secs, cur_m10_secs, cur_m15_secs,
             cur_mfe_secs, cur_mae_secs) = oc

            upd: dict = {}

            # Update max/min for each window that has elapsed
            window_data = [
                (1, mx1, mn1), (3, mx3, mn3), (5, mx5, mn5),
                (10, mx10, mn10), (30, mx30, mn30),
            ]
            for w, old_mx, old_mn in window_data:
                if age_min >= w:
                    upd[f"max_price_{w}m"] = max(price, old_mx) if old_mx is not None else price
                    upd[f"min_price_{w}m"] = min(price, old_mn) if old_mn is not None else price

            # TP / stop hits for BUY_NOW and TOO_LATE (WATCH has no defined levels)
            if label in ("BUY_NOW", "TOO_LATE") and tp1 is not None and inv is not None:
                if not ht1 and price >= tp1:
                    upd["hit_tp1"] = 1
                    if cur_tp1_secs is None:
                        upd["tp1_hit_at_seconds"] = age_sec
                if not ht2 and tp2 is not None and price >= tp2:
                    upd["hit_tp2"] = 1
                    if cur_tp2_secs is None:
                        upd["tp2_hit_at_seconds"] = age_sec
                if not hst and price <= inv:
                    upd["hit_stop"] = 1
                    if cur_stop_secs is None:
                        upd["stop_hit_at_seconds"] = age_sec

            # --- Shadow-test (BUY_NOW only): WIDE_TP variant + observationele drempels.
            # Puur logging op bruto prijsniveau; beïnvloedt hit_tp1/hit_tp2/hit_stop/
            # first_hit (CURRENT) hierboven op geen enkele manier.
            if label == "BUY_NOW" and entry_max is not None:
                wide_tp_price = entry_max * (1.0 + _WIDE_TP_PCT / 100.0)
                if not cur_hit_wide_tp and price >= wide_tp_price:
                    upd["hit_wide_tp"] = 1
                    if cur_wide_tp_secs is None:
                        upd["wide_tp_hit_at_seconds"] = age_sec

                obs_up_secs = {"p07": cur_p07_secs, "p10": cur_p10_secs}
                for key, pct in _OBS_UP_PCTS.items():
                    if obs_up_secs[key] is None and price >= entry_max * (1.0 + pct / 100.0):
                        upd[f"{key}_hit_at_seconds"] = age_sec

                obs_down_secs = {"m10": cur_m10_secs, "m15": cur_m15_secs}
                for key, pct in _OBS_DOWN_PCTS.items():
                    if obs_down_secs[key] is None and price <= entry_max * (1.0 - pct / 100.0):
                        upd[f"{key}_hit_at_seconds"] = age_sec

            # best/worst from all current max/min values
            all_maxes = []
            all_mins = []
            for w, old_mx, old_mn in window_data:
                cur_mx = upd.get(f"max_price_{w}m", old_mx)
                cur_mn = upd.get(f"min_price_{w}m", old_mn)
                if cur_mx is not None:
                    all_maxes.append(cur_mx)
                if cur_mn is not None:
                    all_mins.append(cur_mn)
            if all_maxes:
                upd["best_exit_pct"] = round((max(all_maxes) - entry_ref) / entry_ref * 100, 4)
            if all_mins:
                upd["worst_drawdown_pct"] = round((min(all_mins) - entry_ref) / entry_ref * 100, 4)

            # MFE/MAE timestamp: seconden waarop een NIEUW extreem werd geobserveerd
            # (puur observationeel, gebruikt dezelfde running max/min als hierboven).
            new_best = upd.get("best_exit_pct", cur_best_exit_pct)
            if new_best is not None and (cur_best_exit_pct is None or new_best > cur_best_exit_pct):
                upd["mfe_at_seconds"] = age_sec
            new_worst = upd.get("worst_drawdown_pct", cur_worst_dd_pct)
            if new_worst is not None and (cur_worst_dd_pct is None or new_worst < cur_worst_dd_pct):
                upd["mae_at_seconds"] = age_sec

            # Determine first_hit on final evaluation (30 min elapsed)
            if age_min >= 30 and cur_first_hit is None:
                # Read final hit state (merged with any updates in this tick)
                final_ht1 = upd.get("hit_tp1", ht1)
                final_ht2 = upd.get("hit_tp2", ht2)
                final_hst = upd.get("hit_stop", hst)
                final_tp1_secs = upd.get("tp1_hit_at_seconds", cur_tp1_secs)
                final_tp2_secs = upd.get("tp2_hit_at_seconds", cur_tp2_secs)
                final_stop_secs = upd.get("stop_hit_at_seconds", cur_stop_secs)

                # Determine chronological first hit
                candidates = []
                if final_ht1 and final_tp1_secs is not None:
                    candidates.append((final_tp1_secs, _HIT_TP1))
                if final_ht2 and final_tp2_secs is not None:
                    candidates.append((final_tp2_secs, _HIT_TP2))
                if final_hst and final_stop_secs is not None:
                    candidates.append((final_stop_secs, _HIT_STOP))

                if candidates:
                    # Earliest hit wins
                    upd["first_hit"] = min(candidates, key=lambda x: x[0])[1]
                elif final_ht1 or final_ht2 or final_hst:
                    # Hit detected but no timing — use priority TP1 > TP2 > STOP
                    if final_ht1:
                        upd["first_hit"] = _HIT_TP1
                    elif final_ht2:
                        upd["first_hit"] = _HIT_TP2
                    else:
                        upd["first_hit"] = _HIT_STOP
                else:
                    upd["first_hit"] = _HIT_TIMEOUT

                # time_to_first_hit_minutes: seconden → minuten vanaf signaal.
                # Use freshly updated hit-seconds when present, otherwise keep
                # existing values already stored in this outcome row.
                if upd["first_hit"] in (_HIT_TP1, _HIT_TP2, _HIT_STOP):
                    secs = (
                        upd.get("tp1_hit_at_seconds")
                        or upd.get("tp2_hit_at_seconds")
                        or upd.get("stop_hit_at_seconds")
                        or cur_tp1_secs
                        or cur_tp2_secs
                        or cur_stop_secs
                    )
                    if secs is not None:
                        upd["time_to_first_hit_minutes"] = round(secs / 60.0, 2)

                # entry_zone_reached: 1 als de minimumprijs <= entry_max (prijs daalde in entry zone)
                min_p30m = upd.get("min_price_30m") or mn30
                if min_p30m is not None and entry_max is not None:
                    upd["entry_zone_reached"] = 1 if min_p30m <= entry_max else 0

                # --- Shadow-test: wide_first_hit (BUY_NOW only) ---
                # Hergebruikt exact dezelfde final_stop_secs/final_hst als CURRENT
                # (zelfde invalidation_price) — alleen de TP-kant is anders.
                if label == "BUY_NOW":
                    final_hwide = upd.get("hit_wide_tp", cur_hit_wide_tp)
                    final_wide_secs = upd.get("wide_tp_hit_at_seconds", cur_wide_tp_secs)

                    wide_candidates = []
                    if final_hwide and final_wide_secs is not None:
                        wide_candidates.append((final_wide_secs, _HIT_WIDE_TP))
                    if final_hst and final_stop_secs is not None:
                        wide_candidates.append((final_stop_secs, _HIT_STOP))

                    if wide_candidates:
                        upd["wide_first_hit"] = min(wide_candidates, key=lambda x: x[0])[1]
                    elif final_hwide or final_hst:
                        upd["wide_first_hit"] = _HIT_WIDE_TP if final_hwide else _HIT_STOP
                    else:
                        upd["wide_first_hit"] = _HIT_TIMEOUT

                    if upd["wide_first_hit"] in (_HIT_WIDE_TP, _HIT_STOP):
                        wide_secs = (
                            upd.get("wide_tp_hit_at_seconds")
                            or upd.get("stop_hit_at_seconds")
                            or cur_wide_tp_secs
                            or cur_stop_secs
                        )
                        if wide_secs is not None:
                            upd["wide_time_to_first_hit_minutes"] = round(wide_secs / 60.0, 2)

                upd["evaluated_at"] = now

            if upd:
                set_clause = ", ".join(f"{k} = ?" for k in upd)
                vals = list(upd.values()) + [oid]
                self._conn.execute(
                    f"UPDATE signal_outcomes SET {set_clause} WHERE id = ?",  # noqa: S608
                    vals,
                )
                self._conn.commit()
                updated += 1
                logger.debug(
                    "[OUTCOME] %s:%s [%s] age=%.1fm price=%.6g → %s",
                    exchange, pair, label, age_min, price, upd,
                )

        return updated

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
