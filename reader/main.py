"""Signal reader: watches the source channel with your Telegram account and posts
SETUP / UPDATE messages into the inbox channel, where the executor bot picks them up.

It never trades. It posts as your account (not as the bot) because a Telegram bot
does not receive the channel posts it makes itself.
"""
import argparse
import asyncio
import io
import logging
import os
import sys

from dotenv import load_dotenv

from copier.config import load_config

from .chart import build_setup
from .updates import build_update, is_highrisk

log = logging.getLogger("reader")


def _need(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise SystemExit(f"{name} belum diisi di file .env")
    return v


def _peer(value):
    """'-100123' / -100123 -> int id, anything else (a @username or t.me link) as is."""
    s = str(value).strip()
    return int(s) if s.lstrip("-").isdigit() else s


def topic_of(msg) -> int:
    """Forum topic a message belongs to. Messages in the General topic carry no topic: 1."""
    rt = getattr(msg, "reply_to", None)
    if rt is not None and getattr(rt, "forum_topic", False):
        return rt.reply_to_top_id or rt.reply_to_msg_id
    return 1


async def list_channels(client, source_id):
    from telethon import functions

    print("Channel yang kamu ikuti (salin ID-nya ke pembaca.channel_sumber di config.yaml):\n")
    async for d in client.iter_dialogs():
        if d.is_channel:
            print(f"  {d.id:>16}   {d.name}")
    if not source_id:
        return
    source = await client.get_entity(_peer(source_id))
    print(f"\nTopik di '{getattr(source, 'title', source_id)}' "
          f"(salin nomornya ke pembaca.topik_sumber di config.yaml):\n")
    if not getattr(source, "forum", False):
        print("  Grup/channel ini tidak memakai topik. Biarkan topik_sumber kosong.")
        return
    res = await client(functions.messages.GetForumTopicsRequest(
        peer=source, offset_date=None, offset_id=0, offset_topic=0, limit=100))
    for t in res.topics:
        if getattr(t, "title", None):
            print(f"  {t.id:>8}   {t.title}")


async def run(cfg: dict, find: bool):
    from telethon import TelegramClient, events

    p = cfg["pembaca"]
    client = TelegramClient("pembaca", int(_need("TG_API_ID")), _need("TG_API_HASH"))
    await client.start()   # first run asks for phone number and login code in this window
    if find:
        await client.get_dialogs()
        await list_channels(client, p["channel_sumber"])
        return

    if not p["channel_sumber"]:
        raise SystemExit("pembaca.channel_sumber di config.yaml belum diisi "
                         "(jalankan dengan --cari-channel untuk melihat ID-nya)")
    from .vision import GeminiReader
    gemini = GeminiReader(_need("GEMINI_API_KEY"), p["gemini_model"])
    await client.get_dialogs()   # fills the entity cache so numeric ids resolve
    source = await client.get_entity(_peer(p["channel_sumber"]))
    inbox = await client.get_entity(_peer(_need("TG_INBOX_CHANNEL_ID")))
    name = p["nama_sumber"]
    topic = int(p["topik_sumber"]) if p.get("topik_sumber") else None

    @client.on(events.NewMessage(chats=source))
    async def on_message(event):
        msg = event.message
        if topic and topic_of(msg) != topic:
            return   # another topic of the same group: not signals
        try:
            if msg.photo or (msg.document and (msg.file.mime_type or "").startswith("image/")):
                await on_image(msg)
            elif msg.raw_text:
                text = build_update(msg.raw_text, p, name)
                if text:
                    await client.send_message(inbox, text)
                    log.info("update diteruskan: %s", text.splitlines()[2])
        except Exception:
            log.exception("gagal memproses pesan %s", msg.id)
            await client.send_message(inbox, f"UPDATE\nSumber: {name}\nAksi: INFO\n"
                                             f"Teks: Pembaca error di pesan {msg.id}, cek logs/pembaca.log")

    async def on_image(msg):
        image = await msg.download_media(file=bytes)
        mime = msg.file.mime_type or "image/jpeg"
        caption = msg.raw_text or ""
        try:
            read = await asyncio.to_thread(gemini.read, image, mime)
            setup, why = build_setup(read, p, name, highrisk=is_highrisk(caption, p))
        except Exception as e:   # quota, network, unreadable reply
            log.exception("gemini gagal")
            setup, why = None, f"Gemini gagal: {e}"[:300]
        photo = io.BytesIO(image)
        photo.name = "sinyal.jpg"
        if setup:
            await client.send_file(inbox, photo, caption=setup)
            log.info("setup diposting:\n%s", setup)
        else:
            note = f" Caption: {' '.join(caption.split())[:300]}" if caption else ""
            await client.send_file(inbox, photo, caption=f"UPDATE\nSumber: {name}\nAksi: INFO\n"
                                                         f"Teks: Gambar tidak dijadikan setup ({why}).{note}")
            log.info("gambar dilewati: %s", why)

    log.info("Pembaca jalan, menonton %s%s. Tutup jendela untuk berhenti.",
             getattr(source, "title", p["channel_sumber"]), f" topik {topic}" if topic else "")
    await client.run_until_disconnected()


def try_image(cfg: dict, path: str):
    """Read one image file with Gemini and show the SETUP it would post. No Telegram."""
    from .vision import GeminiReader
    p = cfg["pembaca"]
    with open(path, "rb") as f:
        image = f.read()
    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    read = GeminiReader(_need("GEMINI_API_KEY"), p["gemini_model"]).read(image, mime)
    print(f"Dibaca Gemini: {read}\n")
    setup, why = build_setup(read, p, p["nama_sumber"])
    print(setup if setup else f"Tidak dijadikan setup: {why}")


def main():
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler("logs/pembaca.log", encoding="utf-8")])
    logging.getLogger("telethon").setLevel(logging.WARNING)
    load_dotenv()
    ap = argparse.ArgumentParser(description="Pembaca sinyal: channel sumber -> channel kotak masuk")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--cari-channel", action="store_true", help="tampilkan ID channel yang kamu ikuti")
    ap.add_argument("--coba-gambar", metavar="FILE", help="baca satu gambar dengan Gemini, tanpa Telegram")
    a = ap.parse_args()
    if a.coba_gambar:
        try_image(load_config(a.config), a.coba_gambar)
        return
    asyncio.run(run(load_config(a.config), a.cari_channel))


if __name__ == "__main__":
    main()
