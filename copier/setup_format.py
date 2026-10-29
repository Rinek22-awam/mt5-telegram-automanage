"""Reader for the standard setup format posted to the inbox channel.

    SETUP
    Pair: XAUUSD
    Arah: BUY
    Entry: 3987.26
    SL: 3981.26
    TP1: 3993.26
    TP2: 3999.26
    TP3: 4005.26
    Sumber: outlook_gold

Optional lines: Order (LIMIT/STOP/MARKET), Entry2, SL2, Risk ("0.5%" or "$20"),
Highrisk (ya/tidak), Catatan.

Updates from a source use their own header:

    UPDATE
    Sumber: outlook_gold
    Aksi: CANCEL          # INFO | CANCEL | CLOSE
    Teks: cancel order gold

Keys are case-insensitive; ":" or "=" both work. Numbers may use Indonesian style
("3.987,26") or plain ("3987.26").
"""
import re
from typing import List, Optional, Tuple

from .models import Setup

_HEADER = re.compile(r"\bSETUP\b", re.I)
_UPDATE_HEADER = re.compile(r"\bUPDATE\b", re.I)
_YES = ("YA", "YES", "Y", "TRUE", "1")
UPDATE_ACTIONS = ("INFO", "CANCEL", "CLOSE")
_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 ]*?)\s*[:=]\s*(.+?)\s*$")
_TP_KEY = re.compile(r"^TP\s*(\d+)$")
_SIDES = {"BUY": "BUY", "LONG": "BUY", "BELI": "BUY",
          "SELL": "SELL", "SHORT": "SELL", "JUAL": "SELL"}
_ORDER_TYPES = ("LIMIT", "STOP", "MARKET")
_KEYS = {"PAIR": "pair", "SIMBOL": "pair", "SYMBOL": "pair",
         "ARAH": "side", "SIDE": "side", "POSISI": "side",
         "ENTRY": "entry", "ENTRY1": "entry", "ENTRY 1": "entry",
         "ENTRY2": "entry2", "ENTRY 2": "entry2",
         "SL": "sl", "SL1": "sl", "SL 1": "sl", "STOP LOSS": "sl",
         "SL2": "sl2", "SL 2": "sl2",
         "TP": "tp", "ORDER": "order", "TIPE": "order",
         "RISK": "risk", "RISIKO": "risk",
         "SUMBER": "source", "SOURCE": "source",
         "HIGHRISK": "highrisk", "HIGH RISK": "highrisk",
         "CATATAN": "note", "NOTE": "note"}


def parse_number(text: str) -> Optional[float]:
    """'3987.26', '3.987,26', '3,987.26', '1,2700' -> float. None if not a number."""
    s = re.sub(r"[\s$]", "", text or "")
    if not re.fullmatch(r"\d[\d.,]*", s):
        return None
    dots, commas = s.count("."), s.count(",")
    if dots and commas:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        grp = "," if dec == "." else "."
        s = s.replace(grp, "").replace(dec, ".")
    elif commas:
        s = s.replace(",", ".") if commas == 1 else s.replace(",", "")
    elif dots > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_risk(text: str) -> Optional[Tuple[str, float]]:
    t = text.strip().upper()
    num = parse_number(re.sub(r"(%|\$|USD|USC|DOLAR|PERSEN)", "", t))
    if num is None or num <= 0:
        return None
    if "%" in t or "PERSEN" in t:
        return "persen", num
    if "$" in t or "USD" in t or "USC" in t or "DOLAR" in t:
        return "dolar", num
    return None


def is_setup_post(text: str) -> bool:
    first = next((l for l in (text or "").splitlines() if l.strip()), "")
    return bool(_HEADER.search(first))


def parse_setup(text: str) -> Tuple[Optional[Setup], List[str]]:
    """Return (setup, errors). (None, []) means the post is not a setup at all."""
    if not is_setup_post(text):
        return None, []
    errors: List[str] = []
    vals, tps = {}, {}
    for line in text.splitlines()[1:]:
        m = _LINE.match(line)
        if not m:
            continue
        key, val = re.sub(r"\s+", " ", m.group(1).strip().upper()), m.group(2)
        tp = _TP_KEY.match(key.replace(" ", ""))
        if tp:
            tps[int(tp.group(1))] = val
            continue
        name = _KEYS.get(key)
        if name == "tp":
            tps[len(tps) + 1] = val
        elif name:
            vals[name] = val

    pair = re.sub(r"[^A-Za-z0-9._]", "", vals.get("pair", "")).upper()
    if not pair:
        errors.append("Pair belum diisi")
    side = _SIDES.get(vals.get("side", "").strip().upper())
    if not side:
        errors.append("Arah harus BUY atau SELL")
    order = vals.get("order", "LIMIT").strip().upper()
    if order not in _ORDER_TYPES:
        errors.append("Order harus LIMIT, STOP, atau MARKET")

    def num(name, label, required):
        if name not in vals:
            if required:
                errors.append(f"{label} belum diisi")
            return None
        v = parse_number(vals[name])
        if v is None or v <= 0:
            errors.append(f"{label} bukan angka: {vals[name]}")
        return v

    entry = num("entry", "Entry", required=order != "MARKET")
    sl = num("sl", "SL", required=True)
    entry2 = num("entry2", "Entry2", required=False)
    sl2 = num("sl2", "SL2", required=False)

    tp_list = []
    for i in sorted(tps):
        v = parse_number(tps[i])
        if v is None or v <= 0:
            errors.append(f"TP{i} bukan angka: {tps[i]}")
        else:
            tp_list.append(v)
    if not tps:
        errors.append("Minimal satu TP")

    risk_mode = risk_value = None
    if "risk" in vals:
        r = parse_risk(vals["risk"])
        if r:
            risk_mode, risk_value = r
        else:
            errors.append(f"Risk harus seperti 0.5% atau $20: {vals['risk']}")

    if errors:
        return None, errors

    if entry is not None:
        if side == "BUY" and sl >= entry or side == "SELL" and sl <= entry:
            errors.append("SL ada di sisi yang salah dari Entry")
        wrong = [t for t in tp_list if (t <= entry if side == "BUY" else t >= entry)]
        if wrong:
            errors.append("TP ada di sisi yang salah dari Entry: " + ", ".join(map(str, wrong)))
    else:
        bad = [t for t in tp_list if (t <= sl if side == "BUY" else t >= sl)]
        if bad:
            errors.append("TP ada di sisi yang salah dari SL")
    if len(set(tp_list)) != len(tp_list):
        errors.append("Ada TP yang sama")
    if errors:
        return None, errors

    tp_list.sort(reverse=(side == "SELL"))
    return Setup(symbol=pair, side=side, entry=entry if order != "MARKET" else None, sl=sl,
                 tps=tp_list, order_type=order, entry2=entry2, sl2=sl2,
                 risk_mode=risk_mode, risk_value=risk_value,
                 source=vals.get("source", "").strip(), note=vals.get("note", "").strip(),
                 highrisk=vals.get("highrisk", "").strip().upper() in _YES, raw=text), []


def parse_update(text: str) -> Optional[dict]:
    """UPDATE post -> {"action", "source", "text"}; None if the post is not an update."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    if not lines or not _UPDATE_HEADER.search(lines[0]) or _HEADER.search(lines[0]):
        return None
    vals = {}
    for line in lines[1:]:
        m = _LINE.match(line)
        if m:
            vals[m.group(1).strip().upper()] = m.group(2)
    action = vals.get("AKSI", vals.get("ACTION", "INFO")).strip().upper()
    return {"action": action if action in UPDATE_ACTIONS else "INFO",
            "source": vals.get("SUMBER", vals.get("SOURCE", "")).strip(),
            "text": vals.get("TEKS", vals.get("TEXT", "")).strip()}
