"""Risk-based position sizing, independent of MT5 so it can be unit tested."""
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class SymbolSpec:
    tick_size: float
    tick_value: float      # account currency per 1 lot per tick
    volume_min: float
    volume_max: float
    volume_step: float


def round_volume(vol: float, spec: SymbolSpec) -> float:
    steps = math.floor(vol / spec.volume_step + 1e-9)
    v = steps * spec.volume_step
    v = min(v, spec.volume_max)
    decimals = max(0, -int(math.floor(math.log10(spec.volume_step)))) if spec.volume_step < 1 else 0
    return round(v, decimals)


def risk_amount(balance: float, mode: str, percent: float, dollars: float) -> float:
    """Money lost if every leg hits SL. mode: 'persen' (of balance) or 'dolar' (fixed)."""
    if mode == "dolar":
        return max(0.0, float(dollars))
    return max(0.0, balance * float(percent) / 100.0)


def loss_per_lot(entry: float, sl: float, spec: SymbolSpec) -> float:
    if spec.tick_size <= 0 or spec.tick_value <= 0:
        return 0.0
    return abs(entry - sl) / spec.tick_size * spec.tick_value


def lot_for_risk(risk: float, per_lot: float, spec: SymbolSpec,
                 max_lot: float = float("inf")) -> float:
    """Total lot so that hitting SL loses about `risk`. Rounded down; 0 if below minimum."""
    if risk <= 0 or per_lot <= 0:
        return 0.0
    vol = round_volume(min(risk / per_lot, max_lot), spec)
    return vol if vol >= spec.volume_min else 0.0


def plan_legs(total: float, tps: List[float], split: Dict[int, List[float]],
              spec: SymbolSpec) -> List[Tuple[float, float]]:
    """Split `total` lot over the TPs as [(volume, tp), ...].

    Shares come from `split[number_of_tps]`. If the lot is too small for every leg to
    reach the broker minimum, the farthest TP is dropped and the split retried.
    """
    n = min(len(tps), max(split) if split else len(tps))
    while n >= 1:
        shares = split.get(n) or [1] * n
        s = sum(shares)
        legs = [round_volume(total * x / s, spec) for x in shares]
        if all(l >= spec.volume_min for l in legs):
            rest = round_volume(total - sum(legs), spec)
            if rest > 0:
                legs[0] = round_volume(legs[0] + rest, spec)
            return list(zip(legs, tps[:n]))
        n -= 1
    return []
