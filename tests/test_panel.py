"""Menu pieces that do not need a console: config editing and input checking."""
import shutil

import pytest
import yaml

from panel.settings import SECTIONS, Settings, _get, parse
from panel.yamledit import add_value, fmt, remove_value, set_value


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.yaml"
    shutil.copy("config.yaml", p)
    return p


def comments(text):
    return [l[l.index("#"):] for l in text.splitlines() if "#" in l]


def test_every_setting_path_exists_in_config():
    cfg = Settings("config.yaml").cfg()
    for _, items in SECTIONS:
        for path, *_ in items:
            assert _get(cfg, path) is not None or path == ("pengaman", "loss_harian_dolar"), path


def test_set_keeps_comments_and_reloads(cfg_file):
    s = Settings(str(cfg_file))
    before = cfg_file.read_text(encoding="utf-8")
    s.set(("risiko", "mode"), "dolar")
    s.set(("risiko", "dolar"), 25.0)
    s.set(("tp", "bagi", "3"), [60, 25, 15])
    s.set(("pengaman", "loss_harian_dolar"), None)
    after = cfg_file.read_text(encoding="utf-8")
    assert comments(after) == comments(before)
    c = s.cfg()
    assert (c["risiko"]["mode"], c["risiko"]["dolar"], c["tp"]["bagi"][3]) == ("dolar", 25.0, [60, 25, 15])


def test_refuses_to_write_a_broken_config(cfg_file):
    s = Settings(str(cfg_file))
    before = cfg_file.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        s.set(("risiko", "mode"), "bebas")       # the bot would refuse to start
    assert cfg_file.read_text(encoding="utf-8") == before


def test_symbols_add_edit_remove(cfg_file):
    s = Settings(str(cfg_file))
    s.save(add_value(s.load_text(), ("simbol",), "ETHUSD", "ETHUSDc"))
    s.set(("simbol", "XAUUSD"), "XAUUSDc")
    s.save(remove_value(s.load_text(), ("simbol", "EURUSD")))
    m = s.cfg()["simbol"]
    assert m["ETHUSD"] == "ETHUSDc" and m["XAUUSD"] == "XAUUSDc" and "EURUSD" not in m


@pytest.mark.parametrize("kind,options,raw,value", [
    ("bool", None, "y", True), ("bool", None, "tidak", False),
    ("choice", ["persen", "dolar"], "2", "dolar"), ("choice", ["persen", "dolar"], "PERSEN", "persen"),
    ("float", (0.01, 20), "1,5", 1.5), ("int", (0, 10), "2", 2),
    ("float_or_null", (0.01, 100), "", None), ("float_or_null", (0.01, 100), "25", 25.0),
    ("split", 3, "50 30 20", [50, 30, 20]), ("split", 3, "50/30/20", [50, 30, 20]),
])
def test_parse_accepts(kind, options, raw, value):
    assert parse(kind, options, raw) == value


@pytest.mark.parametrize("kind,options,raw", [
    ("bool", None, "mungkin"), ("choice", ["persen", "dolar"], "3"), ("float", (0.01, 20), "50"),
    ("float", (0.01, 20), "abc"), ("split", 3, "50 50"), ("split", 3, "50 -30 20"), ("text", None, ""),
])
def test_parse_rejects(kind, options, raw):
    with pytest.raises(ValueError):
        parse(kind, options, raw)


def test_fmt_quotes_what_yaml_would_misread():
    assert fmt("-1004307070844") == '"-1004307070844"'
    assert fmt("sonnet") == "sonnet" and fmt("yes") == '"yes"'
    assert yaml.safe_load(f"a: {fmt('-1004307070844')}")["a"] == "-1004307070844"


def test_set_value_unknown_key():
    with pytest.raises(KeyError):
        set_value("a:\n  b: 1\n", ("a", "c"), 2)


def test_reset_journal_menu(monkeypatch, tmp_path):
    from copier.journal import Journal
    from copier.models import Setup
    from panel import main
    db = tmp_path / "jurnal.db"
    j = Journal(str(db))
    sid = j.add_setup(Setup("XAUUSD", "BUY", 3990, 3980, [4000]), "running")
    j.db.close()
    cfg = {"bot": {"jurnal": str(db)}}
    answers = iter(["salah", "RESET"])
    monkeypatch.setattr(main, "ask", lambda _: next(answers))
    monkeypatch.setattr(main, "pause", lambda: None)
    monkeypatch.setattr(main, "bot_on", lambda: False)

    main.reset_journal(cfg)                              # active setup: refused before asking
    assert len(Journal(str(db)).since(0)) == 1
    j = Journal(str(db))
    j.update(sid, status="done")
    j.db.close()
    main.reset_journal(cfg)                              # wrong word: unchanged
    assert len(Journal(str(db)).since(0)) == 1 and not list(tmp_path.glob("jurnal-cadangan-*"))
    main.reset_journal(cfg)
    assert not Journal(str(db)).since(0) and len(list(tmp_path.glob("jurnal-cadangan-*"))) == 1
