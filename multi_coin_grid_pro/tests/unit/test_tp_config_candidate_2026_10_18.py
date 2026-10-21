"""TP-config testkandidaat 2026-10-18 — validatie vóór enige paper-test.

Valideert de voorgestelde Kraken USD TP-configuratie:
    dynamic_tp_min_pct : 0.025 -> 0.012
    dynamic_tp_max_pct : 0.05  -> 0.012
    min_grid_profit_pct: 2.0   -> 2.5

Doelstelling zoals opgegeven:
  * per-level TP effectief 1.2%, tenzij de grid-step hoger is
  * globale TP blijft 2.5% netto
  * stop-loss, trailing stop, US-005 PROFIT_LOCK en emergency exits ongewijzigd

Deze tests draaien de ECHTE ``GridExecutor._generate_grid_levels()`` met de
ECHTE, uit de productiedatabase gelezen executor-configwaarden — géén
handmatig nagebouwde formule. Dat is precies hoe de belangrijkste bevinding
boven water kwam: de ``max(self.step, dynamic_tp)``-vloer in
grid_executor.py:679 bindt, waardoor de per-level TP op de grid-step
(1.7-1.8%) uitkomt in plaats van op de geconfigureerde 1.2%.
"""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor

# Empirisch gemeten Kraken-fee per fill (zie fee-correctie 2026-10-17).
FEE_PER_FILL = Decimal("0.0030")
# Waargenomen volatility-waarde uit productie (procentpunten — zie unitbug-test).
PROD_ATR_PCT = 0.6997

CURRENT = {"dynamic_tp_min_pct": 0.025, "dynamic_tp_max_pct": 0.05}
CANDIDATE = {"dynamic_tp_min_pct": 0.012, "dynamic_tp_max_pct": 0.012}


def _build_executor(*, start_price, end_price, total_amount_quote, tick,
                    dynamic_tp_min_pct, dynamic_tp_max_pct,
                    min_order_amount_quote="15",
                    min_spread_between_orders="0.0085", coerce_tp_to_step=False):
    """Echte GridExecutor met de productie-configvelden uit de DB."""
    ex = GridExecutor.__new__(GridExecutor)
    cfg = MagicMock()
    cfg.id = "tp-test"
    cfg.connector_name = "kraken"
    cfg.trading_pair = "TEST-USD"
    cfg.start_price = Decimal(str(start_price))
    cfg.end_price = Decimal(str(end_price))
    cfg.total_amount_quote = Decimal(str(total_amount_quote))
    cfg.min_order_amount_quote = Decimal(str(min_order_amount_quote))
    cfg.min_spread_between_orders = Decimal(str(min_spread_between_orders))
    cfg.side = TradeType.BUY
    cfg.coerce_tp_to_step = coerce_tp_to_step
    cfg.activation_bounds = Decimal("0.075")

    tb = MagicMock()
    tb.take_profit = Decimal("0.075")
    tb.open_order_type = OrderType.LIMIT_MAKER
    tb.take_profit_order_type = OrderType.LIMIT_MAKER
    cfg.triple_barrier_config = tb

    cfg.custom_info = {
        "dynamic_tp_enabled": True,
        "atr_pct": PROD_ATR_PCT,
        "dynamic_tp_atr_multiplier": 0.60,
        "dynamic_tp_min_pct": dynamic_tp_min_pct,
        "dynamic_tp_max_pct": dynamic_tp_max_pct,
    }
    ex.config = cfg

    rules = MagicMock()
    rules.min_notional_size = Decimal("5")
    rules.min_base_amount_increment = Decimal("0.00000001")
    rules.min_price_increment = Decimal(str(tick))
    ex.trading_rules = rules

    ex.connectors = {"kraken": MagicMock()}
    ex.logger = MagicMock(return_value=MagicMock())
    ex.get_price = MagicMock(return_value=(cfg.start_price + cfg.end_price) / 2)
    return ex


def _required_global_tp(dynamic_tp_min_pct, min_grid_profit_pct, fee_aware_min_net_profit_pct):
    """Roept de ECHTE _required_take_profit_net_pct() aan."""
    ex = GridExecutor.__new__(GridExecutor)
    cfg = MagicMock()
    cfg.custom_info = {
        "dynamic_tp_enabled": True,
        "dynamic_tp_min_pct": dynamic_tp_min_pct,
        "min_grid_profit_pct": min_grid_profit_pct,
        "fee_aware_min_net_profit_pct": fee_aware_min_net_profit_pct,
    }
    ex.config = cfg
    return ex._required_take_profit_net_pct()


# --- Punt 1: eenheden en volgorde van de TP-configvelden -------------------

def test_fraction_and_percent_config_helpers_use_different_units():
    """dynamic_tp_min_pct is een FRACTIE, min_grid_profit_pct PROCENTPUNTEN.

    Deze asymmetrie is de reden dat 0.012 en 2.5 beide '1.2%' resp. '2.5%'
    betekenen; verwisseling zou een factor 100 schelen.
    """
    ex = GridExecutor.__new__(GridExecutor)
    assert ex._fraction_from_config(0.012) == Decimal("0.012")      # fractie, ongedeeld
    assert ex._percent_from_config(2.5) == Decimal("2.5") / Decimal("100")  # /100


def test_candidate_keeps_global_tp_at_exactly_2_5_percent():
    """Kernvereiste: min_grid_profit_pct 2.5 houdt de globale TP op 2.5% netto."""
    got = _required_global_tp(
        dynamic_tp_min_pct=CANDIDATE["dynamic_tp_min_pct"],
        min_grid_profit_pct=2.5,
        fee_aware_min_net_profit_pct=0.3,
    )
    assert got == Decimal("0.025"), f"globale TP moet 2.5% zijn, is {got}"


def test_without_raising_min_grid_profit_the_global_tp_would_drop():
    """Bewijst dat de derde wijziging noodzakelijk is: zonder 2.0->2.5 zakt de
    globale TP naar 2.0% omdat dynamic_tp_min_pct (de oude 2.5%-vloer) wegvalt."""
    got = _required_global_tp(
        dynamic_tp_min_pct=CANDIDATE["dynamic_tp_min_pct"],
        min_grid_profit_pct=2.0,
        fee_aware_min_net_profit_pct=0.3,
    )
    assert got == Decimal("0.02")


def test_current_config_global_tp_is_also_2_5_percent():
    """Baseline: de huidige config levert eveneens 2.5% globale TP."""
    got = _required_global_tp(
        dynamic_tp_min_pct=CURRENT["dynamic_tp_min_pct"],
        min_grid_profit_pct=2.0,
        fee_aware_min_net_profit_pct=0.3,
    )
    assert got == Decimal("0.025")


# --- Punt 2: per-level TP voor de 11 historische grids ---------------------

# (naam, start_price, end_price, total_amount_quote, min_price_increment)
HISTORICAL_GRIDS = [
    ("CT", 0.38677857, 0.39853429, 67.03166250, "0.00001"),
    ("GNOT", 0.07354947, 0.07481053, 66.69207000, "0.000001"),
    ("PYTH1", 0.08549571, 0.08698886, 66.35907000, "0.000001"),
    ("NIL1", 0.08688571, 0.09056286, 66.01403250, "0.00001"),
    ("PYTH2", 0.08661744, 0.08810256, 65.71644750, "0.000001"),
    ("NIL2", 0.08655795, 0.08804205, 65.37611250, "0.00001"),
    ("US", 0.00723571, 0.00748086, 65.18058750, "0.0000001"),
    ("TIA", 0.69147210, 0.70332790, 50.61891596, "0.00001"),
    ("BAT", 0.20123484, 0.20468516, 39.23741250, "0.000001"),
    ("FIL", 1.16104650, 1.18095350, 65.25409500, "0.00001"),
    ("DOT", 1.15420515, 1.17399485, 64.44605250, "0.00001"),
]


@pytest.mark.parametrize("name,sp,ep,tot,tick", HISTORICAL_GRIDS)
def test_current_config_yields_exactly_5_percent_per_level_tp(name, sp, ep, tot, tick):
    """Baseline-bewijs: de HUIDIGE config geeft altijd 5.00% per level.

    Komt overeen met alle 18 productie-logregels
    '📈 Dynamic TP: ATR=.. x 0.6 -> TP=5.00% (clamped [2.5%-5.0%])'.
    """
    ex = _build_executor(start_price=sp, end_price=ep, total_amount_quote=tot,
                         tick=tick, **CURRENT)
    levels = ex._generate_grid_levels()
    assert float(levels[0].take_profit) == pytest.approx(0.05), \
        f"{name}: verwacht 5.00%, kreeg {float(levels[0].take_profit) * 100:.3f}%"


@pytest.mark.parametrize("name,sp,ep,tot,tick", HISTORICAL_GRIDS)
def test_candidate_lowers_per_level_tp_but_step_floor_binds(name, sp, ep, tot, tick):
    """KERNBEVINDING: de kandidaat verlaagt de per-level TP fors, maar komt
    NIET op de beoogde 1.2% uit.

    ``take_profit = max(self.step, dynamic_tp)`` (grid_executor.py:679) legt een
    ondergrens op gelijk aan de grid-step. Doordat
    ``min_spread_between_orders`` het aantal levels tot 2-4 beperkt, is die step
    1.41-1.80% — altijd boven de geconfigureerde 1.2%.
    """
    ex = _build_executor(start_price=sp, end_price=ep, total_amount_quote=tot,
                         tick=tick, **CANDIDATE)
    levels = ex._generate_grid_levels()
    tp = float(levels[0].take_profit)
    step = float(ex.step)

    # Fors lager dan de huidige 5% -> dit is de daadwerkelijke verbetering.
    assert tp < 0.05
    # Maar de step-vloer bindt, niet de 1.2%-configwaarde.
    assert tp == pytest.approx(step), \
        f"{name}: verwacht step-gebonden TP, tp={tp * 100:.3f}% step={step * 100:.3f}%"
    assert tp > CANDIDATE["dynamic_tp_max_pct"], \
        f"{name}: TP {tp * 100:.3f}% zou boven de geconfigureerde 1.2% moeten liggen"


def test_candidate_reaches_1_2_percent_only_when_enough_levels_fit():
    """Toont de voorwaarde waaronder 1.2% WEL bindend wordt: een kleinere
    ``min_spread_between_orders`` laat >=3 levels toe, waardoor de step onder
    1.2% zakt. Dit is een grid-geometriewijziging, GEEN onderdeel van de
    voorgestelde 3-veldswijziging."""
    # 0.0085 (productie) -> 2 levels -> step == volledige range
    narrow = _build_executor(start_price=0.69147210, end_price=0.70332790,
                             total_amount_quote=50.62, tick="0.00001",
                             min_spread_between_orders="0.0085", **CANDIDATE)
    narrow_levels = narrow._generate_grid_levels()
    assert len(narrow_levels) == 2
    assert float(narrow_levels[0].take_profit) > 0.012

    # 0.0057 -> 3 levels -> step 0.857% -> de 1.2%-configwaarde wordt bindend
    wide = _build_executor(start_price=0.69147210, end_price=0.70332790,
                           total_amount_quote=50.62, tick="0.00001",
                           min_spread_between_orders="0.0057", **CANDIDATE)
    wide_levels = wide._generate_grid_levels()
    assert len(wide_levels) >= 3
    assert float(wide_levels[0].take_profit) == pytest.approx(0.012)


# --- Punt 3: TP boven netto break-even -------------------------------------

def _break_even_tp(slippage=Decimal("0.0005"), spread=Decimal("0.0004")):
    """Break-even TP: netto = P*(tp*(1-F) - 2F) = 0, plus slippage en spread."""
    return (2 * FEE_PER_FILL + slippage + spread) / (1 - FEE_PER_FILL)


@pytest.mark.parametrize("name,sp,ep,tot,tick", HISTORICAL_GRIDS)
def test_candidate_per_level_tp_exceeds_net_break_even(name, sp, ep, tot, tick):
    """Elke nieuwe TP-sell moet boven fees + slippage + spread liggen."""
    ex = _build_executor(start_price=sp, end_price=ep, total_amount_quote=tot,
                         tick=tick, **CANDIDATE)
    tp = Decimal(str(float(ex._generate_grid_levels()[0].take_profit)))
    be = _break_even_tp()
    assert tp > be, f"{name}: TP {tp * 100:.3f}% ligt niet boven break-even {be * 100:.3f}%"


def test_break_even_is_about_0_69_percent_at_measured_fees():
    """Pin de break-even-aanname zodat een toekomstige feewijziging opvalt."""
    assert _break_even_tp() == pytest.approx(Decimal("0.00692"), abs=Decimal("0.0001"))


def test_configured_1_2_percent_would_still_clear_break_even():
    """Ook als de step-vloer ooit wegvalt, is 1.2% nog steeds winstgevend."""
    assert Decimal("0.012") > _break_even_tp()


# --- Punt 5: geen conflict met de overige exits ----------------------------

def test_per_level_tp_stays_below_global_tp_so_it_fires_first():
    """De per-level TP moet onder de globale TP blijven, anders is hij zinloos."""
    ex = _build_executor(start_price=0.69147210, end_price=0.70332790,
                         total_amount_quote=50.62, tick="0.00001", **CANDIDATE)
    per_level = Decimal(str(float(ex._generate_grid_levels()[0].take_profit)))
    global_tp = _required_global_tp(CANDIDATE["dynamic_tp_min_pct"], 2.5, 0.3)
    assert per_level < global_tp, (
        f"per-level {per_level * 100:.3f}% moet onder globale {global_tp * 100:.3f}% liggen"
    )


def test_candidate_does_not_touch_stop_loss_trailing_or_profit_lock_fields():
    """Structureel bewijs dat de 3 gewijzigde velden geen beschermingsmechanisme raken.

    Geen van de stop-/trailing-/profit-lock-paden leest dynamic_tp_* of
    min_grid_profit_pct voor hun drempel.
    """
    import inspect

    from multi_coin_grid_pro.risk import professional_risk_manager as prm

    # US-005 PROFIT_LOCK-tiers zijn hardcoded en kennen geen TP-config.
    src = inspect.getsource(prm.ProfessionalRiskManager.should_exit_position)
    for tp_field in ("dynamic_tp_min_pct", "dynamic_tp_max_pct", "min_grid_profit_pct"):
        assert tp_field not in src, f"PROFIT_LOCK leest onverwacht {tp_field}"

    # stop_loss_condition / trailing_stop_condition lezen uitsluitend triple_barrier.
    sl = inspect.getsource(GridExecutor.stop_loss_condition)
    ts = inspect.getsource(GridExecutor.trailing_stop_condition)
    for src_fn, label in ((sl, "stop_loss_condition"), (ts, "trailing_stop_condition")):
        for tp_field in ("dynamic_tp_min_pct", "dynamic_tp_max_pct", "min_grid_profit_pct"):
            assert tp_field not in src_fn, f"{label} leest onverwacht {tp_field}"


# --- Punt 6: volatiliteits-unitbug (uitsluitend vastgelegd, NIET gewijzigd) --

def test_volatility_unit_mismatch_is_documented_and_pins_current_behaviour():
    """_calculate_volatility() levert PROCENTPUNTEN; beide consumenten
    behandelen de waarde als FRACTIE.

    Gevolg (niet gewijzigd, alleen vastgelegd):
      * per-level TP  -> altijd dynamic_tp_max_pct i.p.v. ATR-geschaald
      * dynamische SL -> altijd max_stop_pct (2.0%) i.p.v. ~1.05%

    Zodra deze test faalt, is de unitbug verholpen en moeten de TP/SL-clamps
    opnieuw worden geijkt.
    """
    import inspect

    from multi_coin_grid_pro.utils.trend_calculator import TrendCalculator

    src = inspect.getsource(TrendCalculator._calculate_volatility)
    assert "* 100" in src, "volatility wordt niet langer in procentpunten geleverd"

    # Dynamische stop-loss: productiewaarden uit spot_grid_kraken_usd.yaml.
    atr_stop_multiplier, min_stop, max_stop = 1.5, 0.010, 0.020
    actual = max(min_stop, min(PROD_ATR_PCT * atr_stop_multiplier, max_stop))
    intended = max(min_stop, min((PROD_ATR_PCT / 100) * atr_stop_multiplier, max_stop))
    assert actual == pytest.approx(0.020), "SL klemt niet langer op max_stop_pct"
    assert intended == pytest.approx(0.0105, abs=1e-4)
    assert actual > intended, "unitbug maakt de stop breder dan bedoeld"


def test_candidate_neutralises_the_atr_unit_bug_for_per_level_tp():
    """Met tp_min == tp_max is de per-level TP onafhankelijk van atr_pct,
    waardoor de unitbug geen invloed meer heeft op de TP (de SL blijft
    ongemoeid)."""
    results = set()
    for atr in (0.0001, 0.6997, 5.0, 150.0):
        ex = _build_executor(start_price=0.69147210, end_price=0.70332790,
                             total_amount_quote=50.62, tick="0.00001", **CANDIDATE)
        ex.config.custom_info["atr_pct"] = atr
        results.add(float(ex._generate_grid_levels()[0].take_profit))
    assert len(results) == 1, f"TP varieert nog met atr_pct: {results}"


# --- Optie B (afgewezen): ontkoppelen via dynamic_tp_enabled=false ---------

def test_option_b_reaches_exactly_1_2_percent_per_level():
    """Optie B HAALT het doel wel: met dynamic_tp_enabled=false slaat de
    ``max(self.step, ..)``-vloer niet toe en is de per-level TP exact gelijk
    aan triple_barrier_config.take_profit."""
    ex = _build_executor(start_price=0.69147210, end_price=0.70332790,
                         total_amount_quote=50.62, tick="0.00001",
                         dynamic_tp_min_pct=0.025, dynamic_tp_max_pct=0.05)
    ex.config.custom_info["dynamic_tp_enabled"] = False
    ex.config.triple_barrier_config.take_profit = Decimal("0.012")

    assert float(ex._generate_grid_levels()[0].take_profit) == pytest.approx(0.012)


def test_option_b_keeps_global_tp_at_2_5_percent():
    """Met dynamic_tp_enabled=false valt de dynamic_tp_min_pct-term weg; de
    globale TP komt dan volledig uit min_grid_profit_pct."""
    ex = GridExecutor.__new__(GridExecutor)
    cfg = MagicMock()
    cfg.custom_info = {
        "dynamic_tp_enabled": False,
        "dynamic_tp_min_pct": 0.012,
        "min_grid_profit_pct": 2.5,
        "fee_aware_min_net_profit_pct": 0.3,
    }
    ex.config = cfg
    assert ex._required_take_profit_net_pct() == Decimal("0.025")


def test_option_b_implicitly_changes_activation_bounds_and_is_therefore_rejected():
    """REDEN VAN AFWIJZING van optie B.

    De controller zet ``activation_bounds = dynamic_take_profit_pct``
    (multi_coin_grid_controller.py:11165). Optie B verlaagt take_profit_pct
    naar 0.012 en daarmee ongewild ook activation_bounds van 7.5% naar 1.2%.

    Gevolg (hieronder nagerekend met de echte filterformule uit
    ``_filter_levels_by_activation_bounds`` / ``get_open_order_ids_to_cancel``):
    zodra de prijs naar de gridtop loopt, valt het onderste koopniveau buiten
    de bounds en wordt het geannuleerd. Dat is een materiële wijziging van de
    orderplaatsing die buiten de gevraagde scope valt.
    """
    start, end = 100.0, 101.8          # 1.8% grid, 2 niveaus
    levels = [start, end]

    def active_levels(mid, activation_bounds):
        floor = mid * (1 - activation_bounds)
        return [i for i, p in enumerate(levels) if p >= floor]

    mid_at_top = end

    # Optie A: activation_bounds blijft 7.5% -> beide niveaus blijven actief.
    assert active_levels(mid_at_top, 0.075) == [0, 1]

    # Optie B: activation_bounds wordt 1.2% -> onderste niveau valt weg.
    assert active_levels(mid_at_top, 0.012) == [1]
