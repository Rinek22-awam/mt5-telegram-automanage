"""Reader logic without Telegram or Claude: model JSON -> SETUP, text -> UPDATE."""
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


def test_topic_of_forum_messages():
    from types import SimpleNamespace as NS
    from reader.main import topic_of
    assert topic_of(NS(reply_to=None)) == 1                                   # General topic
    assert topic_of(NS(reply_to=NS(forum_topic=True, reply_to_top_id=None, reply_to_msg_id=42))) == 42
    # a reply inside topic 42 points at the replied message; the topic is reply_to_top_id
    assert topic_of(NS(reply_to=NS(forum_topic=True, reply_to_top_id=42, reply_to_msg_id=977))) == 42
    assert topic_of(NS(reply_to=NS(forum_topic=False, reply_to_top_id=None, reply_to_msg_id=5))) == 1


def test_claude_reader_is_locked_down_and_cleans_up(tmp_path):
    import json, os
    from types import SimpleNamespace as NS
    from reader.vision import ClaudeReader
    seen = {}

    def fake_run(cmd, cwd, **kw):
        seen.update(cmd=cmd, cwd=cwd, files=os.listdir(cwd))
        reply = '```json\n{"is_signal": true, "entries": ["3.987,260"], "sl": "3.981,260", "tps": ["3.993,260"]}\n```'
        return NS(stdout=json.dumps({"is_error": False, "result": reply}), stderr="")

    r = ClaudeReader("sonnet", workdir=str(tmp_path), run=fake_run)
    read = r.read(b"\x89PNG...", "image/png")
    assert read["entries"] == ["3.987,260"] and read["sl"] == "3.981,260"
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "Read"            # no Bash, Edit, Write, web...
    assert "--strict-mcp-config" in cmd and cmd[cmd.index("--setting-sources") + 1] == "project"
    assert seen["files"] == ["sinyal.png"]                    # Claude's folder holds only the image
    assert os.listdir(tmp_path) == []                         # and is removed afterwards


def test_claude_reader_reports_errors(tmp_path):
    import json
    from types import SimpleNamespace as NS
    import pytest
    from reader.vision import ClaudeReader

    def expired(cmd, cwd, **kw):
        return NS(stdout=json.dumps({"is_error": True, "result": "OAuth session expired"}), stderr="")
    with pytest.raises(RuntimeError, match="OAuth"):
        ClaudeReader(workdir=str(tmp_path), run=expired).read(b"x")

    def garbage(cmd, cwd, **kw):
        return NS(stdout="not json", stderr="")
    with pytest.raises(RuntimeError, match="JSON"):
        ClaudeReader(workdir=str(tmp_path), run=garbage).read(b"x")


def test_save_source_keeps_comments(tmp_path):
    import shutil
    import yaml
    from reader.main import save_source
    cfg = tmp_path / "config.yaml"
    shutil.copy("config.yaml", cfg)
    save_source(str(cfg), "-1004307070844", 12)
    text = cfg.read_text(encoding="utf-8")
    p = yaml.safe_load(text)["pembaca"]
    assert (p["channel_sumber"], p["topik_sumber"]) == ("-1004307070844", 12)
    assert "# ID channel sinyal" in text and "# grup bertopik" in text
    save_source(str(cfg), "-1004307070844", None)
    assert yaml.safe_load(cfg.read_text(encoding="utf-8"))["pembaca"]["topik_sumber"] is None


class _FakeClient:
    """Just enough of a Telethon client for find_source."""
    def __init__(self, forum=True):
        from types import SimpleNamespace as NS
        self.NS, self.forum = NS, forum

    async def iter_dialogs(self):
        yield self.NS(is_channel=True, id=-1004307070844, name="Tes Rinek")

    async def get_entity(self, peer):
        if peer != -1004307070844:
            raise ValueError("not found")
        return self.NS(title="Tes Rinek", forum=self.forum)

    async def __call__(self, request):
        NS = self.NS
        return NS(topics=[NS(id=1, title="General"), NS(id=12, title="Sinyal")])


def _find(monkeypatch, tmp_path, answers, forum=True):
    import asyncio
    import shutil
    from reader.main import find_source
    cfg = tmp_path / "config.yaml"
    shutil.copy("config.yaml", cfg)
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_: next(replies))
    asyncio.run(find_source(_FakeClient(forum), "-1002631236672", str(cfg)))
    import yaml
    return yaml.safe_load(cfg.read_text(encoding="utf-8"))["pembaca"]


def test_find_source_lists_topics_and_saves(monkeypatch, tmp_path, capsys):
    p = _find(monkeypatch, tmp_path, ["-1004307070844", "12"])
    out = capsys.readouterr().out
    assert "12   Sinyal" in out and "Tersimpan" in out
    assert (p["channel_sumber"], p["topik_sumber"]) == ("-1004307070844", 12)


def test_find_source_enter_changes_nothing(monkeypatch, tmp_path):
    p = _find(monkeypatch, tmp_path, ["-1004307070844", ""])
    assert (p["channel_sumber"], p["topik_sumber"]) == ("-1002631236672", 78395)


def test_find_source_rejects_unknown_topic_and_channel(monkeypatch, tmp_path, capsys):
    p = _find(monkeypatch, tmp_path, ["-1004307070844", "999"])
    assert p["topik_sumber"] == 78395 and "tidak ada di daftar" in capsys.readouterr().out
    p = _find(monkeypatch, tmp_path, ["-100111", ""])
    assert p["channel_sumber"] == "-1002631236672" and "tidak ditemukan" in capsys.readouterr().out


def test_find_source_without_topics(monkeypatch, tmp_path):
    p = _find(monkeypatch, tmp_path, ["-1004307070844", "y"], forum=False)
    assert (p["channel_sumber"], p["topik_sumber"]) == ("-1004307070844", None)
