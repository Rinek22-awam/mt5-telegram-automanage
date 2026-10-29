"""Executor: turns an approved setup into MT5 orders, one leg per TP."""
from dataclasses import dataclass
from typing import List, Tuple

from .models import LEG_OPEN, LEG_PENDING, PENDING, REJECTED, RUNNING, Setup
from .sizing import lot_for_risk, plan_legs, risk_amount


@dataclass
class Plan:
    entry: float               # price used for sizing (limit price, or market price)
    risk: float                # money at risk if every leg hits SL
    total_lot: float
    legs: List[Tuple[float, float]]   # (volume, tp) per TP from TP1; volume 0 = no order there
    actual_risk: float
    error: str = ""


class Executor:
    def __init__(self, cfg: dict, broker, journal, clock):
        self.cfg, self.broker, self.journal, self.clock = cfg, broker, journal, clock

    def plan(self, s: Setup, market) -> Plan:
        r = self.cfg["risiko"]
        mode = s.risk_mode or r["mode"]
        value = s.risk_value if s.risk_mode else (r["persen"] if mode == "persen" else r["dolar"])
        sym = market.symbol
        entry = s.entry if market.kind != "MARKET" else (
            market.ask if s.side == "BUY" else market.bid)
        balance = self.broker.account().balance
        if mode == "dolar":   # config and setups speak US dollars; cent accounts count in USC
            value = float(value) * self.broker.money_factor()
        risk = risk_amount(balance, mode, value, value)
        per_lot = self.broker.loss_per_lot(sym, s.side, entry, s.sl)
        spec = self.broker.spec(sym)
        total = lot_for_risk(risk, per_lot, spec, float(r["lot_maks"]))
        if total <= 0:
            need = spec.volume_min * per_lot
            return Plan(entry, risk, 0, [], 0, f"Lot di bawah minimum broker (risiko {risk:.2f}, "
                                                f"butuh minimal {need:.2f} untuk {spec.volume_min} lot)")
        tp = self.cfg["tp"]
        split = tp["bagi"]
        if tp["mode"] == "satu":   # the whole lot on one TP: a split with zeros before it
            k = min(tp["satu_ke"], len(s.tps))
            split = {k: [0] * (k - 1) + [100]}
        legs = plan_legs(total, s.tps, split, spec)
        if not legs:
            return Plan(entry, risk, total, [], 0, "Lot tidak bisa dibagi ke TP")
        return Plan(entry, risk, total, legs, round(sum(v for v, _ in legs) * per_lot, 2))

    def execute(self, setup_id: int, s: Setup, market, plan: Plan) -> Tuple[bool, str]:
        """Place every leg. If any leg fails, roll back the ones already placed."""
        placed, err = [], ""
        wanted = [(i, vol, tp) for i, (vol, tp) in enumerate(plan.legs) if vol > 0]   # i = TP index
        for i, vol, tp in wanted:
            ticket, err = self.broker.place(market.symbol, s.side, market.kind, vol, plan.entry,
                                            s.sl, tp, f"su{setup_id}-{i + 1}")
            if ticket is None:
                break
            placed.append((i, ticket, vol, tp))
        if len(placed) < len(wanted):
            for _, ticket, _, _ in placed:
                if market.kind == "MARKET":
                    self.broker.close(ticket)
                else:
                    self.broker.cancel(ticket)
            self.journal.update(setup_id, status=REJECTED, reason=f"Order ditolak broker: {err}")
            self.journal.event(setup_id, "order_failed", err)
            return False, err
        leg_status = LEG_OPEN if market.kind == "MARKET" else LEG_PENDING
        for i, ticket, vol, tp in placed:
            self.journal.add_leg(setup_id, i, ticket, vol, tp, leg_status)
        hours = self.cfg["entry"]["limit_kedaluwarsa_jam"]
        self.journal.update(setup_id, status=RUNNING if market.kind == "MARKET" else PENDING,
                            broker_symbol=market.symbol, risk_amount=plan.actual_risk,
                            total_lot=plan.total_lot, expires=self.clock() + hours * 3600,
                            order_type=market.kind)
        self.journal.event(setup_id, "placed", f"{market.kind} {len(placed)} kaki, "
                                               f"lot {plan.total_lot}, risiko {plan.actual_risk}")
        return True, ""
