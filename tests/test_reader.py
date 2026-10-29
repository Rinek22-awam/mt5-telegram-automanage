"""Reader logic without Telegram or Gemini: model JSON -> SETUP, text -> UPDATE."""
from copier.config import with_defaults
from copier.setup_format import parse_setup, parse_update
from reader.chart import build_setup, symbol_for
from reader.updates import build_update, classify, is_highrisk
from reader.vision import parse_reply

P = with_defaults({})["pembaca"]

# what the model should return for contoh_sinyal/01_outlook_tradingview_gold.png
OUTLOOK_01 = {"is_signal": True, "entries": ["3.987,260", "3.985,460"], "sl": "3.981,260",
              "tps": ["(4.017,260)", "4.011,260", "4.005,260", "3.999,260", "3.993,260"],
              "symbol_text": "", "highrisk": False}


def test_outlook_01_becomes_a_valid_buy_setup():
    text, why = build_setup(OUTLOOK_01, P, "outlook")
    assert why == ""
    s, err = parse_setup(text)
    assert err == []
    assert (s.symbol, s.side, s.entry, s.entry2, s.sl) == ("XAUUSD", "BUY", 3987.26, 3985.46, 3981.26)
    assert s.tps == [3993.26, 3999.26, 4005.26, 4011.26, 4017.26]
    assert s.source == "outlook" and not s.highrisk


def test_sell_takes_lowest_entry():
    read = {"is_signal": True, "entries": ["4.010,0", "4.012,5"], "sl": "4.020,0",
            "tps": ["4.000,0", "3.990,0"]}
    s, _ = parse_setup(build_setup(read, P, "x")[0])
    assert (s.side, s.entry, s.entry2, s.tps) == ("SELL", 4010.0, 4012.5, [4000.0, 3990.0])


def test_btc_by_price_or_by_label():
    read = {"is_signal": True, "entries": ["112,450.5"], "sl": "111,900", "tps": ["113,000"]}
    s, _ = parse_setup(build_setup(read, P, "x")[0])
    assert s.symbol == "BTCUSD" and s.entry == 112450.5
    assert symbol_for(112000, P["simbol_dari_harga"], "BTCUSDT") == "BTCUSD"
    assert symbol_for(3990, P["simbol_dari_harga"], "BTCUSDT") == "XAUUSD"   # prices win over a misread label
    assert symbol_for(3990, P["simbol_dari_harga"], "") == "XAUUSD"
    assert symbol_for(50, P["simbol_dari_harga"], "") is None


def test_highrisk_from_caption_or_image():
    s, _ = parse_setup(build_setup(OUTLOOK_01, P, "o", highrisk=True)[0])
    assert s.highrisk
    s, _ = parse_setup(build_setup({**OUTLOOK_01, "highrisk": True}, P, "o")[0])
    assert s.highrisk


def test_unusable_reads_are_explained():
    assert build_setup({"is_signal": False}, P, "o") == (None, "bukan gambar sinyal")
    assert "tidak lengkap" in build_setup({**OUTLOOK_01, "sl": ""}, P, "o")[1]
    assert "di antara" in build_setup({**OUTLOOK_01, "sl": "3.986,000"}, P, "o")[1]
    assert "sisi yang salah" in build_setup({**OUTLOOK_01, "tps": ["3.970,0"]}, P, "o")[1]
    assert "simbol" in build_setup({**OUTLOOK_01, "entries": ["50"], "sl": "40", "tps": ["60"]},
                                   P, "o")[1]


def test_parse_reply_tolerates_fences():
    assert parse_reply('```json\n{"is_signal": false}\n```') == {"is_signal": False}
    assert parse_reply('{"is_signal": true, "entries": []}')["is_signal"] is True


def test_text_updates():
    assert classify("Gold TP1 hit +60 pips 🔥", P) == "INFO"
    assert classify("Cancel setup gold ya", P) == "CANCEL"
    assert classify("Close now, market berbalik", P) == "CLOSE"
    assert classify("closed at TP2", P) == "INFO"          # whole words only
    assert is_highrisk("Setup ini HIGH RISK, lot kecil aja", P)
    assert not is_highrisk("risk management penting", P)
    u = parse_update(build_update("Cancel\nsetup gold", P, "outlook"))
    assert u == {"action": "CANCEL", "source": "outlook", "text": "Cancel setup gold"}
    assert build_update("   ", P, "outlook") is None


def test_ambiguous_thousands_resolved_by_price_range():
    # "111,900" alone could be 111.9; only 111900 fits a known symbol
    read = {"is_signal": True, "entries": ["112,450"], "sl": "111,900", "tps": ["113,000", "114,000"]}
    s, _ = parse_setup(build_setup(read, P, "x")[0])
    assert (s.symbol, s.entry, s.sl, s.tps) == ("BTCUSD", 112450.0, 111900.0, [113000.0, 114000.0])
    # Indonesian style gold stays as it was
    s, _ = parse_setup(build_setup(OUTLOOK_01, P, "x")[0])
    assert s.entry == 3987.26
