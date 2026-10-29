"""Thin wrapper around the MetaTrader5 package. Pass `mt5_module` to inject a fake."""
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .sizing import SymbolSpec, loss_per_lot as tick_loss_per_lot

log = logging.getLogger(__name__)

_FILL_FOK, _FILL_IOC = 1, 2          # bits of symbol_info.filling_mode
_INVALID_FILL = 10030


@dataclass
class LegState:
    state: str                       # pending | open | closed | cancelled | unknown
    price: float = 0.0               # fill price (open) or close price (closed)
    sl: float = 0.0
    tp: float = 0.0
    volume: float = 0.0
    profit: float = 0.0
    reason: str = ""                 # tp | sl | other (closed only)
    time: float = 0.0                # fill time, server clock


class Broker:
    def __init__(self, cfg: dict, mt5_module=None):
        if mt5_module is None:
            import MetaTrader5 as mt5_module  # noqa: N813  (Windows only)
        self.mt5 = mt5_module
        self.magic = int(cfg["mt5"]["magic"])
        self.deviation = int(cfg["mt5"]["deviasi_poin"])

    # --- connection and account ---------------------------------------------
    def connect(self, login=None, password=None, server=None, path=None) -> bool:
        kw = {}
        if path:
            kw["path"] = path
        if login:
            kw.update(login=int(login), password=password, server=server)
        ok = self.mt5.initialize(**kw)
        if not ok:
            log.error("MT5 initialize failed: %s", self.mt5.last_error())
        return bool(ok)

    def account(self):
        return self.mt5.account_info()

    def is_demo(self) -> bool:
        return self.account().trade_mode == self.mt5.ACCOUNT_TRADE_MODE_DEMO

    def is_hedging(self) -> bool:
        return self.account().margin_mode == self.mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING

    # --- symbols and prices -------------------------------------------------
    def symbol_info(self, symbol):
        if not self.mt5.symbol_select(symbol, True):
            return None
        return self.mt5.symbol_info(symbol)

    def tick(self, symbol) -> Tuple[float, float, float]:
        t = self.mt5.symbol_info_tick(symbol)
        return (t.bid, t.ask, float(t.time)) if t else (0.0, 0.0, 0.0)

    def spec(self, symbol) -> SymbolSpec:
        i = self.mt5.symbol_info(symbol)
        return SymbolSpec(i.trade_tick_size, i.trade_tick_value, i.volume_min, i.volume_max,
                          i.volume_step)

    def normalize(self, symbol, price: Optional[float]) -> float:
        if not price:
            return 0.0
        i = self.mt5.symbol_info(symbol)
        step = i.trade_tick_size or i.point
        return round(round(price / step) * step, i.digits)

    def min_stop_distance(self, symbol) -> float:
        i = self.mt5.symbol_info(symbol)
        return (i.trade_stops_level or 0) * i.point

    def loss_per_lot(self, symbol, side, entry, sl) -> float:
        """Money lost per 1 lot from entry to SL, in account currency."""
        m = self.mt5
        otype = m.ORDER_TYPE_BUY if side == "BUY" else m.ORDER_TYPE_SELL
        try:
            p = m.order_calc_profit(otype, symbol, 1.0, entry, sl)
            if p is not None and p < 0:
                return -p
        except Exception:  # fall back to tick math
            log.debug("order_calc_profit failed", exc_info=True)
        return tick_loss_per_lot(entry, sl, self.spec(symbol))

    # --- orders -------------------------------------------------------------
    def _fillings(self, symbol) -> List[int]:
        m = self.mt5
        flags = self.mt5.symbol_info(symbol).filling_mode or 0
        first = []
        if flags & _FILL_FOK:
            first.append(m.ORDER_FILLING_FOK)
        if flags & _FILL_IOC:
            first.append(m.ORDER_FILLING_IOC)
        rest = [f for f in (m.ORDER_FILLING_RETURN, m.ORDER_FILLING_FOK, m.ORDER_FILLING_IOC)
                if f not in first]
        return first + rest

    def _send(self, req: dict, symbol: str):
        """order_send, retrying with the next filling mode if the broker rejects it."""
        m, res = self.mt5, None
        for fill in self._fillings(symbol):
            res = m.order_send({**req, "type_filling": fill})
            if res is None or res.retcode != _INVALID_FILL:
                break
        ok = res is not None and res.retcode in (m.TRADE_RETCODE_DONE, m.TRADE_RETCODE_PLACED,
                                                 m.TRADE_RETCODE_DONE_PARTIAL)
        err = "" if ok else (f"{res.retcode} {res.comment}" if res else str(m.last_error()))
        return ok, res, err

    def place(self, symbol, side, kind, volume, price, sl, tp, comment) -> Tuple[Optional[int], str]:
        """kind: LIMIT | STOP | MARKET. Returns (ticket, error)."""
        m = self.mt5
        if kind == "MARKET":
            bid, ask, _ = self.tick(symbol)
            otype = m.ORDER_TYPE_BUY if side == "BUY" else m.ORDER_TYPE_SELL
            action, price = m.TRADE_ACTION_DEAL, (ask if side == "BUY" else bid)
        else:
            otype = {("BUY", "LIMIT"): m.ORDER_TYPE_BUY_LIMIT, ("BUY", "STOP"): m.ORDER_TYPE_BUY_STOP,
                     ("SELL", "LIMIT"): m.ORDER_TYPE_SELL_LIMIT,
                     ("SELL", "STOP"): m.ORDER_TYPE_SELL_STOP}[(side, kind)]
            action = m.TRADE_ACTION_PENDING
        req = {"action": action, "symbol": symbol, "volume": float(volume), "type": otype,
               "price": self.normalize(symbol, price), "sl": self.normalize(symbol, sl),
               "tp": self.normalize(symbol, tp), "deviation": self.deviation,
               "magic": self.magic, "comment": comment[:31], "type_time": m.ORDER_TIME_GTC}
        ok, res, err = self._send(req, symbol)
        return (res.order, "") if ok else (None, err)

    def cancel(self, ticket: int) -> Tuple[bool, str]:
        m = self.mt5
        res = m.order_send({"action": m.TRADE_ACTION_REMOVE, "order": int(ticket)})
        ok = res is not None and res.retcode == m.TRADE_RETCODE_DONE
        return ok, "" if ok else (f"{res.retcode} {res.comment}" if res else str(m.last_error()))

    def modify_sl(self, symbol, ticket: int, sl: float, tp: float) -> Tuple[bool, str]:
        m = self.mt5
        res = m.order_send({"action": m.TRADE_ACTION_SLTP, "symbol": symbol, "position": int(ticket),
                            "sl": self.normalize(symbol, sl), "tp": self.normalize(symbol, tp),
                            "magic": self.magic})
        ok = res is not None and res.retcode == m.TRADE_RETCODE_DONE
        return ok, "" if ok else (f"{res.retcode} {res.comment}" if res else str(m.last_error()))

    def close(self, ticket: int) -> Tuple[bool, str]:
        m = self.mt5
        pos = m.positions_get(ticket=int(ticket))
        if not pos:
            return False, "posisi tidak ditemukan"
        p = pos[0]
        bid, ask, _ = self.tick(p.symbol)
        buy = p.type == m.POSITION_TYPE_BUY
        req = {"action": m.TRADE_ACTION_DEAL, "symbol": p.symbol, "volume": p.volume,
               "type": m.ORDER_TYPE_SELL if buy else m.ORDER_TYPE_BUY, "position": p.ticket,
               "price": bid if buy else ask, "deviation": self.deviation, "magic": self.magic,
               "comment": "bot close", "type_time": m.ORDER_TIME_GTC}
        ok, _, err = self._send(req, p.symbol)
        return ok, err

    # --- state --------------------------------------------------------------
    def leg_state(self, ticket: int) -> LegState:
        """Where a leg is now: still a pending order, an open position, or closed."""
        m, t = self.mt5, int(ticket)
        if m.orders_get(ticket=t):
            o = m.orders_get(ticket=t)[0]
            return LegState("pending", price=o.price_open, sl=o.sl, tp=o.tp,
                            volume=o.volume_current)
        pos = m.positions_get(ticket=t)
        if pos:
            p = pos[0]
            return LegState("open", price=p.price_open, sl=p.sl, tp=p.tp, volume=p.volume,
                            profit=p.profit, time=float(p.time))
        deals = m.history_deals_get(position=t) or []
        outs = [d for d in deals if d.entry in (m.DEAL_ENTRY_OUT, m.DEAL_ENTRY_OUT_BY)]
        if outs:
            last = outs[-1]
            reason = {m.DEAL_REASON_TP: "tp", m.DEAL_REASON_SL: "sl"}.get(last.reason, "other")
            profit = sum(d.profit + d.swap + d.commission + getattr(d, "fee", 0.0) for d in deals)
            return LegState("closed", price=last.price, profit=profit, reason=reason)
        hist = m.history_orders_get(ticket=t) or []
        if hist and hist[0].state in (m.ORDER_STATE_CANCELED, m.ORDER_STATE_EXPIRED,
                                      m.ORDER_STATE_REJECTED):
            return LegState("cancelled")
        return LegState("unknown")

    def day_pnl(self, symbol_for_clock: str) -> Tuple[float, float, float]:
        """(realized today, floating now, balance at start of the server day)."""
        m = self.mt5
        _, _, now = self.tick(symbol_for_clock)
        day_start = int(now - now % 86400)
        deals = m.history_deals_get(day_start, int(now) + 86400) or []
        realized = sum(d.profit + d.swap + d.commission + getattr(d, "fee", 0.0) for d in deals
                       if d.type in (m.DEAL_TYPE_BUY, m.DEAL_TYPE_SELL))
        floating = sum(p.profit for p in (m.positions_get() or []))
        return realized, floating, self.account().balance - realized

    def bot_tickets(self) -> set:
        """Tickets of every order and position carrying this bot's magic number."""
        m = self.mt5
        items = list(m.orders_get() or []) + list(m.positions_get() or [])
        return {x.ticket for x in items if x.magic == self.magic}

    def rates_extreme(self, symbol, side, since: float, until: float) -> Optional[float]:
        """Best price reached since `since` (high for BUY, low for SELL), from M1 bars."""
        m = self.mt5
        bars = m.copy_rates_range(symbol, m.TIMEFRAME_M1, int(since), int(until) + 60)
        if bars is None or len(bars) == 0:
            return None
        return max(b["high"] for b in bars) if side == "BUY" else min(b["low"] for b in bars)
