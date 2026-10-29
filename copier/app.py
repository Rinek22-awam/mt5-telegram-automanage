"""Wires the inbox channel, gate, executor and guard together."""
import logging
import os
import time
from datetime import datetime

from .executor import Executor
from .gate import Gate
from .guard import Guard
from .journal import backup_path
from .models import ACTIVE, AWAITING, DECLINED, EXPIRED, LEG_PENDING, REJECTED, RUNNING, Setup
from .setup_format import parse_setup, parse_update

log = logging.getLogger("copier")

HELP = ("Perintah:\n"
        "/status  setup aktif, loss hari ini\n"
        "/stop  hentikan setup baru + batalkan semua limit\n"
        "/lanjut  terima setup baru lagi\n"
        "/limit  daftar limit yang menunggu, dengan tombol batal\n"
        "/hapuslimit  hapus SEMUA limit yang belum ke-fill (ada konfirmasi)\n"
        "/tutupsemua  tutup SEMUA posisi bot (ada konfirmasi)\n"
        "/resetjurnal  hapus riwayat setup, ada cadangan (ada konfirmasi)")


def setup_from_row(r: dict) -> Setup:
    return Setup(symbol=r["symbol"], side=r["side"], entry=r["entry"], sl=r["sl"], tps=r["tps"],
                 order_type=r["order_type"], entry2=r["entry2"], sl2=r["sl2"],
                 risk_mode=r["risk_mode"], risk_value=r["risk_value"], source=r["source"] or "",
                 note=r["note"] or "", raw=r["raw"] or "")


class App:
    def __init__(self, cfg, broker, journal, bot, inbox_chat: int, admin_id: int, clock=time.time):
        self.cfg, self.broker, self.journal, self.bot = cfg, broker, journal, bot
        self.inbox, self.admin, self.clock = int(inbox_chat), int(admin_id), clock
        self.gate = Gate(cfg, broker, journal, clock)
        self.executor = Executor(cfg, broker, journal, clock)
        self.guard = Guard(cfg, broker, journal, self.notify, clock)

    # --- output -------------------------------------------------------------
    def notify(self, text, buttons=None):
        try:
            return self.bot.send(self.admin, text, buttons=buttons)
        except Exception:
            log.exception("cannot send Telegram message")
            log.info("message was: %s", text)
            return None

    # --- startup ------------------------------------------------------------
    def startup_checks(self) -> bool:
        acc = self.broker.account()
        if self.cfg["akun"]["hanya_demo"] and not self.broker.is_demo():
            self.notify("⛔ MT5 login ke akun REAL. Bot berhenti (akun.hanya_demo: true).")
            return False
        if not self.broker.is_hedging():
            self.notify("⛔ Akun MT5 bukan tipe hedging. TP bertahap butuh akun hedging.")
            return False
        missing = [m for m in set(self.cfg["simbol"].values()) if self.broker.symbol_info(m) is None]
        orphan = self.broker.bot_tickets() - self.journal.all_tickets()
        lines = [f"🤖 Bot nyala. Akun {acc.login} ({'demo' if self.broker.is_demo() else 'REAL'}), "
                 f"saldo {acc.balance:.2f} {acc.currency}",
                 f"Setup aktif di jurnal: {len(self.journal.by_status(*ACTIVE))}"]
        if missing:
            lines.append("⚠️ Simbol tidak ada di MT5: " + ", ".join(sorted(missing)) +
                         ". Setup untuk pair itu akan ditolak. Perbaiki lewat MENU > Utilitas > "
                         "Cocokkan nama pair dengan broker.")
        if orphan:
            lines.append(f"⚠️ {len(orphan)} order/posisi ber-magic bot tidak ada di jurnal "
                         f"(tidak dijaga): {sorted(orphan)}")
        if self.journal.get_kv("paused", False):
            lines.append("⏸ Masih dalam mode stop. /lanjut untuk menerima setup.")
        self.notify("\n".join(lines))
        return True

    # --- main loop ----------------------------------------------------------
    def run(self):
        interval = float(self.cfg["bot"]["interval_detik"])
        while True:
            started = self.clock()
            try:
                offset = self.journal.get_kv("tg_offset", 0)
                for u in self.bot.get_updates(offset, wait=1):
                    self.journal.set_kv("tg_offset", u["update_id"] + 1)
                    self.handle_update(u)
            except OSError as e:   # timeouts and dropped connections: just try again
                log.warning("Telegram lambat/putus, dicoba lagi: %s", e)
            except Exception:
                log.exception("telegram polling failed")
            try:
                self.tick()
            except Exception:
                log.exception("tick failed")
            time.sleep(max(0.0, interval - (self.clock() - started)))

    def tick(self):
        self._expire_confirmations()
        self.guard.run_once()
        self._watch_daily_loss()

    def handle_update(self, u: dict):
        try:
            if "channel_post" in u:
                self.on_channel_post(u["channel_post"])
            elif "callback_query" in u:
                self.on_button(u["callback_query"])
            elif "message" in u:
                self.on_message(u["message"])
        except Exception:
            log.exception("update failed: %s", u.get("update_id"))
            self.notify("⚠️ Error saat memproses pesan, lihat logs/bot.log")

    # --- inbox --------------------------------------------------------------
    def on_channel_post(self, msg: dict):
        chat = msg["chat"]["id"]
        if chat != self.inbox or self.journal.message_seen(chat, msg["message_id"]):
            return
        text = msg.get("text") or msg.get("caption") or ""
        upd = parse_update(text)
        if upd:
            self.on_source_update(upd)
            return
        setup, errors = parse_setup(text)
        if setup is None:
            if errors:
                self.notify("❌ Format setup salah:\n- " + "\n- ".join(errors))
            return
        meta = dict(msg_chat=chat, msg_id=msg["message_id"], posted=float(msg["date"]))
        v = self.gate.check(setup, posted=meta["posted"])
        plan = self.executor.plan(setup, v.market) if v.ok else None
        if plan and plan.error:
            v.ok, v.reasons = False, [plan.error]
        if not v.ok:
            sid = self.journal.add_setup(setup, REJECTED, reason="; ".join(v.reasons), **meta)
            self.notify(f"🚫 Setup #{sid} {setup.symbol} {setup.side} ditolak:\n- " + "\n- ".join(v.reasons))
            return
        sid = self.journal.add_setup(setup, AWAITING, broker_symbol=v.market.symbol,
                                     warning="; ".join(v.warnings), **meta)
        if not self.cfg["gerbang"]["konfirmasi_wajib"] and not v.warnings:
            self.notify(self._execute(sid))
            return
        minutes = self.cfg["gerbang"]["konfirmasi_kedaluwarsa_menit"]
        deadline = self.clock() + minutes * 60
        text = self._summary(sid, setup, v, plan) + \
            f"\nBerlaku sampai {datetime.fromtimestamp(deadline):%H:%M}"
        sent = self.notify(text, buttons=[[("✅ Ya, eksekusi", f"ya:{sid}"), ("❌ Tidak", f"tidak:{sid}")]])
        self.journal.update(sid, confirm_deadline=deadline,
                            confirm_msg_id=sent["message_id"] if sent else None)

    def on_source_update(self, upd: dict):
        """Updates from the signal source never act on their own: INFO is passed on,
        CANCEL / CLOSE become buttons for the most recent matching setup."""
        head = f"📣 Update channel{' ' + upd['source'] if upd['source'] else ''}"
        if upd["action"] == "INFO":
            self.notify(f"{head}:\n{upd['text']}")
            return
        src = upd["source"].lower()
        rows = [r for r in self.journal.by_status(AWAITING, *ACTIVE)
                if not src or (r["source"] or "").lower() == src]
        if not rows:
            self.notify(f"{head}: {upd['action']}\n{upd['text']}\nTidak ada setup aktif dari sumber ini.")
            return
        r = max(rows, key=lambda x: x["id"])
        sid = r["id"]
        if r["status"] == AWAITING:
            act = ("❌ Tolak setup #%d" % sid, f"tidak:{sid}")
        elif upd["action"] == "CANCEL":
            act = (f"🚫 Batalkan limit #{sid}", f"batal:{sid}")
        else:
            act = (f"🧯 Tutup semua posisi #{sid}", f"tutup:{sid}")
        self.notify(f"{head}: {upd['action']}\n{upd['text']}\n"
                    f"Setup terkait: #{sid} {r['broker_symbol'] or r['symbol']} {r['side']} ({r['status']})\n"
                    f"Bot tidak bertindak sebelum kamu tekan tombol.",
                    buttons=[[act, ("Abaikan", "abaikan:0")]])

    def _summary(self, sid, s: Setup, v, plan) -> str:
        m = v.market
        r = self.cfg["risiko"]
        mode = s.risk_mode or r["mode"]
        value = s.risk_value if s.risk_mode else r[mode]
        risk_txt = f"{value}% saldo" if mode == "persen" else f"tetap ${value}"
        if s.risk_mode:
            risk_txt += ", dari setup"
        lines = [f"🆕 Setup #{sid} perlu konfirmasi",
                 f"{m.symbol} {s.side} {m.kind} @ {plan.entry}",
                 f"SL {s.sl}"]
        for i, tp in enumerate(s.tps):
            vol = plan.legs[i][0] if i < len(plan.legs) else 0
            if vol:
                lot = f"{vol} lot"
            elif i < len(plan.legs) or self.cfg["tp"]["mode"] == "satu":
                lot = "tanpa lot"
            else:
                lot = "tidak dipakai, lot kurang"
            lines.append(f"TP{i + 1} {tp} ({lot})")
        cur = self.broker.account().currency
        lines += [f"Lot total {plan.total_lot} · Risiko {plan.actual_risk:.2f} {cur} ({risk_txt})",
                  f"Harga sekarang {m.bid} / {m.ask}"]
        if s.entry2 or s.sl2:
            lines.append(f"Entry2/SL2 dicatat, tidak dipakai: {s.entry2 or '-'} / {s.sl2 or '-'}")
        if s.source:
            lines.append(f"Sumber: {s.source}")
        lines += [f"⚠️ {w}" for w in v.warnings]
        return "\n".join(lines)

    def _execute(self, sid) -> str:
        row = self.journal.get(sid)
        s = setup_from_row(row)
        v = self.gate.check(s, recheck=True)
        plan = self.executor.plan(s, v.market) if v.ok else None
        if plan and plan.error:
            v.ok, v.reasons = False, [plan.error]
        if not v.ok:
            self.journal.update(sid, status=REJECTED, reason="; ".join(v.reasons))
            return f"🚫 #{sid} batal dieksekusi:\n- " + "\n- ".join(v.reasons)
        ok, err = self.executor.execute(sid, s, v.market, plan)
        if not ok:
            return f"🚫 #{sid} ditolak broker: {err}"
        what = "masuk market" if v.market.kind == "MARKET" else f"{v.market.kind} terpasang"
        return (f"📌 #{sid} {v.market.symbol} {s.side} {what}, lot {plan.total_lot}, "
                f"risiko {plan.actual_risk:.2f} {self.broker.account().currency}")

    def _expire_confirmations(self):
        for r in self.journal.by_status(AWAITING):
            if r["confirm_deadline"] and self.clock() > r["confirm_deadline"]:
                self.journal.update(r["id"], status=EXPIRED, reason="Tidak dikonfirmasi")
                self._edit(r, f"⌛ Setup #{r['id']} {r['symbol']} {r['side']} kedaluwarsa (tidak dijawab)")

    def _edit(self, row, text):
        if row.get("confirm_msg_id"):
            try:
                self.bot.edit(self.admin, row["confirm_msg_id"], text)
                return
            except Exception:
                log.exception("edit failed")
        self.notify(text)

    def _reply(self, msg_id, text):
        """Replace the button message with the result; send a new message if that fails."""
        try:
            self.bot.edit(self.admin, msg_id, text)
        except Exception:
            log.warning("edit failed, sending a new message", exc_info=True)
            self.notify(text)

    def _watch_daily_loss(self):
        if not self.journal.by_status(*ACTIVE):
            return
        hit = self.gate.daily_loss_hit()
        today = datetime.now().strftime("%Y-%m-%d")
        if hit and self.journal.get_kv("loss_warned", "") != today:
            self.journal.set_kv("loss_warned", today)
            self.notify(f"🛑 {hit}. Setup baru ditolak sampai besok. Posisi yang jalan tetap dijaga.")

    # --- buttons and commands (admin only) -----------------------------------
    def on_button(self, q: dict):
        if q["from"]["id"] != self.admin:
            return
        data = q.get("data", "")
        action, _, arg = data.partition(":")
        try:
            self.bot.answer(q["id"])   # only stops the button spinner; may fail if the tap arrived late
        except Exception:
            log.warning("answerCallbackQuery failed, continuing", exc_info=True)
        msg_id = q.get("message", {}).get("message_id")
        if action == "tutupsemua":
            text = "Dibatalkan, tidak ada yang ditutup."
            if arg == "ya":
                n = self.guard.close_all()
                text = f"🧯 {n} order/posisi ditutup atau dibatalkan."
            self._reply(msg_id, text)
            return
        if action == "hapuslimit":
            text = "Dibatalkan, limit tetap terpasang."
            if arg == "ya":
                n = self.guard.cancel_pending()
                text = f"🚫 {n} limit dihapus. Posisi yang sudah jalan tetap dijaga."
            self._reply(msg_id, text)
            return
        if action == "resetjurnal":
            text = "Dibatalkan, jurnal tidak diubah."
            if arg == "ya":
                text = self._reset_journal()
            self._reply(msg_id, text)
            return
        if action == "abaikan":
            self._reply(msg_id, "Diabaikan. SOP bot tetap berjalan.")
            return
        if action in ("batal", "tutup") and arg.isdigit():
            if action == "batal":
                n = self.guard.cancel_pending(int(arg))
                self._reply(msg_id, f"🚫 {n} limit setup #{arg} dibatalkan.")
            else:
                n = self.guard.close_setup(int(arg))
                self._reply(msg_id, f"🧯 Setup #{arg}: {n} order/posisi ditutup atau dibatalkan.")
            return
        if action not in ("ya", "tidak") or not arg.isdigit():
            return
        row = self.journal.get(int(arg))
        if row is None or row["status"] != AWAITING:
            self._reply(msg_id, f"Setup #{arg} sudah tidak menunggu konfirmasi.")
            return
        if action == "tidak":
            self.journal.update(row["id"], status=DECLINED, reason="Ditolak user")
            self._reply(msg_id, f"❌ Setup #{arg} kamu tolak.")
            return
        self._reply(msg_id, self._execute(row["id"]))

    def on_message(self, msg: dict):
        if msg.get("from", {}).get("id") != self.admin or msg["chat"]["id"] != self.admin:
            return
        parts = (msg.get("text") or "").strip().split()
        cmd = parts[0].lower().split("@")[0] if parts else ""
        if cmd == "/status":
            self.notify(self._status())
        elif cmd == "/stop":
            self.journal.set_kv("paused", True)
            n = self.guard.cancel_pending()
            self.notify(f"⏸ Bot stop. {n} limit dibatalkan. Posisi yang sudah jalan tetap dijaga. "
                        f"/lanjut untuk menyalakan lagi.")
        elif cmd == "/lanjut":
            self.journal.set_kv("paused", False)
            self.notify("▶️ Bot menerima setup lagi.")
        elif cmd == "/batal" and len(parts) > 1 and parts[1].lstrip("#").isdigit():   # not in HELP: /limit has buttons
            n = self.guard.cancel_pending(int(parts[1].lstrip("#")))
            self.notify(f"{n} limit setup #{parts[1].lstrip('#')} dibatalkan.")
        elif cmd == "/limit":
            self._list_limits()
        elif cmd == "/hapuslimit":
            ids = [r["id"] for r in self._with_limits()]
            if not ids:
                self.notify("Tidak ada limit yang terpasang.")
            else:
                self.notify("Yakin hapus semua limit yang belum ke-fill? Setup: " +
                            ", ".join(f"#{i}" for i in ids) + ". Posisi yang sudah jalan tidak disentuh.",
                            buttons=[[("🚫 Ya, hapus limit", "hapuslimit:ya"), ("Batal", "hapuslimit:tidak")]])
        elif cmd == "/tutupsemua":
            self.notify("Yakin tutup SEMUA posisi dan limit bot di harga pasar?",
                        buttons=[[("🧯 Ya, tutup semua", "tutupsemua:ya"), ("Batal", "tutupsemua:tidak")]])
        elif cmd == "/resetjurnal":
            busy = self._reset_blocked()
            if busy:
                self.notify(busy)
            else:
                self.notify(f"Yakin reset jurnal? Riwayat {len(self.journal.since(0))} setup dihapus "
                            f"(cek dobel ikut mulai dari nol, nomor setup mulai lagi dari #1), "
                            f"cadangan disimpan di folder data. "
                            f"Batas loss harian tidak ikut ter-reset (dihitung dari MT5).",
                            buttons=[[("🗑 Ya, reset", "resetjurnal:ya"), ("Batal", "resetjurnal:tidak")]])
        else:
            self.notify(HELP)

    def _with_limits(self):
        """Active setups that still have an unfilled order."""
        return [r for r in self.journal.by_status(*ACTIVE)
                if any(l["status"] == LEG_PENDING for l in self.journal.legs(r["id"]))]

    def _list_limits(self):
        rows = self._with_limits()
        if not rows:
            self.notify("Tidak ada limit yang terpasang.")
            return
        lines = ["📋 Limit yang menunggu:"]
        for r in rows:
            if r["status"] == RUNNING:
                when = "sebagian jalan"
            elif r["expires"]:
                end = datetime.fromtimestamp(r["expires"])
                when = "habis " + end.strftime("%H:%M" if end.date() == datetime.now().date() else "%d/%m %H:%M")
            else:
                when = ""
            lines.append(f"#{r['id']} {r['broker_symbol']} {r['side']} @ {r['entry']} · SL {r['sl']}"
                         + (f" · {when}" if when else ""))
        self.notify("\n".join(lines), buttons=[[(f"🚫 Batalkan #{r['id']}", f"batal:{r['id']}")] for r in rows])

    def _reset_blocked(self) -> str:
        """Why the journal cannot be reset now, or "" if it can."""
        active = self.journal.by_status(*ACTIVE)
        if not active:
            return ""
        return ("Belum bisa reset: masih ada setup aktif " + ", ".join(f"#{r['id']}" for r in active) +
                ". Tanpa jurnal, bot tidak bisa menjaganya (BE, trailing). "
                "Tunggu selesai, atau /hapuslimit / /tutupsemua dulu.")

    def _reset_journal(self) -> str:
        busy = self._reset_blocked()   # checked again: something may have been placed since the question
        if busy:
            return busy
        backup = backup_path(self.journal.path)
        n = self.journal.reset(backup)
        return f"🗑 Jurnal di-reset, {n} setup dihapus. Cadangan: {os.path.basename(backup)}"

    def _status(self) -> str:
        acc = self.broker.account()
        lines = [f"Saldo {acc.balance:.2f} · Equity {acc.equity:.2f} {acc.currency}",
                 "⏸ Mode stop" if self.journal.get_kv("paused", False) else "▶️ Menerima setup"]
        active = self.journal.by_status(*ACTIVE)
        if not active:
            lines.append("Tidak ada setup aktif.")
        for r in active:
            lines.append(f"#{r['id']} {r['broker_symbol']} {r['side']} {r['status']}, "
                         f"TP kena: {r['tp_level'] or 0}/{len(r['tps'])}, lot {r['total_lot']}")
        waiting = self.journal.by_status(AWAITING)
        if waiting:
            lines.append("Menunggu konfirmasi: " + ", ".join(f"#{r['id']}" for r in waiting))
        hit = self.gate.daily_loss_hit()
        if hit:
            lines.append(f"🛑 {hit}")
        return "\n".join(lines)
