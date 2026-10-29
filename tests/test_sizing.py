from copier.sizing import SymbolSpec, lot_for_risk, loss_per_lot, plan_legs, risk_amount, round_volume

FX = SymbolSpec(tick_size=0.00001, tick_value=1.0, volume_min=0.01, volume_max=100, volume_step=0.01)
GOLD = SymbolSpec(tick_size=0.01, tick_value=1.0, volume_min=0.01, volume_max=50, volume_step=0.01)
SPLIT = {1: [100], 2: [50, 50], 3: [50, 30, 20]}


def test_risk_modes():
    assert risk_amount(10_000, "persen", 1.0, 99) == 100.0
    assert risk_amount(10_000, "dolar", 1.0, 25) == 25.0


def test_fx_one_percent_50_pips():
    # 10k * 1% = 100 USD; 50 pips = 500 ticks * $1 = $500/lot -> 0.20 lot
    assert lot_for_risk(100, loss_per_lot(1.1000, 1.0950, FX), FX) == 0.20


def test_gold_fixed_dollars():
    # $10 SL distance = 1000 ticks * $1 = $1000/lot ; risk $50 -> 0.05
    assert lot_for_risk(50, loss_per_lot(2350, 2340, GOLD), GOLD) == 0.05


def test_rounds_down_and_caps():
    assert lot_for_risk(100, loss_per_lot(1.1, 1.0997, FX), FX, max_lot=1.5) == 1.5
    assert round_volume(0.239, FX) == 0.23


def test_too_small_returns_zero():
    assert lot_for_risk(0.25, loss_per_lot(1.1, 1.0, FX), FX) == 0.0
    assert lot_for_risk(10, 0, FX) == 0.0


def test_plan_legs_follows_split():
    assert plan_legs(1.0, [1, 2, 3], SPLIT, FX) == [(0.5, 1), (0.3, 2), (0.2, 3)]


def test_plan_legs_drops_far_tps_when_lot_is_small():
    assert plan_legs(0.02, [1, 2, 3], SPLIT, FX) == [(0.01, 1), (0.01, 2)]
    assert plan_legs(0.01, [1, 2, 3], SPLIT, FX) == [(0.01, 1)]


def test_plan_legs_remainder_goes_to_first_leg():
    legs = plan_legs(0.11, [1, 2, 3], SPLIT, FX)
    assert abs(sum(v for v, _ in legs) - 0.11) < 1e-9 and legs[0][0] == 0.06


def test_plan_legs_more_tps_than_split():
    assert len(plan_legs(1.0, [1, 2, 3, 4, 5], SPLIT, FX)) == 3
