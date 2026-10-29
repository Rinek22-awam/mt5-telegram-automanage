from copier.broker import Broker
from copier.config import with_defaults

from .fake_mt5 import FakeMT5


def mk(**kw):
    m = FakeMT5(**kw)
    return m, Broker(with_defaults({}), mt5_module=m)


def test_loss_per_lot_uses_order_calc_profit():
    _, b = mk()
    # gold: $10 move on 1 lot (100 oz) = $1000
    assert round(b.loss_per_lot("XAUUSDm", "BUY", 3990, 3980), 2) == 1000.0


def test_falls_back_to_next_filling_mode():
    m, b = mk()
    m.accepted_fillings = {m.ORDER_FILLING_RETURN}
    ticket, err = b.place("XAUUSDm", "BUY", "LIMIT", 0.05, 3990, 3980, 4010, "su1-1")
    assert ticket and err == ""
    assert [r["type_filling"] for r in m.requests] == [m.ORDER_FILLING_FOK, m.ORDER_FILLING_RETURN]


def test_leg_lifecycle():
    m, b = mk()
    t, _ = b.place("XAUUSDm", "BUY", "LIMIT", 0.05, 3990, 3980, 4010, "x")
    assert b.leg_state(t).state == "pending"
    m.set_price(3989.8)
    st = b.leg_state(t)
    assert st.state == "open" and st.price == 3990
    m.set_price(4010.5)
    st = b.leg_state(t)
    assert (st.state, st.reason, st.profit) == ("closed", "tp", 100.0)


def test_cancelled_leg():
    m, b = mk()
    t, _ = b.place("XAUUSDm", "SELL", "LIMIT", 0.05, 4010, 4020, 3990, "x")
    assert b.cancel(t)[0]
    assert b.leg_state(t).state == "cancelled"


def test_normalize_to_tick():
    _, b = mk()
    assert b.normalize("XAUUSDm", 3990.12345) == 3990.123


def test_day_pnl():
    m, b = mk()
    b.place("XAUUSDm", "BUY", "MARKET", 0.1, 0, 3990, 4010, "x")
    m.set_price(3995.0)
    realized, floating, start = b.day_pnl("XAUUSDm")
    assert realized == 0 and round(floating, 2) == -52.0 and start == 10_000
