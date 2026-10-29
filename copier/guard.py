"""Position keeper: follows every active setup in the journal and applies the SOP.

All state lives in the journal and in MT5 itself, so after a restart the guard simply
picks up where it left off: it re-reads each leg from MT5 and recomputes what the SL
should be. Failed SL moves are retried on the next pass.
"""
import logging

from .models import (CANCELLED, DONE, EXPIRED, LEG_CANCELLED, LEG_CLOSED, LEG_FINAL, LEG_OPEN,
                     LEG_PENDING, LEG_SL, LEG_TP, PENDING, RUNNING)

log = logging.getLogger(__name__)
RETRY_SEC = 15


class Guard:
    def __init__(self, cfg: dict, broker, journal, notify, clock):
        self.cfg, self.broker, self.journal, self.notify, self.clock = cfg, broker, journal, notify, clock
        self.sop = cfg["sop"]

    def run_once(self):
        for s in self.journal.by_status(PENDING, RUNNING):
            try:
                self._one(s)
            except Exception:  # one bad setup must not stop the others
                log.exception("guard failed on setup %s", s["id"])

    # --- per setup ----------------------------------------------------------
    def _one(self, s):
        sid, legs = s["id"], self.journal.legs(s["id"])
        live = {}
        for leg in legs:
            if leg["status"] in LEG_FINAL:
                continue
            st = self.broker.leg_state(leg["ticket"])
            self._sync_leg(s, leg, st)
            if st.state == "open":
                live[leg["id"]] = st
        legs = self.journal.legs(sid)

        if s["status"] == PENDING and any(l["status"] == LEG_OPEN or l["status"] in (LEG_TP, LEG_SL, LEG_CLOSED)
                                          for l in legs):
            self.journal.update(sid, status=RUNNING)
            s["status"] = RUNNING
            fills = [l["fill_price"] for l in legs if l["fill_price"]]
            self.notify(f"✅ #{sid} {s['broker_symbol']} {s['side']} ke-fill di {fills[0] if fills else '-'}")

        pending = [l for l in legs if l["status"] == LEG_PENDING]
        if pending and s["expires"] and self.clock() >= s["expires"] and s["status"] == PENDING:
            for l in pending:
                self.broker.cancel(l["ticket"])
            self.journal.event(sid, "expired", f"{len(pending)} limit dibatalkan")
            self.notify(f"⌛ #{sid} {s['broker_symbol']} limit tidak ke-fill dalam "
                        f"{self.cfg['entry']['limit_kedaluwarsa_jam']} jam, dibatalkan")
            return  # leg states are picked up as cancelled on the next pass

        if live:
            self._apply_sop(s, legs, live)

        if all(l["status"] in LEG_FINAL for l in self.journal.legs(sid)):
            self._finish(s)

    def _sync_leg(self, s, leg, st):
        sid = s["id"]
        if st.state == "open" and leg["status"] == LEG_PENDING:
            self.journal.update_leg(leg["id"], status=LEG_OPEN, fill_price=st.price, fill_time=st.time)
            self.journal.event(sid, "filled", f"kaki {leg['idx'] + 1} di {st.price}")
        elif st.state == "open" and not leg["fill_price"]:   # market legs: record the real fill
            self.journal.update_leg(leg["id"], fill_price=st.price, fill_time=st.time)
        elif st.state == "closed":
            status = {"tp": LEG_TP, "sl": LEG_SL}.get(st.reason, LEG_CLOSED)
            self.journal.update_leg(leg["id"], status=status, profit=st.profit,
                                    fill_price=leg["fill_price"] or st.open_price or None)
            self.journal.event(sid, status, f"kaki {leg['idx'] + 1} di {st.price}, {st.profit:+.2f}")
            label = {LEG_TP: f"🎯 TP{leg['idx'] + 1} kena", LEG_SL: "🛑 Kena SL"}.get(status, "Ditutup")
            self.notify(f"{label}: #{sid} {s['broker_symbol']} kaki {leg['idx'] + 1}, {st.profit:+.2f}")
        elif st.state == "cancelled":
            self.journal.update_leg(leg["id"], status=LEG_CANCELLED)
            self.journal.event(sid, "leg_cancelled", f"kaki {leg['idx'] + 1}")

    def _apply_sop(self, s, legs, live):
        sid, sym, side, tps = s["id"], s["broker_symbol"], s["side"], s["tps"]
        buy = side == "BUY"
        bid, ask, now_srv = self.broker.tick(sym)
        if bid <= 0:
            return
        exit_price = bid if buy else ask   # price a position closes at

        peak = s["peak"]
        if peak is None:   # first look (or after restart): include moves we did not watch
            first_fill = min((st.time for st in live.values() if st.time), default=0)
            seen = self.broker.rates_extreme(sym, side, first_fill, now_srv) if first_fill else None
            if seen is not None and not buy:
                seen += ask - bid      # bars are bid prices; a SELL closes at ask
            peak = seen if seen is not None else exit_price
        peak = max(peak, exit_price) if buy else min(peak, exit_price)

        by_price = sum(1 for t in tps if (peak >= t if buy else peak <= t))
        by_legs = max((l["idx"] + 1 for l in legs if l["status"] == LEG_TP), default=0)
        level = max(by_price, by_legs, s["tp_level"] or 0)
        if level > (s["tp_level"] or 0):
            self.journal.event(sid, "tp_level", f"TP{level}")
            if by_legs < level:   # legs report their own TP; announce TPs without a leg here
                self.notify(f"🎯 #{sid} {sym} harga menyentuh TP{level}")
        self.journal.update(sid, peak=peak, tp_level=level)

        gap = self.broker.min_stop_distance(sym)
        for leg in legs:
            st = live.get(leg["id"])
            if st is None:
                continue
            want = self._wanted_sl(s, st.price, level)
            if want is None or (st.sl and (want <= st.sl if buy else want >= st.sl)):
                continue   # nothing to do, or SL is already at least this good
            if self.clock() < (leg["next_try"] or 0):
                continue
            room = (exit_price - want) if buy else (want - exit_price)
            if room <= 0:
                if self.sop["tutup_jika_sl_baru_terlewat"]:
                    ok, err = self.broker.close(leg["ticket"])
                    self._result(s, leg, ok, err, f"harga sudah melewati SL baru {want}, ditutup")
                continue
            if room < gap:
                continue   # too close for the broker right now, try again next pass
            ok, err = self.broker.modify_sl(sym, leg["ticket"], want, st.tp)
            self._result(s, leg, ok, err, f"SL kaki {leg['idx'] + 1} → {want}")

    def _wanted_sl(self, s, fill, level):
        buy, tps = s["side"] == "BUY", s["tps"]
        options = []
        be_after = self.sop["be_setelah_tp"]
        if be_after and level >= be_after:
            pad = abs(fill - s["sl"]) * float(self.sop["be_jarak_aman_r"])
            options.append(fill + pad if buy else fill - pad)
        if self.sop["trailing"] and level >= 2:
            options.append(tps[level - 2])
        if not options:
            return None
        return self.broker.normalize(s["broker_symbol"], max(options) if buy else min(options))

    def _result(self, s, leg, ok, err, what):
        sid = s["id"]
        if ok:
            self.journal.update_leg(leg["id"], next_try=0)
            self.journal.event(sid, "sop", what)
            self.notify(f"🔒 #{sid} {s['broker_symbol']}: {what}")
            return
        first = not leg["next_try"]
        self.journal.update_leg(leg["id"], next_try=self.clock() + RETRY_SEC)
        self.journal.event(sid, "sop_failed", f"{what}: {err}")
        if first:
            self.notify(f"⚠️ #{sid} {s['broker_symbol']}: gagal ({what}): {err}. Dicoba ulang.")

    def _finish(self, s):
        sid, legs = s["id"], self.journal.legs(s["id"])
        filled = [l for l in legs if l["status"] != LEG_CANCELLED]
        pnl = round(sum(l["profit"] or 0 for l in legs), 2)
        if not filled:
            status = EXPIRED if s["expires"] and self.clock() >= s["expires"] else CANCELLED
            self.journal.update(sid, status=status, pnl=0)
            return
        by_legs = max((l["idx"] + 1 for l in legs if l["status"] == LEG_TP), default=0)
        self.journal.update(sid, status=DONE, pnl=pnl, tp_level=max(by_legs, s["tp_level"] or 0))
        self.journal.event(sid, "done", f"{pnl:+.2f}")
        self.notify(f"🏁 #{sid} {s['broker_symbol']} {s['side']} selesai: {pnl:+.2f}")

    # --- manual controls ----------------------------------------------------
    def cancel_pending(self, setup_id=None) -> int:
        """Cancel unfilled orders (of one setup, or all). Returns how many were cancelled."""
        n = 0
        for s in self.journal.by_status(PENDING, RUNNING):
            if setup_id is not None and s["id"] != setup_id:
                continue
            for l in self.journal.legs(s["id"]):
                if l["status"] == LEG_PENDING and self.broker.cancel(l["ticket"])[0]:
                    n += 1
            self.journal.event(s["id"], "cancel_request", "")
        return n

    def close_setup(self, setup_id: int) -> int:
        """Cancel the unfilled orders and close the open positions of one setup."""
        n = self.cancel_pending(setup_id)
        for l in self.journal.legs(setup_id):
            if l["status"] == LEG_OPEN and self.broker.close(l["ticket"])[0]:
                n += 1
        return n

    def close_all(self) -> int:
        n = self.cancel_pending()
        for s in self.journal.by_status(PENDING, RUNNING):
            for l in self.journal.legs(s["id"]):
                if l["status"] == LEG_OPEN and self.broker.close(l["ticket"])[0]:
                    n += 1
        return n
