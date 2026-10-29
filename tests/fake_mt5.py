"""A small in-memory MT5 that fills limits and hits SL/TP as the price moves."""
from types import SimpleNamespace as NS


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_REAL = 0, 2
    ACCOUNT_MARGIN_MODE_RETAIL_NETTING, ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 0, 2
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT = 2, 3
    ORDER_TYPE_BUY_STOP, ORDER_TYPE_SELL_STOP = 4, 5
    TRADE_ACTION_DEAL, TRADE_ACTION_PENDING, TRADE_ACTION_SLTP, TRADE_ACTION_REMOVE = 1, 5, 6, 8
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    ORDER_TIME_GTC = 0
    TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL = 10008, 10009, 10010
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    DEAL_TYPE_BUY, DEAL_TYPE_SELL, DEAL_TYPE_BALANCE = 0, 1, 2
    DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT, DEAL_ENTRY_OUT_BY = 0, 1, 2, 3
    DEAL_REASON_CLIENT, DEAL_REASON_EXPERT, DEAL_REASON_SL, DEAL_REASON_TP = 0, 3, 4, 5
    ORDER_STATE_CANCELED, ORDER_STATE_FILLED, ORDER_STATE_REJECTED, ORDER_STATE_EXPIRED = 2, 4, 5, 6
    TIMEFRAME_M1 = 1

    def __init__(self, bid=4000.0, spread=0.2, balance=10_000.0, demo=True, hedging=True,
                 currency="USD"):
        self.bid, self.ask, self.time = bid, bid + spread, 1_000_000
        self.balance, self.currency = balance, currency
        self.trade_mode = self.ACCOUNT_TRADE_MODE_DEMO if demo else self.ACCOUNT_TRADE_MODE_REAL
        self.margin_mode = (self.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING if hedging
                            else self.ACCOUNT_MARGIN_MODE_RETAIL_NETTING)
        self.sym = NS(name="XAUUSDm", point=0.001, digits=3, trade_tick_size=0.001,
                      trade_tick_value=0.1, volume_min=0.01, volume_max=200, volume_step=0.01,
                      trade_stops_level=0, filling_mode=1)
        self.accepted_fillings = None     # None = all; or a set
        self.fail_sltp = 0                # number of SLTP requests to reject
        self.orders, self.positions = {}, {}
        self.deals, self.hist_orders, self.bars, self.requests = [], {}, [], []
        self._next = 100

    # --- terminal -----------------------------------------------------------
    def initialize(self, **kw):
        return True

    def last_error(self):
        return (1, "fake")

    def account_info(self):
        floating = sum(p.profit for p in self.positions.values())
        return NS(login=123, balance=self.balance, equity=self.balance + floating, currency=self.currency,
                  trade_mode=self.trade_mode, margin_mode=self.margin_mode)

    def symbol_select(self, name, enable=True):
        return name == self.sym.name

    def symbol_info(self, name):
        return self.sym if name == self.sym.name else None

    def symbol_info_tick(self, name):
        return NS(bid=self.bid, ask=self.ask, time=self.time) if name == self.sym.name else None

    def order_calc_profit(self, otype, symbol, volume, open_price, close_price):
        sign = 1 if otype == self.ORDER_TYPE_BUY else -1
        return sign * (close_price - open_price) / self.sym.trade_tick_size * self.sym.trade_tick_value * volume

    # --- queries ------------------------------------------------------------
    def orders_get(self, ticket=None, **kw):
        if ticket is not None:
            return (self.orders[ticket],) if ticket in self.orders else ()
        return tuple(self.orders.values())

    def positions_get(self, ticket=None, **kw):
        if ticket is not None:
            return (self.positions[ticket],) if ticket in self.positions else ()
        return tuple(self.positions.values())

    def history_deals_get(self, date_from=None, date_to=None, position=None):
        if position is not None:
            return tuple(d for d in self.deals if d.position_id == position)
        return tuple(d for d in self.deals if date_from <= d.time <= date_to)

    def history_orders_get(self, ticket=None, **kw):
        return (self.hist_orders[ticket],) if ticket in self.hist_orders else ()

    def copy_rates_range(self, symbol, tf, date_from, date_to):
        return [b for b in self.bars if date_from <= b["time"] <= date_to]

    # --- trading ------------------------------------------------------------
    def _res(self, code, order=0, comment=""):
        return NS(retcode=code, order=order, comment=comment, price=0.0)

    def order_send(self, req):
        self.requests.append(req)
        a = req["action"]
        fill = req.get("type_filling")
        if a in (self.TRADE_ACTION_DEAL, self.TRADE_ACTION_PENDING) and \
                self.accepted_fillings is not None and fill not in self.accepted_fillings:
            return self._res(10030, comment="Unsupported filling mode")
        if a == self.TRADE_ACTION_PENDING:
            return self._pending(req)
        if a == self.TRADE_ACTION_DEAL:
            return self._deal(req)
        if a == self.TRADE_ACTION_SLTP:
            return self._sltp(req)
        if a == self.TRADE_ACTION_REMOVE:
            o = self.orders.pop(req["order"], None)
            if o is None:
                return self._res(10013, comment="Invalid request")
            self.hist_orders[o.ticket] = NS(ticket=o.ticket, state=self.ORDER_STATE_CANCELED)
            return self._res(self.TRADE_RETCODE_DONE)
        return self._res(10013)

    def _pending(self, req):
        t, p = req["type"], req["price"]
        valid = {self.ORDER_TYPE_BUY_LIMIT: p < self.ask, self.ORDER_TYPE_SELL_LIMIT: p > self.bid,
                 self.ORDER_TYPE_BUY_STOP: p > self.ask, self.ORDER_TYPE_SELL_STOP: p < self.bid}[t]
        if not valid:
            return self._res(10015, comment="Invalid price")
        self._next += 1
        self.orders[self._next] = NS(ticket=self._next, type=t, price_open=p, sl=req["sl"],
                                     tp=req["tp"], volume_current=req["volume"], magic=req["magic"],
                                     symbol=req["symbol"], comment=req["comment"])
        return self._res(self.TRADE_RETCODE_DONE, order=self._next)

    def _deal(self, req):
        if "position" in req:   # closing
            p = self.positions.get(req["position"])
            if p is None:
                return self._res(10013)
            self._close(p, self.bid if p.type == self.POSITION_TYPE_BUY else self.ask,
                        self.DEAL_REASON_EXPERT)
            return self._res(self.TRADE_RETCODE_DONE, order=p.ticket)
        self._next += 1
        buy = req["type"] == self.ORDER_TYPE_BUY
        self._open(self._next, buy, self.ask if buy else self.bid, req)
        return self._res(self.TRADE_RETCODE_DONE, order=self._next)

    def _sltp(self, req):
        p = self.positions.get(req["position"])
        if p is None:
            return self._res(10013)
        if self.fail_sltp:
            self.fail_sltp -= 1
            return self._res(10016, comment="Invalid stops")
        buy = p.type == self.POSITION_TYPE_BUY
        if req["sl"] and (req["sl"] >= self.bid if buy else req["sl"] <= self.ask):
            return self._res(10016, comment="Invalid stops")
        p.sl, p.tp = req["sl"], req["tp"]
        return self._res(self.TRADE_RETCODE_DONE)

    def _open(self, ticket, buy, price, req):
        self.positions[ticket] = NS(ticket=ticket, identifier=ticket, symbol=req["symbol"],
                                    type=self.POSITION_TYPE_BUY if buy else self.POSITION_TYPE_SELL,
                                    volume=req["volume"], price_open=price, sl=req["sl"], tp=req["tp"],
                                    profit=0.0, magic=req["magic"], time=self.time)
        self.deals.append(NS(position_id=ticket, entry=self.DEAL_ENTRY_IN, reason=self.DEAL_REASON_EXPERT,
                             price=price, profit=0.0, swap=0.0, commission=0.0, time=self.time,
                             type=self.DEAL_TYPE_BUY if buy else self.DEAL_TYPE_SELL))

    def _close(self, p, price, reason):
        buy = p.type == self.POSITION_TYPE_BUY
        profit = round(self.order_calc_profit(self.ORDER_TYPE_BUY if buy else self.ORDER_TYPE_SELL,
                                              p.symbol, p.volume, p.price_open, price), 2)
        self.balance += profit
        del self.positions[p.ticket]
        self.deals.append(NS(position_id=p.ticket, entry=self.DEAL_ENTRY_OUT, reason=reason,
                             price=price, profit=profit, swap=0.0, commission=0.0, time=self.time,
                             type=self.DEAL_TYPE_SELL if buy else self.DEAL_TYPE_BUY))

    # --- market simulation --------------------------------------------------
    def set_price(self, bid, spread=None, seconds=60):
        spread = (self.ask - self.bid) if spread is None else spread
        self.time += seconds
        self.bid, self.ask = bid, round(bid + spread, 3)
        self.bars.append({"time": self.time, "high": bid, "low": bid})
        for o in list(self.orders.values()):
            hit = {self.ORDER_TYPE_BUY_LIMIT: self.ask <= o.price_open,
                   self.ORDER_TYPE_SELL_LIMIT: self.bid >= o.price_open,
                   self.ORDER_TYPE_BUY_STOP: self.ask >= o.price_open,
                   self.ORDER_TYPE_SELL_STOP: self.bid <= o.price_open}[o.type]
            if hit:
                del self.orders[o.ticket]
                self.hist_orders[o.ticket] = NS(ticket=o.ticket, state=self.ORDER_STATE_FILLED)
                buy = o.type in (self.ORDER_TYPE_BUY_LIMIT, self.ORDER_TYPE_BUY_STOP)
                self._open(o.ticket, buy, o.price_open,
                           {"symbol": o.symbol, "volume": o.volume_current, "sl": o.sl, "tp": o.tp,
                            "magic": o.magic})
        for p in list(self.positions.values()):
            buy = p.type == self.POSITION_TYPE_BUY
            px = self.bid if buy else self.ask
            if p.sl and (px <= p.sl if buy else px >= p.sl):
                self._close(p, p.sl, self.DEAL_REASON_SL)
            elif p.tp and (px >= p.tp if buy else px <= p.tp):
                self._close(p, p.tp, self.DEAL_REASON_TP)
            else:
                p.profit = round(self.order_calc_profit(
                    self.ORDER_TYPE_BUY if buy else self.ORDER_TYPE_SELL, p.symbol, p.volume,
                    p.price_open, px), 2)
