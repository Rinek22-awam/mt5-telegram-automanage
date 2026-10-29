"""End-to-end: channel post -> gate -> confirmation -> MT5 orders -> SOP, on a fake MT5."""
from copier.app import App
from copier.broker import Broker
from copier.config import with_defaults
from copier.guard import RETRY_SEC
from copier.journal import Journal

from .fake_mt5 import FakeMT5

INBOX, ADMIN = -1001, 42
SETUP = """SETUP
Pair: XAUUSD
Arah: BUY
Entry: 3990
SL: 3980
TP1: 4000
TP2: 4010
TP3: 4020
Sumber: tes"""


class Clock:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t


class FakeBot:
    def __init__(self):
        self.sent, self.edits, self.n = [], [], 0

    def send(self, chat, text, buttons=None, reply_to=None):
        self.n += 1
        self.sent.append(dict(chat=chat, text=text, buttons=buttons, id=self.n))
        return {"message_id": self.n}

    def edit(self, chat, msg_id, text):
        self.edits.append(dict(id=msg_id, text=text))

    def answer(self, *a, **k):
        pass

    @property
    def last(self):
        return self.sent[-1]["text"]

    def texts(self):
        return "\n".join(m["text"] for m in self.sent) + "\n".join(e["text"] for e in self.edits)


def make(cfg=None, journal=None, mt5=None, clock=None):
    clock = clock or Clock()
    cfg = with_defaults({"simbol": {"XAUUSD": "XAUUSDm"}, **(cfg or {})})
    mt5 = mt5 or FakeMT5(bid=3995.0)
    journal = journal or Journal(":memory:", clock=clock)
    bot = FakeBot()
    app = App(cfg, Broker(cfg, mt5_module=mt5), journal, bot, INBOX, ADMIN, clock=clock)
    return app, mt5, bot, clock


_msg_id = iter(range(1, 10_000))


def post(app, text=SETUP, age=0):
    app.handle_update({"update_id": 1, "channel_post": {
        "chat": {"id": INBOX}, "message_id": next(_msg_id), "date": app.clock() - age, "text": text}})


def press(app, data, user=ADMIN):
    app.handle_update({"update_id": 2, "callback_query": {
        "id": "q", "from": {"id": user}, "data": data, "message": {"message_id": 1}}})


def command(app, text):
    app.handle_update({"update_id": 3, "message": {
        "chat": {"id": ADMIN}, "from": {"id": ADMIN}, "text": text}})


def step(app, mt5, bid):
    mt5.set_price(bid)
    app.tick()


def confirmed(app, text=SETUP):
    post(app, text)
    sid = app.journal.by_status("awaiting_confirm")[-1]["id"]
    press(app, f"ya:{sid}")
    return sid


# --- the happy path ---------------------------------------------------------
def test_full_lifecycle_limit_be_trailing():
    app, mt5, bot, _ = make()
    post(app)
    assert "perlu konfirmasi" in bot.last and bot.sent[-1]["buttons"]
    assert "TP1 4000.0 (0.05 lot)" in bot.last and "Risiko 100.00 USD (1.0% saldo)" in bot.last
    assert not mt5.orders                       # nothing placed before "Ya"

    press(app, "ya:1")
    assert "LIMIT terpasang" in bot.edits[-1]["text"]
    assert sorted(o.volume_current for o in mt5.orders.values()) == [0.02, 0.03, 0.05]
    assert app.journal.get(1)["status"] == "pending"

    step(app, mt5, 3989.7)                      # limit fills
    assert app.journal.get(1)["status"] == "running" and "ke-fill" in bot.texts()

    step(app, mt5, 4000.5)                      # TP1 hit -> BE + 0.1R on the rest
    assert [round(p.sl, 3) for p in mt5.positions.values()] == [3991.0, 3991.0]

    step(app, mt5, 4010.5)                      # TP2 hit -> SL to TP1
    assert [p.sl for p in mt5.positions.values()] == [4000.0]

    step(app, mt5, 3999.9)                      # pullback stops out the runner at TP1
    s = app.journal.get(1)
    assert s["status"] == "done" and s["tp_level"] == 2
    assert s["pnl"] == round(50 + 60 + 20, 2)   # 0.05*$10*100 + 0.03*$20*100 + 0.02*$10*100
    assert "selesai: +130.00" in bot.texts()


def test_fixed_dollar_risk_mode_and_small_lot_drops_far_tps():
    app, mt5, bot, _ = make({"risiko": {"mode": "dolar", "dolar": 20}})
    post(app)
    assert "Risiko 20.00 USD (tetap $20)" in bot.last
    assert "TP3 4020.0 (tidak dipakai" in bot.last
    press(app, "ya:1")
    assert sorted(o.volume_current for o in mt5.orders.values()) == [0.01, 0.01]


def test_per_setup_risk_override():
    app, mt5, bot, _ = make()
    post(app, SETUP + "\nRisk: $50")
    assert "Risiko 50.00 USD (tetap $50.0, dari setup)" in bot.last


def test_sell_setup():
    app, mt5, bot, _ = make(mt5=FakeMT5(bid=3995.0))
    sid = confirmed(app, "SETUP\nPair: XAUUSD\nArah: SELL\nEntry: 4000\nSL: 4010\nTP1: 3990\nTP2: 3980")
    assert app.journal.get(sid)["status"] == "pending"
    step(app, mt5, 4000.1)
    step(app, mt5, 3989.0)                      # TP1: ask 3989.2 <= 3990
    p = list(mt5.positions.values())
    assert len(p) == 1 and p[0].sl == 3999.0    # BE 4000 - 0.1R


# --- gate -------------------------------------------------------------------
def test_market_when_price_already_better_than_limit():
    app, mt5, bot, _ = make(mt5=FakeMT5(bid=3988.0))
    confirmed(app)
    assert not mt5.orders and len(mt5.positions) == 3
    assert "masuk market" in bot.edits[-1]["text"]


def test_rejects_old_post_and_wrong_symbol():
    app, mt5, bot, _ = make()
    post(app, age=3600)
    assert "basi" in bot.last
    post(app, SETUP.replace("XAUUSD", "NAS100"))
    assert "tidak ada di MT5" in bot.last


def test_limit_past_tp1_is_asked_not_rejected():
    app, mt5, bot, _ = make({"gerbang": {"konfirmasi_wajib": False}}, mt5=FakeMT5(bid=4005.0))
    post(app)
    assert "perlu konfirmasi" in bot.last and "lewat TP1" in bot.last and not mt5.orders
    press(app, "ya:1")
    assert len(mt5.orders) == 3                 # limits wait below price
    step(app, mt5, 3989.7)                      # price comes back, limits fill
    assert [p.sl for p in mt5.positions.values()] == [3980.0] * 3   # earlier high is not a TP1 hit


def test_market_past_tp1_is_rejected():
    app, mt5, bot, _ = make(mt5=FakeMT5(bid=4005.0))
    post(app, SETUP.replace("Entry: 3990\n", "Order: MARKET\n"))
    assert "TP1 sudah terlewat" in bot.last and not mt5.positions
    post(app, SETUP.replace("Entry: 3990", "Entry: 3992\nOrder: STOP"))   # stop already passed -> market
    assert "TP1 sudah terlewat" in bot.last and not mt5.positions


def test_rejects_entry_far_from_price():
    app, _, bot, _ = make(mt5=FakeMT5(bid=4200.0))
    post(app, SETUP.replace("TP1: 4000", "TP1: 4300").replace("TP2: 4010", "TP2: 4310")
         .replace("TP3: 4020", "TP3: 4320"))
    assert "dari harga sekarang" in bot.last


def test_duplicate_and_similar():
    app, _, bot, _ = make()
    confirmed(app)
    post(app)
    assert "Dobel dengan setup #1" in bot.last
    post(app, SETUP.replace("Entry: 3990", "Entry: 3991"))
    assert "Mirip setup #1" in bot.last


def test_similar_setup_asks_even_when_confirmation_is_off():
    app, mt5, bot, _ = make({"gerbang": {"konfirmasi_wajib": False}})
    post(app)
    assert len(mt5.orders) == 3 and "terpasang" in bot.last
    post(app, SETUP.replace("Entry: 3990", "Entry: 3991"))
    assert "perlu konfirmasi" in bot.last and len(mt5.orders) == 3


def test_format_error_is_reported():
    app, _, bot, _ = make()
    post(app, "SETUP\nPair: XAUUSD\nArah: BUY")
    assert "Format setup salah" in bot.last
    n = len(bot.sent)
    post(app, "selamat pagi")
    assert len(bot.sent) == n


def test_max_active_setups():
    app, _, bot, _ = make({"pengaman": {"maks_setup_aktif": 1}})
    confirmed(app)
    post(app, SETUP.replace("Entry: 3990", "Entry: 3985"))
    assert "maksimal 1" in bot.last


def test_daily_loss_limit_blocks_new_setups():
    app, mt5, bot, _ = make(mt5=FakeMT5(bid=3995.0))
    mt5.deals.append(type("D", (), dict(position_id=1, entry=1, reason=4, price=0, profit=-400.0,
                                        swap=0.0, commission=0.0, time=mt5.time, type=0))())
    mt5.balance -= 400
    post(app)
    assert "Batas loss harian" in bot.last


def test_confirmation_expires():
    app, mt5, bot, clock = make()
    post(app)
    clock.t += 31 * 60
    app.tick()
    assert app.journal.get(1)["status"] == "expired" and "kedaluwarsa" in bot.edits[-1]["text"]
    press(app, "ya:1")
    assert not mt5.orders


def test_decline_and_strangers_are_ignored():
    app, mt5, bot, _ = make()
    post(app)
    press(app, "ya:1", user=999)
    assert not mt5.orders
    press(app, "tidak:1")
    assert app.journal.get(1)["status"] == "declined" and not mt5.orders


def test_refuses_real_account_and_netting():
    app, _, bot, _ = make(mt5=FakeMT5(demo=False))
    assert not app.startup_checks() and "REAL" in bot.last
    app, _, bot, _ = make(mt5=FakeMT5(hedging=False))
    assert not app.startup_checks() and "hedging" in bot.last
    app, _, bot, _ = make()
    assert app.startup_checks() and "Bot nyala" in bot.last


# --- guard ------------------------------------------------------------------
def test_limit_expires_after_hours():
    app, mt5, bot, clock = make()
    confirmed(app)
    clock.t += 12 * 3600 + 1
    app.tick()
    app.tick()
    assert not mt5.orders and app.journal.get(1)["status"] == "expired"
    assert "tidak ke-fill" in bot.texts()


def test_sl_move_failure_is_retried():
    app, mt5, bot, clock = make()
    confirmed(app)
    step(app, mt5, 3989.7)
    mt5.fail_sltp = 2                           # both remaining legs refused once
    step(app, mt5, 4000.5)
    assert "gagal" in bot.texts()
    assert all(p.sl == 3980 for p in mt5.positions.values())
    clock.t += RETRY_SEC + 1
    app.tick()
    assert all(p.sl == 3991.0 for p in mt5.positions.values())


def test_closes_when_price_runs_through_new_sl_before_it_is_set():
    app, mt5, bot, _ = make()
    confirmed(app)
    step(app, mt5, 3989.7)
    mt5.set_price(4000.5)                       # TP1 hit while the bot is not looking...
    step(app, mt5, 3990.5)                      # ...and price is already below BE (3991)
    assert not mt5.positions
    app.tick()                                  # closed legs are read back on the next pass
    assert app.journal.get(1)["status"] == "done"


def test_restart_picks_up_where_it_left_off():
    clock = Clock()
    journal = Journal(":memory:", clock=clock)
    app, mt5, _, _ = make(journal=journal, clock=clock)
    confirmed(app)
    step(app, mt5, 3989.7)
    # bot is off: TP1 and TP2 hit, price pulls back a bit
    mt5.set_price(4000.5)
    mt5.set_price(4010.5)
    mt5.set_price(4005.0)
    app2, _, bot2, _ = make(journal=journal, mt5=mt5, clock=clock)
    assert app2.startup_checks()
    app2.tick()
    assert [p.sl for p in mt5.positions.values()] == [4000.0]
    assert journal.get(1)["tp_level"] == 2


def test_stop_cancels_limits_and_blocks_new_setups():
    app, mt5, bot, _ = make()
    confirmed(app)
    command(app, "/stop")
    assert not mt5.orders and "3 limit dibatalkan" in bot.last
    post(app, SETUP.replace("Entry: 3990", "Entry: 3985"))
    assert "di-stop" in bot.last
    command(app, "/lanjut")
    post(app, SETUP.replace("Entry: 3990", "Entry: 3984"))
    assert "perlu konfirmasi" in bot.last


def test_close_all_needs_confirmation():
    app, mt5, bot, _ = make(mt5=FakeMT5(bid=3988.0))
    confirmed(app)
    command(app, "/tutupsemua")
    assert mt5.positions and bot.sent[-1]["buttons"]
    press(app, "tutupsemua:ya")
    assert not mt5.positions


def test_limit_list_shows_entry_sl_and_cancels_by_button():
    app, mt5, bot, _ = make()
    command(app, "/limit")
    assert "Tidak ada limit" in bot.last
    confirmed(app)
    confirmed(app, SETUP.replace("Entry: 3990", "Entry: 3985").replace("SL: 3980", "SL: 3975"))
    command(app, "/limit")
    assert "#1 XAUUSDm BUY @ 3990.0 · SL 3980.0 · habis" in bot.last
    assert "#2 XAUUSDm BUY @ 3985.0 · SL 3975.0 · habis" in bot.last
    assert bot.sent[-1]["buttons"] == [[("🚫 Batalkan #1", "batal:1")], [("🚫 Batalkan #2", "batal:2")]]
    press(app, "batal:1")
    assert "3 limit setup #1 dibatalkan" in bot.edits[-1]["text"] and len(mt5.orders) == 3
    app.tick()
    command(app, "/limit")
    assert "#1" not in bot.last and "#2" in bot.last


def test_delete_all_limits_needs_confirmation_and_keeps_positions():
    app, mt5, bot, _ = make()
    command(app, "/hapuslimit")
    assert "Tidak ada limit" in bot.last
    confirmed(app, SETUP.replace("Entry: 3990\n", "Order: MARKET\n"))     # a running trade
    confirmed(app, SETUP.replace("Entry: 3990", "Entry: 3985"))          # three limits
    command(app, "/hapuslimit")
    assert "#2" in bot.last and "#1" not in bot.last and len(mt5.orders) == 3
    press(app, "hapuslimit:tidak")
    assert len(mt5.orders) == 3
    command(app, "/hapuslimit")
    press(app, "hapuslimit:ya")
    assert not mt5.orders and len(mt5.positions) == 3
    assert "3 limit dihapus" in bot.edits[-1]["text"]
    assert not app.journal.get_kv("paused", False)                       # unlike /stop


def test_reset_journal_from_telegram(tmp_path):
    db = tmp_path / "jurnal.db"
    app, mt5, bot, _ = make(journal=Journal(str(db)), mt5=FakeMT5(bid=3988.0))
    confirmed(app)                                                       # running, so reset is refused
    command(app, "/resetjurnal")
    assert "Belum bisa reset" in bot.last and not bot.sent[-1]["buttons"]
    command(app, "/tutupsemua")
    press(app, "tutupsemua:ya")
    app.tick()
    command(app, "/resetjurnal")
    assert bot.sent[-1]["buttons"]
    press(app, "resetjurnal:ya")
    assert "1 setup dihapus" in bot.edits[-1]["text"] and not app.journal.since(0)
    backups = list(tmp_path.glob("jurnal-cadangan-*.db"))
    assert len(backups) == 1 and len(Journal(str(backups[0])).since(0)) == 1
    post(app)
    assert app.journal.by_status("awaiting_confirm")[-1]["id"] == 2    # numbering carries on


def test_status_command():
    app, _, bot, _ = make()
    confirmed(app)
    command(app, "/status")
    assert "#1 XAUUSDm BUY pending" in bot.last


def test_late_button_tap_still_executes():
    # Telegram refuses to acknowledge a tap that arrived late; the order must still go in
    app, mt5, bot, _ = make()
    post(app)

    def too_old(*a, **k):
        raise RuntimeError("Telegram answerCallbackQuery: Bad Request: query is too old")
    bot.answer = too_old
    bot.edit = too_old
    press(app, "ya:1")
    assert len(mt5.orders) == 3 and app.journal.get(1)["status"] == "pending"
    assert "LIMIT terpasang" in bot.last          # result sent as a new message instead
