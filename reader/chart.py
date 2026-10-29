"""Turn what the vision model read off a chart image into a SETUP post.

The model only reports the labels it sees and their colour. Everything that decides
the trade (direction, which entry, which symbol) is plain code here, so it is the
same every time and can be tested.
"""
import re
from typing import List, Optional, Tuple

from copier.setup_format import parse_number

_NUM_CHARS = re.compile(r"[^\d.,]")
_GROUPED = re.compile(r"\d{1,3}([.,])\d{3}(\1\d{3})*")


def num(text, grouped: bool = False) -> Optional[float]:
    """Label -> number. `grouped` reads a lone separator before 3 digits ('111,900',
    '3.987') as a thousands mark instead of a decimal point."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = _NUM_CHARS.sub("", str(text))
    if grouped and _GROUPED.fullmatch(s):
        return float(re.sub(r"[.,]", "", s))
    return parse_number(s)


def symbol_for(price: float, ranges: List[dict], seen_text: str = "") -> Optional[str]:
    """Symbol written on the chart if it is a known one, else guess from the price level."""
    seen = re.sub(r"[^A-Z]", "", (seen_text or "").upper())
    for r in ranges:
        if seen and (seen == r["simbol"] or seen in [a.upper() for a in r.get("alias", [])]):
            if r["min"] <= price <= r["max"]:
                return r["simbol"]
    for r in ranges:
        if r["min"] <= price <= r["max"]:
            return r["simbol"]
    return None


def _numbers(read: dict, grouped: bool):
    entries = [v for v in (num(x, grouped) for x in read.get("entries") or []) if v]
    tps = [v for v in (num(x, grouped) for x in read.get("tps") or []) if v]
    return entries, num(read.get("sl"), grouped), tps


def build_setup(read: dict, cfg: dict, source: str, highrisk: bool = False) -> Tuple[Optional[str], str]:
    """read: the model's JSON. Returns (SETUP text, "") or (None, reason it was not a setup)."""
    if not read.get("is_signal"):
        return None, "bukan gambar sinyal"
    first_why = ""
    # labels like "111,900" are ambiguous: keep the reading whose prices match a known symbol
    for grouped in (False, True):
        text, why = _build(*_numbers(read, grouped), read, cfg, source, highrisk)
        if text:
            return text, ""
        first_why = first_why or why
    return None, first_why


def _build(entries, sl, tps, read, cfg, source, highrisk):
    if not entries or not sl or not tps:
        return None, (f"angka tidak lengkap (entry {len(entries)}, SL {'ada' if sl else 'tidak ada'}, "
                      f"TP {len(tps)})")
    if sl < min(entries):
        side = "BUY"
    elif sl > max(entries):
        side = "SELL"
    else:
        return None, "SL ada di antara entry, arah tidak jelas"
    buy = side == "BUY"
    if any((t <= max(entries) if buy else t >= min(entries)) for t in tps):
        return None, "ada TP di sisi yang salah"
    tps = sorted(set(tps), reverse=not buy)
    # nearest entry to the targets fills first: highest for BUY, lowest for SELL
    entries = sorted(set(entries), reverse=buy)
    entry, entry2 = entries[0], (entries[1] if len(entries) > 1 else None)
    symbol = symbol_for(entry, cfg["simbol_dari_harga"], read.get("symbol_text", ""))
    if symbol is None:
        return None, f"simbol tidak dikenali dari harga {entry}"

    lines = ["SETUP", f"Pair: {symbol}", f"Arah: {side}", f"Entry: {_fmt(entry)}"]
    if entry2:
        lines.append(f"Entry2: {_fmt(entry2)}")
    lines.append(f"SL: {_fmt(sl)}")
    lines += [f"TP{i + 1}: {_fmt(t)}" for i, t in enumerate(tps)]
    if highrisk or read.get("highrisk"):
        lines.append("Highrisk: ya")
    lines.append(f"Sumber: {source}")
    return "\n".join(lines), ""


def _fmt(v: float) -> str:
    return f"{v:.5f}".rstrip("0").rstrip(".")
