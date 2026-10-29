"""Match the pair names used in setups (XAUUSD, BTCUSD...) to this broker's MT5 names.

Run once after changing broker or account: it proposes, you approve, it saves to
config.yaml. The bot itself never guesses while trading; it only uses the saved table.
"""
import re
from typing import List

from .ui import ask, clear, pause, title

# other names brokers use for the same instrument
ALIASES = {
    "XAUUSD": ["GOLD", "XAUUSD"],
    "XAGUSD": ["SILVER", "XAGUSD"],
    "BTCUSD": ["BTCUSD", "XBTUSD", "BITCOIN"],
    "ETHUSD": ["ETHUSD", "ETHEREUM"],
    "US30": ["US30", "DJ30", "DOWJONES", "WS30"],
    "NAS100": ["NAS100", "USTEC", "US100", "NDX100"],
    "USOIL": ["USOIL", "WTI", "XTIUSD", "CRUDE"],
}
_ALIAS_OF = {a: k for k, names in ALIASES.items() for a in names}
MAX_EXTRA = 4   # letters a broker may add around the name: m, c, .raw, 247m ...


def norm(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def search_names(key: str) -> List[str]:
    """XAUUSD -> [XAUUSD, GOLD]; GOLD -> [GOLD, XAUUSD]."""
    k = norm(key)
    base = _ALIAS_OF.get(k, k)
    names = [k] + [n for n in ALIASES.get(base, [base]) if n != k]
    return names


def candidates(key: str, symbols) -> List:
    """Broker symbols that are this instrument, best first.

    `symbols`: objects with .name, .visible, .trade_mode (MT5 symbol_info).
    Ranked by: exact name, then fewest extra letters, then shown in Market Watch,
    then the name as written in the setup before its aliases.
    """
    found = []
    order = search_names(key)
    for s in symbols:
        if getattr(s, "trade_mode", 1) == 0:    # SYMBOL_TRADE_MODE_DISABLED
            continue
        n = norm(s.name)
        for rank, token in enumerate(order):
            if n.startswith(token) and len(n) - len(token) <= MAX_EXTRA:
                extra = n[len(token):]
                found.append((extra != "", len(extra), not s.visible, rank, s.name, s))
                break
    found.sort(key=lambda t: t[:5])
    return [t[-1] for t in found]


def _connect():
    try:
        import MetaTrader5 as m
    except ImportError:
        return None, "paket MetaTrader5 belum terpasang"
    if not m.initialize():
        return None, f"tidak tersambung ke MT5 desktop: {m.last_error()}"
    return m, ""


def match_screen(settings):
    clear()
    title("COCOKKAN NAMA PAIR DENGAN BROKER")
    m, err = _connect()
    if m is None:
        print(f"  [X] {err}\n  Buka MT5 dan login ke akun yang mau dipakai, lalu coba lagi.")
        pause()
        return
    a = m.account_info()
    symbols = m.symbols_get() or ()
    print(f"  Akun MT5: {a.login} {a.server} ({a.currency}), {len(symbols)} simbol\n")

    mapping = settings.cfg()["simbol"]
    plan = {}
    for key, current in mapping.items():
        found = candidates(key, symbols)
        names = [s.name for s in found]
        ok_now = current in names
        if not found:
            print(f"  {key:<8} tidak ditemukan di broker ini (sekarang: {current}) -> dibiarkan")
            continue
        if ok_now:   # still valid here: keep it; change by hand in the symbol screen if wanted
            print(f"  {key:<8} -> {current:<14} (tetap, ada di broker ini)")
            continue
        if len(found) == 1:
            plan[key] = names[0]
            print(f"  {key:<8} -> {names[0]:<14} (sebelumnya {current})")
            continue
        print(f"\n  {key}: {current} tidak ada di broker ini, ada {len(found)} kemungkinan:")
        for i, s in enumerate(found[:9], 1):
            desc = getattr(s, "description", "") or ""
            star = "  <- usulan" if i == 1 else ""
            print(f"     {i}. {s.name:<14} {desc[:34]}{star}")
        raw = ask("     Pilih nomor (Enter = usulan, 0 = jangan diubah): ")
        if raw == "0":
            continue
        pick = int(raw) - 1 if raw.isdigit() and 1 <= int(raw) <= min(len(found), 9) else 0
        plan[key] = names[pick]

    changes = {k: v for k, v in plan.items() if mapping.get(k) != v}
    print()
    if not changes:
        print("  Semua nama sudah cocok. Tidak ada yang diubah.")
        pause()
        return
    print("  Akan disimpan:")
    for k, v in changes.items():
        print(f"     {k:<8} {mapping[k]} -> {v}")
    if ask("\n  Simpan? (y/t): ").lower() not in ("y", "ya"):
        print("  Tidak disimpan.")
        pause()
        return
    for k, v in changes.items():
        settings.set(("simbol", k), v)
    print("  Tersimpan.")
    if settings.bot_running():
        print("  Bot sedang jalan: nyalakan ulang supaya nama baru dipakai.")
    pause()
