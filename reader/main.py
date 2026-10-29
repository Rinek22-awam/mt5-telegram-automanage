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
import re
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


def save_source(path: str, channel: str, topic) -> None:
    """Write pembaca.channel_sumber / topik_sumber into config.yaml, keeping its comments."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text, n1 = re.subn(r'(?m)^(  channel_sumber:[ \t]*)("[^"\n]*"|[^\s#]+)', rf'\g<1>"{channel}"', text)
    text, n2 = re.subn(r'(?m)^(  topik_sumber:[ \t]*)([^\s#]+)',
                       rf'\g<1>{topic if topic else "null"}', text)
    if not (n1 and n2):
        raise ValueError("baris channel_sumber / topik_sumber tidak ditemukan di config.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


async def find_source(client, current: str, config_path: str):
    """List channels, ask which one, list its topics, optionally save both to config."""
    from telethon import functions

    print("Channel dan grup yang kamu ikuti:\n")
    async for d in client.iter_dialogs():
        if d.is_channel:
            print(f"  {d.id:>16}   {d.name}")
    print(f"\nSumber di config sekarang: {current or '(kosong)'}")
    chosen = input("Ketik ID channel yang mau dicek (Enter = pakai yang di config): ").strip() or current
    if not chosen:
        return
    try:
        source = await client.get_entity(_peer(chosen))
    except (ValueError, TypeError):
        print(f"\n[X] ID {chosen} tidak ditemukan di daftar. Pastikan akunmu sudah join channel itu.")
        return
    title = getattr(source, "title", chosen)
    topics = {}
    if getattr(source, "forum", False):
        res = await client(functions.messages.GetForumTopicsRequest(
            peer=source, offset_date=None, offset_id=0, offset_topic=0, limit=100))
        topics = {t.id: t.title for t in res.topics if getattr(t, "title", None)}
        print(f"\nTopik di '{title}':\n")
        for tid, name in topics.items():
            print(f"  {tid:>8}   {name}")
        answer = input("\nKetik nomor topik sinyal untuk disimpan ke config "
                       "(0 = semua topik, Enter = tidak disimpan): ").strip()
    else:
        print(f"\n'{title}' tidak memakai topik: semua pesannya akan dibaca.")
        answer = "0" if input("Simpan sebagai sumber di config? (y/n): ").strip().lower() == "y" else ""
    if not answer:
        print("Config tidak diubah.")
        return
    if not answer.isdigit() or (answer != "0" and int(answer) not in topics):
        print(f"[X] Nomor topik {answer} tidak ada di daftar. Config tidak diubah.")
        return
    topic = int(answer) or None
    save_source(config_path, str(chosen), topic)
    print(f"\nTersimpan: channel_sumber = {chosen}, topik_sumber = {topic or 'semua'}"
          f"{' (' + topics[topic] + ')' if topic else ''}.")
    print("Restart pembaca (tutup jendelanya, klik dua kali Nyalakan Pembaca.bat) supaya berlaku.")


async def run(cfg: dict, find: bool, config_path: str = "config.yaml"):
    from telethon import TelegramClient, events

    p = cfg["pembaca"]
    client = TelegramClient("pembaca", int(_need("TG_API_ID")), _need("TG_API_HASH"))
    await client.start()   # first run asks for phone number and login code in this window
    if find:
        await client.get_dialogs()
        await find_source(client, str(p["channel_sumber"] or ""), config_path)
        return

    if not p["channel_sumber"]:
        raise SystemExit("pembaca.channel_sumber di config.yaml belum diisi "
                         "(jalankan dengan --cari-channel untuk melihat ID-nya)")
    from .vision import ClaudeReader
    eye = ClaudeReader(p["claude_model"])
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
            read = await asyncio.to_thread(eye.read, image, mime)
            setup, why = build_setup(read, p, name, highrisk=is_highrisk(caption, p))
        except Exception as e:   # quota, network, unreadable reply
            log.exception("claude gagal")
            setup, why = None, f"Claude gagal membaca: {e}"[:300]
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
    """Read one image file with Claude and show the SETUP it would post. No Telegram."""
    from .vision import ClaudeReader
    p = cfg["pembaca"]
    with open(path, "rb") as f:
        image = f.read()
    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    read = ClaudeReader(p["claude_model"]).read(image, mime)
    print(f"Dibaca Claude: {read}\n")
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
    ap.add_argument("--coba-gambar", metavar="FILE", help="baca satu gambar dengan Claude, tanpa Telegram")
    a = ap.parse_args()
    if a.coba_gambar:
        try_image(load_config(a.config), a.coba_gambar)
        return
    asyncio.run(run(load_config(a.config), a.cari_channel, a.config))


if __name__ == "__main__":
    main()
