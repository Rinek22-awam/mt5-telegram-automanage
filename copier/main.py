import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from .config import load_config
from .single import BOT_PORT, claim
from .telegram import TelegramBot

log = logging.getLogger("copier")


def _need(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise SystemExit(f"{name} belum diisi di file .env")
    return v


def find_ids(bot: TelegramBot):
    """Print chat ids seen by the bot, to fill TG_INBOX_CHANNEL_ID and TG_ADMIN_USER_ID."""
    print("Kirim satu postingan di channel kotak masuk, dan kirim /start ke bot di chat pribadi.")
    print("Lalu tekan Enter di sini...")
    input()
    for u in bot.get_updates(0, wait=0):
        m = u.get("channel_post") or u.get("message") or {}
        chat = m.get("chat", {})
        who = m.get("from", {})
        if chat.get("type") == "channel":
            print(f"Channel  '{chat.get('title')}'  ->  TG_INBOX_CHANNEL_ID={chat['id']}")
        elif chat.get("type") == "private":
            print(f"Chat pribadi dengan {who.get('first_name')}  ->  TG_ADMIN_USER_ID={who.get('id')}")


def main():
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler("logs/bot.log", encoding="utf-8")])
    load_dotenv()
    ap = argparse.ArgumentParser(description="Eksekutor setup dari channel Telegram ke MT5")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--cari-id", action="store_true", help="tampilkan ID channel dan ID kamu")
    a = ap.parse_args()

    lock = claim(BOT_PORT)   # held until this program exits
    if lock is None:
        raise SystemExit("Bot sudah jalan di jendela lain. Tutup dulu jendela itu kalau mau menyalakan ulang.")
    bot = TelegramBot(_need("TG_BOT_TOKEN"))
    if a.cari_id:
        find_ids(bot)
        return

    from .app import App
    from .broker import Broker
    from .journal import Journal

    cfg = load_config(a.config)
    broker = Broker(cfg)
    if not broker.connect(os.getenv("MT5_LOGIN"), os.getenv("MT5_PASSWORD"),
                          os.getenv("MT5_SERVER"), os.getenv("MT5_PATH")):
        raise SystemExit("Tidak bisa terhubung ke MT5. Pastikan MT5 desktop terbuka dan sudah login.")
    journal = Journal(cfg["bot"]["jurnal"])
    app = App(cfg, broker, journal, bot, int(_need("TG_INBOX_CHANNEL_ID")),
              int(_need("TG_ADMIN_USER_ID")))
    if not app.startup_checks():
        raise SystemExit("Pemeriksaan awal gagal, lihat pesan di Telegram.")
    log.info("Bot jalan. Tekan Ctrl+C untuk berhenti.")
    try:
        app.run()
    except KeyboardInterrupt:
        app.notify("⏹ Bot dimatikan. Limit dan SL/TP tetap ada di MT5, tapi BE/trailing tidak dijaga.")


if __name__ == "__main__":
    main()
