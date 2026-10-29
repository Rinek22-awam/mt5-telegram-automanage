"""Matching setup pair names to a broker's MT5 symbol names."""
import shutil
from types import SimpleNamespace as NS

import pytest

from panel import symbols
from panel.settings import Settings
from panel.symbols import candidates, search_names


def sym(name, visible=True, trade_mode=4, description=""):
    return NS(name=name, visible=visible, trade_mode=trade_mode, description=description)


EXNESS_DEMO = [sym("XAUUSDm"), sym("XAUUSD247m", visible=False), sym("XAUEURm"), sym("BTCUSDm"),
               sym("BTCUSDTm"), sym("EURUSDm"), sym("GBPUSDm"), sym("USDJPYm")]
EXNESS_CENT = [sym("XAUUSDc"), sym("BTCUSDc"), sym("EURUSDc"), sym("GBPUSDc"), sym("USDJPYc")]
OTHER = [sym("GOLD"), sym("GOLD.c", trade_mode=0), sym("BTCUSD.raw"), sym("EURUSD.raw"),
         sym("EURUSD.raw2"), sym("GBPUSD"), sym("USDJPY"), sym("XAGUSD")]


def names(key, syms):
    return [s.name for s in candidates(key, syms)]


def test_exness_demo_prefers_plain_suffix_over_247():
    assert names("XAUUSD", EXNESS_DEMO) == ["XAUUSDm", "XAUUSD247m"]
    assert names("BTCUSD", EXNESS_DEMO) == ["BTCUSDm", "BTCUSDTm"]
    assert names("EURUSD", EXNESS_DEMO) == ["EURUSDm"]


def test_cent_account():
    assert names("XAUUSD", EXNESS_CENT) == ["XAUUSDc"]
    assert names("GOLD", EXNESS_CENT) == ["XAUUSDc"]


def test_broker_that_calls_gold_gold_and_disabled_symbols():
    assert names("XAUUSD", OTHER) == ["GOLD"]          # GOLD.c is disabled for trading
    assert names("BTCUSD", OTHER) == ["BTCUSD.raw"]
    assert names("EURUSD", OTHER) == ["EURUSD.raw", "EURUSD.raw2"]
    assert names("GBPUSD", OTHER) == ["GBPUSD"]        # exact name first
    assert names("XAUEUR", EXNESS_DEMO) == ["XAUEURm"]   # unknown pairs still match by name


def test_search_names():
    assert search_names("xauusd") == ["XAUUSD", "GOLD"]
    assert search_names("GOLD") == ["GOLD", "XAUUSD"]
    assert search_names("EURUSD") == ["EURUSD"]


@pytest.fixture
def settings(tmp_path):
    p = tmp_path / "config.yaml"
    shutil.copy("config.yaml", p)
    s = Settings(str(p))
    for k, v in {"XAUUSD": "XAUUSDm", "GOLD": "XAUUSDm", "BTCUSD": "BTCUSDm",
                 "EURUSD": "EURUSDm", "GBPUSD": "GBPUSDm", "USDJPY": "USDJPYm"}.items():
        s.set(("simbol", k), v)
    return s


def run_screen(monkeypatch, settings, syms, answers):
    fake = NS(account_info=lambda: NS(login=1, server="Broker", currency="USC"),
              symbols_get=lambda: tuple(syms))
    monkeypatch.setattr(symbols, "_connect", lambda: (fake, ""))
    monkeypatch.setattr(symbols, "clear", lambda: None)
    replies = iter(answers)
    monkeypatch.setattr(symbols, "ask", lambda *_: next(replies, ""))
    monkeypatch.setattr(symbols, "pause", lambda: None)
    symbols.match_screen(settings)
    return settings.cfg()["simbol"]


def test_switch_to_cent_account_saves_everything(monkeypatch, settings):
    m = run_screen(monkeypatch, settings, EXNESS_CENT, ["y"])
    assert m["XAUUSD"] == m["GOLD"] == "XAUUSDc" and m["BTCUSD"] == "BTCUSDc"
    assert m["USDJPY"] == "USDJPYc"


def test_ambiguous_pick_and_refuse_to_save(monkeypatch, settings):
    m = run_screen(monkeypatch, settings, OTHER, ["2", "t"])     # EURUSD.raw2, then don't save
    assert m["EURUSD"] == "EURUSDm"
    m = run_screen(monkeypatch, settings, OTHER, ["2", "y"])
    assert m["EURUSD"] == "EURUSD.raw2" and m["XAUUSD"] == "GOLD"


def test_missing_pair_is_left_alone(monkeypatch, settings):
    m = run_screen(monkeypatch, settings, [sym("XAUUSDc")], ["y"])
    assert m["XAUUSD"] == "XAUUSDc" and m["BTCUSD"] == "BTCUSDm"
