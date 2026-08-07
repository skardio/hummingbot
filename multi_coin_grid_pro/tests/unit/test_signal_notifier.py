# test_signal_notifier.py — unit tests voor MomentumSignalNotifier
from unittest.mock import MagicMock, patch

from multi_coin_grid_pro.signals.momentum_config import TelegramConfig
from multi_coin_grid_pro.signals.momentum_models import MomentumSignal
from multi_coin_grid_pro.signals.momentum_notifier import MomentumSignalNotifier

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(**kwargs) -> TelegramConfig:
    defaults = dict(enabled=True, bot_token="token123", chat_id="chat456", cooldown_seconds=300)
    defaults.update(kwargs)
    return TelegramConfig(**defaults)


def _signal(
    accepted: bool = True,
    pair: str = "WLD-USD",
    score: float = 0.85,
    rank: int = 1,
    price: float = 0.329,
    signal_label: str = None,
    entry_min: float = None,
    entry_max: float = None,
    max_chase_price: float = None,
    invalidation_price: float = None,
    take_profit_1: float = None,
    take_profit_2: float = None,
) -> MomentumSignal:
    return MomentumSignal(
        scan_id="abc123",
        timestamp=1748260000.0,
        exchange="kraken",
        trading_pair=pair,
        price=price,
        spread_pct=0.10,
        price_change_5m_pct=2.3,
        price_change_15m_pct=4.8,
        volume_ratio=4.9,
        score=score,
        accepted=accepted,
        rank=rank,
        signal_label=signal_label,
        entry_min=entry_min,
        entry_max=entry_max,
        max_chase_price=max_chase_price,
        invalidation_price=invalidation_price,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
    )


# ---------------------------------------------------------------------------
# ready()
# ---------------------------------------------------------------------------

class TestReady:
    def test_ready_true_with_token_and_chat_id(self):
        notifier = MomentumSignalNotifier(_cfg())
        assert notifier.ready() is True

    def test_ready_false_when_disabled(self):
        notifier = MomentumSignalNotifier(_cfg(enabled=False))
        assert notifier.ready() is False

    def test_ready_false_when_no_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        notifier = MomentumSignalNotifier(_cfg(bot_token=None))
        assert notifier.ready() is False

    def test_ready_false_when_no_chat_id(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        notifier = MomentumSignalNotifier(_cfg(chat_id=None))
        assert notifier.ready() is False

    def test_ready_reads_token_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "envtoken")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "envchat")
        notifier = MomentumSignalNotifier(_cfg(bot_token=None, chat_id=None))
        assert notifier.ready() is True
        assert notifier._token == "envtoken"
        assert notifier._chat_id == "envchat"

    def test_config_token_overrides_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "envtoken")
        notifier = MomentumSignalNotifier(_cfg(bot_token="cfgtoken"))
        assert notifier._token == "cfgtoken"


# ---------------------------------------------------------------------------
# notify_accepted() — sturen
# ---------------------------------------------------------------------------

class TestNotifyAccepted:
    def test_stuurt_bericht_voor_geaccepteerd_signaal(self):
        notifier = MomentumSignalNotifier(_cfg())
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted([_signal(accepted=True)])
        mock_send.assert_called_once()

    def test_stuurt_geen_bericht_voor_afgewezen_signaal(self):
        notifier = MomentumSignalNotifier(_cfg())
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted([_signal(accepted=False)])
        mock_send.assert_not_called()

    def test_stuurt_niet_als_not_ready(self):
        notifier = MomentumSignalNotifier(_cfg(enabled=False))
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted([_signal(accepted=True)])
        mock_send.assert_not_called()

    def test_meerdere_geaccepteerde_signalen(self):
        notifier = MomentumSignalNotifier(_cfg())
        signals = [_signal(pair="WLD-USD"), _signal(pair="RENDER-USD"), _signal(pair="FET-USD")]
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted(signals)
        assert mock_send.call_count == 3

    def test_mix_accepted_en_rejected(self):
        notifier = MomentumSignalNotifier(_cfg())
        signals = [
            _signal(pair="WLD-USD", accepted=True),
            _signal(pair="POND-USD", accepted=False),
            _signal(pair="FET-USD", accepted=True),
        ]
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted(signals)
        assert mock_send.call_count == 2

    def test_too_late_signaal_wordt_niet_gestuurd(self):
        notifier = MomentumSignalNotifier(_cfg())
        sig = _signal(accepted=True, signal_label="TOO_LATE")
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted([sig])
        mock_send.assert_not_called()

    def test_watch_signaal_wordt_gestuurd(self):
        notifier = MomentumSignalNotifier(_cfg())
        sig = _signal(accepted=True, signal_label="WATCH")
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted([sig])
        mock_send.assert_called_once()

    def test_buy_now_signaal_wordt_gestuurd(self):
        notifier = MomentumSignalNotifier(_cfg())
        sig = _signal(accepted=True, signal_label="BUY_NOW")
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted([sig])
        mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

class TestCooldown:
    def test_tweede_call_binnen_cooldown_wordt_overgeslagen(self):
        notifier = MomentumSignalNotifier(_cfg(cooldown_seconds=300))
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted([_signal(pair="WLD-USD")])
            notifier.notify_accepted([_signal(pair="WLD-USD")])  # zelfde pair, direct daarna
        assert mock_send.call_count == 1  # tweede wordt geblokkeerd

    def test_na_cooldown_wordt_opnieuw_gestuurd(self):
        notifier = MomentumSignalNotifier(_cfg(cooldown_seconds=1))
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted([_signal(pair="WLD-USD")])
            # Simuleer dat de cooldown verlopen is via de nieuwe tuple-sleutel
            key = ("kraken", "WLD-USD")
            old_ts, old_price = notifier._last_notified[key]
            notifier._last_notified[key] = (old_ts - 2, old_price)
            notifier.notify_accepted([_signal(pair="WLD-USD")])
        assert mock_send.call_count == 2

    def test_verschillende_pairs_hebben_eigen_cooldown(self):
        notifier = MomentumSignalNotifier(_cfg(cooldown_seconds=300))
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted([_signal(pair="WLD-USD")])
            notifier.notify_accepted([_signal(pair="WLD-USD")])     # geblokkeerd
            notifier.notify_accepted([_signal(pair="RENDER-USD")])  # andere pair → door
        assert mock_send.call_count == 2  # WLD eens, RENDER eens

    def test_prijsdaling_doorbreekt_cooldown(self):
        # Als prijs >= dedup_min_price_drop_pct gedaald is, mag er opnieuw gestuurd worden
        notifier = MomentumSignalNotifier(_cfg(cooldown_seconds=1200, dedup_min_price_drop_pct=1.5))
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted([_signal(pair="WLD-USD", price=1.000)])
            # Prijs gedaald van 1.000 naar 0.980 = -2.0% > 1.5% drempel
            notifier.notify_accepted([_signal(pair="WLD-USD", price=0.980)])
        assert mock_send.call_count == 2  # beide gestuurd

    def test_kleine_prijsdaling_blokkeert_cooldown(self):
        # Prijsdaling < drempel: cooldown blijft actief
        notifier = MomentumSignalNotifier(_cfg(cooldown_seconds=1200, dedup_min_price_drop_pct=1.5))
        with patch.object(notifier, "_send") as mock_send:
            notifier.notify_accepted([_signal(pair="WLD-USD", price=1.000)])
            # Prijs gedaald van 1.000 naar 0.992 = -0.8% < 1.5% drempel
            notifier.notify_accepted([_signal(pair="WLD-USD", price=0.992)])
        assert mock_send.call_count == 1  # tweede geblokkeerd


# ---------------------------------------------------------------------------
# _format()
# ---------------------------------------------------------------------------

class TestFormat:
    def test_bevat_pair_naam(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format(_signal(pair="WLD-USD"))
        assert "WLD-USD" in tekst

    def test_bevat_exchange(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format(_signal())
        assert "Kraken" in tekst

    def test_bevat_score(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format(_signal(score=0.85))
        assert "0.85" in tekst

    def test_positieve_pct_heeft_plus_teken(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format(_signal())
        assert "+2.3%" in tekst
        assert "+4.8%" in tekst

    def test_negatieve_pct_zonder_plus(self):
        notifier = MomentumSignalNotifier(_cfg())
        sig = _signal()
        sig.price_change_5m_pct = -1.5
        sig.price_change_15m_pct = -3.2
        tekst = notifier._format(sig)
        assert "-1.5%" in tekst
        assert "-3.2%" in tekst
        assert "+-" not in tekst

    def test_none_waarden_tonen_nvt(self):
        notifier = MomentumSignalNotifier(_cfg())
        sig = _signal()
        sig.price_change_5m_pct = None
        sig.volume_ratio = None
        tekst = notifier._format(sig)
        assert "n/a" in tekst

    def test_volume_ratio_ontbreekt_als_none(self):
        notifier = MomentumSignalNotifier(_cfg())
        sig = _signal()
        sig.volume_ratio = None
        tekst = notifier._format(sig)
        assert "Volume-ratio" not in tekst

    def test_volume_ratio_aanwezig_als_ingevuld(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format(_signal())
        assert "4.9" in tekst

    def test_format_dispatcht_naar_watch_zonder_label(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format(_signal(signal_label=None))
        assert "WATCH" in tekst

    def test_format_dispatcht_naar_buy_now_met_label(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format(_signal(signal_label="BUY_NOW"))
        assert "BUY NOW" in tekst

    def test_format_watch_bevat_geen_buy_now_tekst(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format_watch(_signal())
        assert "BUY NOW" not in tekst

    def test_format_buy_now_bevat_geen_watch_tekst(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format_buy_now(_signal())
        assert "WATCH" not in tekst


# ---------------------------------------------------------------------------
# _send() — HTTP call
# ---------------------------------------------------------------------------

class TestSend:
    def test_post_naar_telegram_api(self):
        notifier = MomentumSignalNotifier(_cfg(bot_token="tok", chat_id="cid"))
        mock_resp = MagicMock()
        mock_resp.ok = True
        with patch("multi_coin_grid_pro.signals.momentum_notifier.requests.post", return_value=mock_resp) as mock_post:
            notifier._send("test bericht")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "tok" in args[0]
        assert kwargs["json"]["chat_id"] == "cid"
        assert kwargs["json"]["text"] == "test bericht"
        assert kwargs["json"]["parse_mode"] == "Markdown"

    def test_http_fout_logt_warning_geen_exception(self):
        notifier = MomentumSignalNotifier(_cfg())
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 400
        mock_resp.text = "bad request"
        with patch("multi_coin_grid_pro.signals.momentum_notifier.requests.post", return_value=mock_resp):
            notifier._send("bericht")  # mag geen exception gooien

    def test_network_exception_logt_warning_geen_exception(self):
        notifier = MomentumSignalNotifier(_cfg())
        with patch(
            "multi_coin_grid_pro.signals.momentum_notifier.requests.post",
            side_effect=ConnectionError("timeout"),
        ):
            notifier._send("bericht")  # mag geen exception gooien


# ---------------------------------------------------------------------------
# _format_buy_now() — entry zone + TP (US-301)
# ---------------------------------------------------------------------------

class TestFormatBuyNow:
    def _buy_now_signal(self) -> MomentumSignal:
        return _signal(
            signal_label="BUY_NOW",
            price=1.2345,
            entry_min=1.23,
            entry_max=1.24,
            max_chase_price=1.250,
            invalidation_price=1.21,
            take_profit_1=1.255,
            take_profit_2=1.271,
        )

    def test_bevat_buy_now_header(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format_buy_now(self._buy_now_signal())
        assert "BUY NOW" in tekst

    def test_bevat_entry_zone(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format_buy_now(self._buy_now_signal())
        assert "Entry" in tekst

    def test_bevat_stop(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format_buy_now(self._buy_now_signal())
        assert "Invalidation" in tekst or "Stop" in tekst

    def test_bevat_tp1_en_tp2(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format_buy_now(self._buy_now_signal())
        assert "TP1" in tekst
        assert "TP2" in tekst

    def test_bevat_max_chase(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format_buy_now(self._buy_now_signal())
        assert "chase" in tekst.lower() or "kopen" in tekst.lower()

    def test_zonder_entry_levels_toont_geen_entry_zone(self):
        notifier = MomentumSignalNotifier(_cfg())
        sig = _signal(signal_label="BUY_NOW")  # geen entry levels
        tekst = notifier._format_buy_now(sig)
        assert "Entry" not in tekst
        assert "Stop" not in tekst

    def test_buy_now_tracking_bijwerken_na_notify(self):
        notifier = MomentumSignalNotifier(_cfg())
        sig = _signal(
            signal_label="BUY_NOW",
            max_chase_price=1.25,
            entry_min=1.23,
        )
        with patch.object(notifier, "_send"):
            notifier.notify_accepted([sig])
        key = ("kraken", "WLD-USD")
        assert key in notifier._buy_now_chase
        assert notifier._buy_now_chase[key][0] == 1.25  # max_chase_price


# ---------------------------------------------------------------------------
# check_do_not_chase() — US-206/303
# ---------------------------------------------------------------------------

class TestCheckDoNotChase:
    def test_geen_alert_als_not_ready(self):
        notifier = MomentumSignalNotifier(_cfg(enabled=False))
        notifier._buy_now_chase[("kraken", "WLD-USD")] = (1.25, 1.23)
        with patch.object(notifier, "_send") as mock_send:
            notifier.check_do_not_chase([_signal(price=1.30)])
        mock_send.assert_not_called()

    def test_geen_alert_als_prijs_onder_max_chase(self):
        notifier = MomentumSignalNotifier(_cfg())
        notifier._buy_now_chase[("kraken", "WLD-USD")] = (1.25, 1.23)
        with patch.object(notifier, "_send") as mock_send:
            notifier.check_do_not_chase([_signal(price=1.20)])  # prijs < max_chase
        mock_send.assert_not_called()

    def test_alert_als_prijs_boven_max_chase(self):
        notifier = MomentumSignalNotifier(_cfg())
        notifier._buy_now_chase[("kraken", "WLD-USD")] = (1.25, 1.23)
        with patch.object(notifier, "_send") as mock_send:
            notifier.check_do_not_chase([_signal(price=1.30)])  # prijs > max_chase
        mock_send.assert_called_once()

    def test_alert_slechts_eenmaal_per_buy_now(self):
        notifier = MomentumSignalNotifier(_cfg())
        notifier._buy_now_chase[("kraken", "WLD-USD")] = (1.25, 1.23)
        with patch.object(notifier, "_send") as mock_send:
            notifier.check_do_not_chase([_signal(price=1.30)])
            notifier.check_do_not_chase([_signal(price=1.35)])  # tweede keer zelfde pair
        mock_send.assert_called_once()  # maar eenmaal gestuurd

    def test_do_not_chase_reset_bij_nieuwe_buy_now(self):
        notifier = MomentumSignalNotifier(_cfg())
        key = ("kraken", "WLD-USD")
        notifier._buy_now_chase[key] = (1.25, 1.23)
        notifier._do_not_chase_sent.add(key)
        # Nieuw BUY_NOW signaal reset de tracking
        sig = _signal(signal_label="BUY_NOW", price=1.10, max_chase_price=1.15, entry_min=1.08)
        with patch.object(notifier, "_send"):
            notifier.notify_accepted([sig])
        assert key not in notifier._do_not_chase_sent

    def test_geen_alert_als_pair_niet_in_signals(self):
        notifier = MomentumSignalNotifier(_cfg())
        notifier._buy_now_chase[("kraken", "WLD-USD")] = (1.25, 1.23)
        other_sig = _signal(pair="BTC-USD", price=60000.0)
        with patch.object(notifier, "_send") as mock_send:
            notifier.check_do_not_chase([other_sig])  # WLD niet in scan
        mock_send.assert_not_called()

    def test_format_do_not_chase_bevat_niet_kopen(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format_do_not_chase("WLD-USD", "kraken", 1.30, 1.23, 1.25)
        assert "NIET KOPEN" in tekst

    def test_format_do_not_chase_bevat_pair(self):
        notifier = MomentumSignalNotifier(_cfg())
        tekst = notifier._format_do_not_chase("WLD-USD", "kraken", 1.30, 1.23, 1.25)
        assert "WLD-USD" in tekst
