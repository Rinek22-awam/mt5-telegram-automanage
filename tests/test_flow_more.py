"""Five TPs, cent accounts, HIGHRISK flag, source updates, market fill price."""
from .fake_mt5 import FakeMT5
from .test_flow import SETUP, confirmed, make, post, press, step

FIVE_TP = """SETUP
Pair: XAUUSD
Arah: BUY
Entry: 3990
SL: 3980
TP1: 4000
TP2: 4010
TP3: 4020
TP4: 4030
TP5: 4040
Sumber: outlook"""


def test_five_tps_split_and_trail_all_the_way():
    app, mt5, bot, _ = make()
    confirmed(app, FIVE_TP)                     # 0.10 lot -> 30/25/20/15/10, rounding rest on TP1
    assert sorted(o.volume_current for o in mt5.orders.values()) == [0.01, 0.01, 0.02, 0.02, 0.04]
    step(app, mt5, 3989.7)
    expected_sl = {4000.5: 3991.0, 4010.5: 4000.0, 4020.5: 4010.0, 4030.5: 4020.0}
    for price, sl in expected_sl.items():
        step(app, mt5, price)
        assert {p.sl for p in mt5.positions.values()} == {sl}, price
    step(app, mt5, 4040.5)                      # last leg takes TP5
    s = app.journal.get(1)
    assert s["status"] == "done" and s["tp_level"] == 5


def test_cent_account_converts_dollar_risk():
    # USC account: $10 risk = 1000 USC. A cent lot is 1/100 of a standard lot, so a $10
    # gold move on 1 cent lot = 1000 USC, the same numbers MT5 reports in USC.
    app, mt5, bot, _ = make({"risiko": {"mode": "dolar", "dolar": 10}},
                            mt5=FakeMT5(bid=3995.0, balance=50_000, currency="USC"))
    post(app)
    assert "Risiko 1000.00 USC (tetap $10)" in bot.last
    assert "Lot total 1.0" in bot.last


def test_cent_account_percent_mode_unchanged():
    app, _, bot, _ = make(mt5=FakeMT5(bid=3995.0, balance=50_000, currency="USC"))
    post(app)
    assert "Risiko 500.00 USC (1.0% saldo)" in bot.last


def test_highrisk_is_flagged_and_always_asked():
    app, mt5, bot, _ = make({"gerbang": {"konfirmasi_wajib": False}})
    post(app, SETUP + "\nHighrisk: ya")
    assert "perlu konfirmasi" in bot.last and "HIGHRISK" in bot.last
    assert "Risiko 100.00 USD" in bot.last and not mt5.orders


def update(source="tes", action="INFO", text="TP1 hit"):
    return f"UPDATE\nSumber: {source}\nAksi: {action}\nTeks: {text}"


def test_info_update_is_passed_on():
    app, mt5, bot, _ = make()
    post(app, update(text="TP1 hit 🔥"))
    assert "Update channel tes" in bot.last and "TP1 hit" in bot.last
    assert not bot.sent[-1]["buttons"]


def test_cancel_update_asks_before_acting():
    app, mt5, bot, _ = make()
    confirmed(app)
    post(app, update(action="CANCEL", text="cancel gold"))
    assert len(mt5.orders) == 3                 # nothing happens without a tap
    assert bot.sent[-1]["buttons"][0][0] == ("🚫 Batalkan limit #1", "batal:1")
    press(app, "batal:1")
    assert not mt5.orders


def test_close_update_closes_only_that_setup():
    app, mt5, bot, _ = make(mt5=FakeMT5(bid=3988.0))
    confirmed(app)                              # market, 3 positions
    post(app, update(action="CLOSE", text="close now"))
    assert bot.sent[-1]["buttons"][0][0][1] == "tutup:1"
    press(app, "abaikan:0")
    assert len(mt5.positions) == 3
    press(app, "tutup:1")
    assert not mt5.positions


def test_cancel_update_on_unconfirmed_setup_offers_decline():
    app, mt5, bot, _ = make()
    post(app)
    post(app, update(action="CANCEL"))
    assert bot.sent[-1]["buttons"][0][0][1] == "tidak:1"


def test_update_from_other_source_finds_nothing():
    app, _, bot, _ = make()
    confirmed(app)
    post(app, update(source="lain", action="CLOSE"))
    assert "Tidak ada setup aktif" in bot.last


def test_market_leg_records_real_fill_price():
    app, mt5, _, _ = make(mt5=FakeMT5(bid=3988.0))
    confirmed(app)
    app.tick()
    step(app, mt5, 3979.0)                      # stopped out
    app.tick()
    legs = app.journal.legs(1)
    assert {l["fill_price"] for l in legs} == {3988.2} and {l["status"] for l in legs} == {"closed_sl"}
