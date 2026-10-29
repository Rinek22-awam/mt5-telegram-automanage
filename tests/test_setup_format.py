import pytest

from copier.setup_format import is_setup_post, parse_number, parse_setup

BUY = """SETUP
Pair: XAUUSD
Arah: BUY
Entry: 3987.26
SL: 3981.26
TP1: 3993.26
TP2: 3999.26
TP3: 4005.26
Sumber: outlook_gold"""


@pytest.mark.parametrize("txt,val", [
    ("3987.26", 3987.26), ("3.987,26", 3987.26), ("3,987.26", 3987.26), ("1,2700", 1.27),
    ("3.987.260", 3987260.0), ("$20", 20.0), ("4000", 4000.0), ("abc", None), ("", None),
])
def test_parse_number(txt, val):
    assert parse_number(txt) == val


def test_basic_buy():
    s, err = parse_setup(BUY)
    assert err == []
    assert (s.symbol, s.side, s.entry, s.sl, s.order_type) == ("XAUUSD", "BUY", 3987.26, 3981.26, "LIMIT")
    assert s.tps == [3993.26, 3999.26, 4005.26] and s.source == "outlook_gold"


def test_indonesian_numbers_and_aliases():
    s, err = parse_setup("📥 SETUP\nsimbol = gold\narah = jual\nentry: 3.987,260\nsl: 3.995,000\n"
                         "tp 2: 3.970,000\ntp 1: 3.980,000\nentry2: 3.990,000\nsl2: 4.000,000")
    assert err == []
    assert s.symbol == "GOLD" and s.side == "SELL" and s.entry == 3987.26
    assert s.tps == [3980.0, 3970.0]          # nearest first
    assert s.entry2 == 3990.0 and s.sl2 == 4000.0


def test_risk_override():
    s, _ = parse_setup(BUY + "\nRisk: 0.5%")
    assert (s.risk_mode, s.risk_value) == ("persen", 0.5)
    s, _ = parse_setup(BUY + "\nRisk: $20")
    assert (s.risk_mode, s.risk_value) == ("dolar", 20.0)
    _, err = parse_setup(BUY + "\nRisk: banyak")
    assert err and "Risk" in err[0]


def test_market_order_needs_no_entry():
    s, err = parse_setup("SETUP\nPair: XAUUSD\nArah: BUY\nOrder: MARKET\nSL: 3980\nTP1: 4010")
    assert err == [] and s.entry is None and s.order_type == "MARKET"


@pytest.mark.parametrize("text", ["halo semua", "", "XAUUSD BUY 3987 SL 3980\nSETUP"])
def test_not_a_setup(text):
    assert not is_setup_post(text) and parse_setup(text) == (None, [])


def test_recap_mentioning_setup_on_first_line_is_reported_not_traded():
    s, err = parse_setup("Recap minggu ini: SETUP bagus")
    assert s is None and err


def test_errors_are_listed():
    s, err = parse_setup("SETUP\nPair: XAUUSD\nArah: naik\nEntry: 3987\nTP1: 3990")
    assert s is None
    assert any("Arah" in e for e in err) and any("SL" in e for e in err)


def test_wrong_side():
    _, err = parse_setup(BUY.replace("SL: 3981.26", "SL: 3990"))
    assert any("SL" in e for e in err)
    _, err = parse_setup(BUY.replace("TP1: 3993.26", "TP1: 3980"))
    assert any("TP" in e for e in err)
