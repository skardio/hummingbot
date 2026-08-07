# momentum_notifier.py — Telegram notificaties voor geaccepteerde momentum-signalen.
# Stuurt een bericht zodra een pair de harde filter + score-grens haalt.
import datetime
import logging
import os
import time
from typing import Dict, List, Optional, Set, Tuple

import requests

from multi_coin_grid_pro.signals.momentum_config import TelegramConfig
from multi_coin_grid_pro.signals.momentum_models import MomentumSignal

logger = logging.getLogger(__name__)

_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _fp(price: float) -> str:
    """Format a price with appropriate significant digits."""
    if price <= 0:
        return str(price)
    if price < 0.001:
        return f"{price:.8g}"
    if price < 1:
        return f"{price:.6g}"
    if price < 10_000:
        return f"{price:.5g}"
    return f"{price:,.0f}"


class MomentumSignalNotifier:
    """Stuurt Telegram-berichten voor geaccepteerde momentum-signalen.

    * Leest token/chat_id uit config; valt terug op env-vars
      ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``.
    * Heeft een per-pair cooldown zodat dezelfde coin niet elke minuut
      een bericht stuurt.
    """

    def __init__(self, config: TelegramConfig) -> None:
        self._config = config
        self._token: Optional[str] = config.bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self._chat_id: Optional[str] = config.chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        # key: (exchange, pair) → (last_sent_timestamp, last_sent_price)
        self._last_notified: Dict[Tuple[str, str], Tuple[float, float]] = {}
        # DO_NOT_CHASE tracking: key: (exchange, pair) → (max_chase_price, entry_min)
        self._buy_now_chase: Dict[Tuple[str, str], Tuple[float, float]] = {}
        # Set of keys for which DO_NOT_CHASE has already been sent this session
        self._do_not_chase_sent: Set[Tuple[str, str]] = set()

    def ready(self) -> bool:
        """True als Telegram geconfigureerd en enabled is."""
        return bool(self._config.enabled and self._token and self._chat_id)

    def notify_accepted(self, signals: List[MomentumSignal]) -> None:
        """Send Telegram for BUY_NOW and WATCH signals (US-201); suppress TOO_LATE.

        Deduplication (US-104): suppresses repeated alerts for the same
        (exchange, pair) within cooldown_seconds.  Exception: if the price
        has dropped ≥ dedup_min_price_drop_pct since the last alert, a new
        alert is allowed regardless of cooldown.
        """
        if not self.ready():
            return
        now = time.time()
        for signal in signals:
            if not signal.accepted:
                continue
            if signal.signal_label == "TOO_LATE":
                continue
            key = (signal.exchange, signal.trading_pair)
            last_ts, last_price = self._last_notified.get(key, (0.0, 0.0))
            if now - last_ts < self._config.cooldown_seconds:
                # Price-drop exception: allow if price fell >= threshold
                price_drop_ok = (
                    last_price > 0
                    and (last_price - signal.price) / last_price * 100.0
                    >= self._config.dedup_min_price_drop_pct
                )
                if not price_drop_ok:
                    logger.debug(
                        "[NOTIFY] %s: cooldown actief (%.0fs resterend)",
                        signal.trading_pair,
                        self._config.cooldown_seconds - (now - last_ts),
                    )
                    continue
            text = self._format(signal)
            self._send(text)
            self._last_notified[key] = (now, signal.price)
            # Track BUY_NOW signals for DO_NOT_CHASE (US-206)
            if signal.signal_label == "BUY_NOW" and signal.max_chase_price:
                self._buy_now_chase[key] = (signal.max_chase_price, signal.entry_min or 0.0)
                self._do_not_chase_sent.discard(key)  # reset on new BUY_NOW

    def check_do_not_chase(
        self,
        signals: List[MomentumSignal],
    ) -> None:
        """Send DO_NOT_CHASE alert if price exceeded max_chase_price (US-206/303).

        Called once per scan with all signals (accepted + rejected) so we can
        look up the current price of any previously-alerted BUY_NOW pair.
        """
        if not self.ready():
            return
        current_prices = {(s.exchange, s.trading_pair): s.price for s in signals}
        for key, (max_chase, entry_min) in list(self._buy_now_chase.items()):
            if key in self._do_not_chase_sent:
                continue
            current_price = current_prices.get(key)
            if current_price is None:
                continue
            if current_price > max_chase:
                exchange, pair = key
                text = self._format_do_not_chase(
                    pair, exchange, current_price, entry_min, max_chase
                )
                self._send(text)
                self._do_not_chase_sent.add(key)
                logger.info(
                    "[NOTIFY] DO_NOT_CHASE gestuurd voor %s @ %s (prijs=%.6g > max_chase=%.6g)",
                    pair, exchange, current_price, max_chase,
                )

    def _format(self, s: MomentumSignal) -> str:
        """Dispatch to BUY_NOW or WATCH format based on signal_label."""
        if s.signal_label == "BUY_NOW":
            return self._format_buy_now(s)
        return self._format_watch(s)

    def _format_watch(self, s: MomentumSignal) -> str:
        ts = datetime.datetime.fromtimestamp(s.timestamp).strftime("%d %b %H:%M")

        def fmt_pct(v: Optional[float]) -> str:
            if v is None:
                return "n/a"
            return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

        lines = [
            "\U0001f7e1 *WATCH: " + s.trading_pair + "*",
            "_Early momentum detected_",
            "",
            f"Prijs: `{_fp(s.price)}`  Score: `{s.score:.2f}`",
            f"\u039b3m: `{fmt_pct(s.price_change_3m_pct)}`  "
            f"\u039b5m: `{fmt_pct(s.price_change_5m_pct)}`  "
            f"\u039b15m: `{fmt_pct(s.price_change_15m_pct)}`",
        ]
        if s.volume_ratio is not None:
            lines.append(
                f"VolR: `{s.volume_ratio:.1f}\u00d7`  "
                f"Spread: `{s.spread_pct:.2f}%`"
            )
        lines.append("")
        lines.append("*Plan:*")
        lines.append("\u2022 Handmatig beoordelen")
        lines.append("\u2022 Instappen bij continuation of gezonde pullback")
        lines.append("\u2022 Niet najagen als prijs te snel doorloopt")
        if s.invalidation_price is not None:
            lines.append(f"\u2022 Ongeldig onder: `{_fp(s.invalidation_price)}`")
        if s.max_chase_price is not None:
            lines.append(f"\u2022 Niet kopen boven: `{_fp(s.max_chase_price)}`")
        lines.extend(["", f"_{ts} @ {s.exchange.capitalize()}_"])
        return "\n".join(lines)

    def _format_buy_now(self, s: MomentumSignal) -> str:
        """Full BUY NOW message with entry zone, stop and TP (US-301)."""
        ts = datetime.datetime.fromtimestamp(s.timestamp).strftime("%d %b %H:%M")

        def fmt_pct(v: Optional[float]) -> str:
            if v is None:
                return "n/a"
            return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

        lines = [
            "\U0001f7e2 *BUY NOW: " + s.trading_pair + "*",
            "_Momentum confirmed, not extended_",
            "",
            f"Prijs: `{_fp(s.price)}`  Score: `{s.score:.2f}`",
            f"\u039b3m: `{fmt_pct(s.price_change_3m_pct)}`  "
            f"\u039b5m: `{fmt_pct(s.price_change_5m_pct)}`  "
            f"\u039b15m: `{fmt_pct(s.price_change_15m_pct)}`",
        ]
        if s.volume_ratio is not None:
            lines.append(
                f"VolR: `{s.volume_ratio:.1f}\u00d7`  Spread: `{s.spread_pct:.2f}%`"
            )
        if s.acceleration_score is not None:
            lines.append(f"Accel: `{s.acceleration_score:.1f}`")

        # Entry zone
        if s.entry_min is not None and s.entry_max is not None:
            lines.append("")
            lines.append("*Entry zone:*")
            lines.append(f"`{_fp(s.entry_min)}` \u2013 `{_fp(s.entry_max)}`")

        # Invalidation
        if s.invalidation_price is not None:
            lines.append("")
            lines.append("*Invalidation:*")
            stop_pct = (s.invalidation_price - (s.entry_min or s.price)) / (s.entry_min or s.price) * 100
            lines.append(f"`{_fp(s.invalidation_price)}`  `({stop_pct:+.1f}%)`")

        # Take profit
        if s.take_profit_1 is not None or s.take_profit_2 is not None:
            lines.append("")
            lines.append("*Take profit:*")
            if s.take_profit_1 is not None and s.entry_max is not None:
                tp1_pct = (s.take_profit_1 - s.entry_max) / s.entry_max * 100
                lines.append(f"TP1: `{_fp(s.take_profit_1)}`  `({tp1_pct:+.1f}%)`")
            if s.take_profit_2 is not None and s.entry_max is not None:
                tp2_pct = (s.take_profit_2 - s.entry_max) / s.entry_max * 100
                lines.append(f"TP2: `{_fp(s.take_profit_2)}`  `({tp2_pct:+.1f}%)`")

        # Max chase
        if s.max_chase_price is not None:
            lines.append("")
            lines.append("*Niet kopen boven:*")
            lines.append(f"`{_fp(s.max_chase_price)}`")

        lines.extend(["", f"_{ts} @ {s.exchange.capitalize()}_"])
        return "\n".join(lines)

    def _format_do_not_chase(
        self,
        pair: str,
        exchange: str,
        current_price: float,
        entry_min: float,
        max_chase_price: float,
    ) -> str:
        """DO_NOT_CHASE alert (US-303)."""
        lines = [
            "\U0001f534 *NIET KOPEN*",
            "",
            f"*{pair}* @ {exchange.capitalize()}",
            "",
            f"Prijs nu:   `{_fp(current_price)}`",
            f"Max chase:  `{_fp(max_chase_price)}`",
        ]
        if entry_min > 0:
            lines.append(f"Was entry:  `{_fp(entry_min)}`")
            lines.append(f"\nTe duur. Wacht op terugval naar `{_fp(entry_min)}`")
        else:
            lines.append("\nTe duur. Wacht op pullback.")
        return "\n".join(lines)

    def _send(self, text: str) -> None:
        url = _SEND_URL.format(token=self._token)
        try:
            resp = requests.post(
                url,
                json={"chat_id": self._chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=5,
            )
            if resp.ok:
                logger.info("[NOTIFY] Telegram bericht verstuurd.")
            else:
                logger.warning(
                    "[NOTIFY] Telegram send mislukt (%s): %s",
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception as exc:
            logger.warning("[NOTIFY] Telegram send error: %s", exc)

    def send_heartbeat(
        self,
        n_buy_now: int,
        n_watch: int,
        n_scans: int,
        interval_label: str = "uur",
    ) -> None:
        """Send periodic heartbeat: 'Service actief. Afgelopen uur: X signalen.' (US-HB)."""
        if not self.ready():
            return
        ts = datetime.datetime.now().strftime("%d %b %H:%M")
        lines = [
            "\U0001f493 *Service actief*",
            "",
            f"Afgelopen {interval_label}:",
            f"  BUY NOW:  `{n_buy_now}`",
            f"  WATCH:    `{n_watch}`",
            f"  Scans:    `{n_scans}`",
            "",
            f"_{ts}_",
        ]
        self._send("\n".join(lines))
