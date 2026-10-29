"""Readiness check: is everything in place to run the bot and the reader? Read-only."""
import json
import os
import subprocess

from copier.single import BOT_PORT, READER_PORT, is_running

OK, BAD, WARN = "✅", "❌", "⚠️"


def _line(mark, text):
    print(f"  {mark} {text}")


def env_keys():
    print("File .env")
    keys = {"TG_BOT_TOKEN": "token bot", "TG_INBOX_CHANNEL_ID": "ID kotak masuk",
            "TG_ADMIN_USER_ID": "ID kamu", "TG_API_ID": "API Telegram (pembaca)",
            "TG_API_HASH": "API hash Telegram (pembaca)"}
    for k, label in keys.items():
        _line(OK if os.getenv(k, "").strip() else BAD, f"{label} ({k})")


def telegram_bot():
    print("\nBot Telegram")
    from copier.telegram import TelegramBot
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not token:
        _line(BAD, "token belum diisi")
        return
    try:
        me = TelegramBot(token, timeout=10).call("getMe")
        _line(OK, f"tersambung sebagai @{me['username']}")
    except Exception as e:
        _line(BAD, f"tidak tersambung: {e}")


def mt5(cfg):
    print("\nMT5")
    try:
        import MetaTrader5 as m
    except ImportError:
        _line(BAD, "paket MetaTrader5 belum terpasang")
        return
    if not m.initialize():
        _line(BAD, f"tidak tersambung ke MT5 desktop: {m.last_error()}")
        return
    a, t = m.account_info(), m.terminal_info()
    demo = a.trade_mode == m.ACCOUNT_TRADE_MODE_DEMO
    _line(OK if demo or not cfg["akun"]["hanya_demo"] else BAD,
          f"akun {a.login} {a.server}: {'DEMO' if demo else 'REAL'}, saldo {a.balance:.2f} {a.currency}"
          + ("" if demo or not cfg["akun"]["hanya_demo"] else " (config: hanya_demo, bot akan menolak)"))
    _line(OK if a.margin_mode == m.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING else BAD, "tipe akun hedging")
    _line(OK if t.trade_allowed else BAD, "tombol Algo Trading " + ("nyala" if t.trade_allowed else
                                                                 "MATI (klik sampai hijau)"))
    missing = sorted({v for v in cfg["simbol"].values() if m.symbol_info(v) is None})
    _line(WARN if missing else OK, "simbol di config ada di MT5" if not missing
          else "tidak ada di MT5: " + ", ".join(missing))


def claude_cli():
    print("\nClaude (mata pembaca)")
    try:
        p = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        st = json.loads(p.stdout)
    except FileNotFoundError:
        _line(BAD, "Claude Code (perintah claude) belum terpasang")
        return
    except Exception as e:
        _line(BAD, f"tidak bisa cek: {e}")
        return
    if st.get("loggedIn"):
        _line(OK, f"login ({st.get('subscriptionType', '?')})")
    else:
        _line(BAD, "belum login: buka PowerShell, ketik  claude auth login")


def reader(cfg):
    print("\nPembaca")
    p = cfg["pembaca"]
    _line(OK if os.path.exists("pembaca.session") else BAD,
          "login Telegram pembaca" + ("" if os.path.exists("pembaca.session")
                                      else " belum (Utilitas > Pilih channel & topik)"))
    _line(OK if p["channel_sumber"] else BAD,
          f"sumber: {p['channel_sumber'] or 'belum dipilih'}"
          + (f", topik {p['topik_sumber']}" if p.get("topik_sumber") else ", semua topik"))


def running():
    print("\nSedang jalan")
    _line(OK if is_running(BOT_PORT) else "○", "bot " + ("jalan" if is_running(BOT_PORT) else "mati"))
    _line(OK if is_running(READER_PORT) else "○",
          "pembaca " + ("jalan" if is_running(READER_PORT) else "mati"))


def run_all(cfg):
    env_keys()
    telegram_bot()
    mt5(cfg)
    claude_cli()
    reader(cfg)
    running()
