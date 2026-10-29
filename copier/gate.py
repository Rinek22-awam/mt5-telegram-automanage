"""Gate: basic checks, journal checks (duplicate / similar), and safety limits."""
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .models import ACTIVE, AWAITING, Setup


@dataclass
class Market:
    symbol: str          # broker symbol
    bid: float
    ask: float
    kind: str            # order type actually used: LIMIT | STOP | MARKET


@dataclass
class Verdict:
    ok: bool
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    market: Optional[Market] = None


class Gate:
    def __init__(self, cfg: dict, broker, journal, clock=time.time):
        self.cfg, self.broker, self.journal, self.clock = cfg, broker, journal, clock
        self.g = cfg["gerbang"]

    def broker_symbol(self, raw: str) -> Optional[str]:
        name = self.cfg["simbol"].get(raw.upper(), raw)
        return name if self.broker.symbol_info(name) is not None else None

    def check(self, s: Setup, posted: Optional[float] = None, skip_id: Optional[int] = None,
              recheck: bool = False) -> Verdict:
        """Full gate. `recheck` = run again right before executing (after confirmation)."""
        v = Verdict(ok=True)
        self._safety(v)
        sym = self.broker_symbol(s.symbol)
        if sym is None:
            v.reasons.append(f"Simbol {s.symbol} tidak ada di MT5 (cek bagian simbol di config.yaml)")
            return _done(v)
        if not recheck:
            self._journal(s, sym, skip_id, v)
            if posted is not None:
                age = (self.clock() - posted) / 60
                if age > self.g["umur_maks_setup_menit"]:
                    v.reasons.append(f"Setup basi ({age:.0f} menit)")
        self._market(s, sym, v)
        return _done(v)

    # --- pieces -------------------------------------------------------------
    def _safety(self, v: Verdict):
        p = self.cfg["pengaman"]
        if self.journal.get_kv("paused", False):
            v.reasons.append("Bot sedang di-stop (/lanjut untuk menyalakan lagi)")
        active = len(self.journal.by_status(*ACTIVE))
        if active >= p["maks_setup_aktif"]:
            v.reasons.append(f"Sudah {active} setup aktif (maksimal {p['maks_setup_aktif']})")
        hit = self.daily_loss_hit()
        if hit:
            v.reasons.append(hit)

    def daily_loss_hit(self) -> str:
        p = self.cfg["pengaman"]
        # any symbol that exists will do: it only supplies the server clock
        clock_sym = next((m for m in self.cfg["simbol"].values()
                          if self.broker.symbol_info(m) is not None), None)
        if clock_sym is None:
            return ""
        realized, floating, start = self.broker.day_pnl(clock_sym)
        loss = -(realized + floating)
        if loss <= 0:
            return ""
        if p.get("loss_harian_dolar") and loss >= float(p["loss_harian_dolar"]):
            return f"Batas loss harian tercapai ({loss:.2f})"
        if p.get("loss_harian_persen") and start > 0 and loss / start * 100 >= p["loss_harian_persen"]:
            return f"Batas loss harian tercapai ({loss / start * 100:.1f}%)"
        return ""

    def _journal(self, s: Setup, sym: str, skip_id, v: Verdict):
        since = self.clock() - self.g["dobel_jendela_jam"] * 3600
        for old in self.journal.since(since):
            if old["id"] == skip_id or old["broker_symbol"] != sym or old["side"] != s.side:
                continue
            same = (old["entry"] == s.entry and old["sl"] == s.sl and old["tps"] == s.tps)
            live = old["status"] in ACTIVE + (AWAITING,)
            if same and (live or old["status"] == "done"):
                v.reasons.append(f"Dobel dengan setup #{old['id']}")
                return
            if old["entry"] and s.entry and live:
                diff = abs(old["entry"] - s.entry) / s.entry * 100
                if diff <= self.g["mirip_jarak_entry_persen"]:
                    v.warnings.append(f"Mirip setup #{old['id']} ({old['status']}, "
                                      f"entry {old['entry']})")

    def _market(self, s: Setup, sym: str, v: Verdict):
        bid, ask, _ = self.broker.tick(sym)
        if bid <= 0 or ask <= 0:
            v.reasons.append("Harga tidak tersedia (market tutup?)")
            return
        kind = s.order_type
        if s.side == "BUY" and s.sl >= bid or s.side == "SELL" and s.sl <= ask:
            v.reasons.append("SL sudah terlewat oleh harga sekarang")
        tp1 = s.tps[0]
        if s.side == "BUY" and tp1 <= bid or s.side == "SELL" and tp1 >= ask:
            v.reasons.append("TP1 sudah terlewat oleh harga sekarang")
        if s.entry is not None and kind != "MARKET":
            mid = (bid + ask) / 2
            dev = abs(s.entry - mid) / mid * 100
            if dev > self.g["jarak_maks_dari_harga_persen"]:
                v.reasons.append(f"Entry {dev:.2f}% dari harga sekarang "
                                 f"(maks {self.g['jarak_maks_dari_harga_persen']}%)")
            price = ask if s.side == "BUY" else bid
            passed = (price <= s.entry if s.side == "BUY" else price >= s.entry) if kind == "LIMIT" \
                else (price >= s.entry if s.side == "BUY" else price <= s.entry)
            if passed:
                if self.cfg["entry"]["jika_harga_sudah_lewat"] == "market":
                    kind = "MARKET"
                    v.warnings.append(f"Harga sudah melewati entry, masuk market di {price}")
                else:
                    v.reasons.append("Harga sudah melewati entry")
            gap = self.broker.min_stop_distance(sym)
            if gap and kind != "MARKET" and abs(s.entry - s.sl) < gap:
                v.reasons.append("Jarak SL terlalu dekat untuk aturan broker")
        v.market = Market(sym, bid, ask, kind)


def _done(v: Verdict) -> Verdict:
    v.ok = not v.reasons
    return v
