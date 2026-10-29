"""Main menu: one place to start the bot / reader and reach every tool and setting."""
import os
import sqlite3
import subprocess
import sys
from datetime import datetime

from dotenv import load_dotenv

from copier.config import load_config
from copier.journal import Journal, backup_path
from copier.models import ACTIVE
from copier.single import BOT_PORT, READER_PORT, is_running

from .settings import Settings
from .symbols import match_screen
from .ui import ask, choose, clear, pause, title

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS = {"received": "diterima", "rejected": "ditolak", "awaiting_confirm": "menunggu konfirmasi",
          "declined": "kamu tolak", "pending": "limit terpasang", "running": "berjalan",
          "done": "selesai", "cancelled": "dibatalkan", "expired": "kedaluwarsa"}


def bot_on():
    return is_running(BOT_PORT)


def reader_on():
    return is_running(READER_PORT)


def launch(window_title: str, module: str):
    """Start a program in its own window; the window stays open after it stops."""
    cmd = (f'start "{window_title}" cmd /c "python -m {module} & echo. & '
           f'echo {window_title} berhenti. Tutup jendela ini. & pause >nul"')
    subprocess.Popen(cmd, shell=True, cwd=ROOT)


def here(*args):
    """Run a tool in this window and wait for it."""
    subprocess.call([sys.executable, *args], cwd=ROOT)


def header():
    clear()
    title("BOT EKSEKUTOR SINYAL - MENU")
    cfg = load_config(os.path.join(ROOT, "config.yaml"))
    r, p = cfg["risiko"], cfg["pembaca"]
    risk = f"{r['persen']}% saldo" if r["mode"] == "persen" else f"${r['dolar']} per setup"
    src = p["channel_sumber"] or "belum dipilih"
    topic = f" topik {p['topik_sumber']}" if p.get("topik_sumber") else ""
    print(f"  Bot     : {'● jalan' if bot_on() else '○ mati'}")
    print(f"  Pembaca : {'● jalan' if reader_on() else '○ mati'}")
    print(f"  Sumber  : {src}{topic}")
    print(f"  Risiko  : {risk}   |   Akun: {'hanya demo' if cfg['akun']['hanya_demo'] else 'REAL boleh'}\n")
    return cfg


# --- Jalankan -----------------------------------------------------------------
def start_menu():
    while True:
        header()
        print("  JALANKAN\n")
        pick = choose(["Bot saja", "Bot + Pembaca"], back="Kembali")
        if pick is None:
            return
        started = []
        if bot_on():
            print("\n  Bot sudah jalan.")
        else:
            launch("Bot Eksekutor", "copier.main")
            started.append("bot")
        if pick == 1:
            if reader_on():
                print("  Pembaca sudah jalan.")
            else:
                launch("Pembaca Sinyal", "reader.main")
                started.append("pembaca")
        if started:
            print(f"\n  Membuka jendela {' dan '.join(started)}. Biarkan jendelanya terbuka;")
            print("  tutup jendelanya untuk mematikan. Pastikan MT5 terbuka dan Algo Trading hijau.")
        pause()
        return


# --- Utilitas -----------------------------------------------------------------
def pick_source():
    if reader_on():
        print("\n  Pembaca sedang jalan. Tutup dulu jendela pembaca, lalu coba lagi.")
        pause()
        return
    here("-m", "reader.main", "--cari-channel")
    pause()


def try_image():
    print("\n  Seret file gambar sinyal ke jendela ini, lalu tekan Enter.")
    path = ask("  File: ").strip().strip('"')
    if not path:
        return
    if not os.path.isfile(path):
        print(f"  [X] File tidak ditemukan: {path}")
    else:
        print("\n  Membaca dengan Claude, tunggu 10-30 detik...\n")
        here("-m", "reader.main", "--coba-gambar", path)
    pause()


def readiness(cfg):
    from .check import run_all
    print("  Mengecek, tunggu sebentar...\n")
    run_all(cfg)
    pause()


def history(cfg):
    db = os.path.join(ROOT, cfg["bot"]["jurnal"])
    if not os.path.exists(db):
        print("\n  Jurnal masih kosong.")
        pause()
        return
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute("SELECT id, created, symbol, side, status, pnl, reason FROM setups "
                       "ORDER BY id DESC LIMIT 15").fetchall()
    print("\n  15 setup terakhir:\n")
    for sid, created, sym, side, status, pnl, reason in rows:
        when = datetime.fromtimestamp(created).strftime("%d/%m %H:%M")
        money = f"{pnl:+.2f}" if pnl is not None else ""
        why = f"  ({reason[:45]})" if reason else ""
        print(f"  #{sid:<4} {when}  {sym:<7} {side:<4} {STATUS.get(status, status):<20} {money}{why}")
    pause()


def reset_journal(cfg):
    if bot_on():
        print("\n  Bot sedang jalan. Tutup dulu jendela bot, lalu coba lagi.")
        pause()
        return
    db = os.path.join(ROOT, cfg["bot"]["jurnal"])
    if not os.path.exists(db):
        print("\n  Jurnal masih kosong.")
        pause()
        return
    journal = Journal(db)
    try:
        active = journal.by_status(*ACTIVE)
        if active:
            print("\n  Masih ada setup aktif (limit terpasang / posisi jalan): " +
                  ", ".join(f"#{r['id']}" for r in active))
            print("  Kalau jurnal dihapus, bot tidak bisa menjaganya lagi (BE, trailing).")
            print("  Tunggu selesai, atau batalkan/tutup lewat Telegram dulu, lalu coba lagi.")
            pause()
            return
        total = len(journal.since(0))
        backup = backup_path(db)
        print(f"\n  Reset jurnal menghapus riwayat {total} setup (cek dobel ikut mulai dari nol).")
        print(f"  Cadangan disimpan dulu ke: {backup}")
        print("  Nomor setup berikutnya tetap lanjut. Batas loss harian tidak ikut ter-reset (dihitung dari MT5).")
        if ask("\n  Ketik RESET untuk lanjut: ") != "RESET":
            print("  Dibatalkan, jurnal tidak diubah.")
            pause()
            return
        journal.reset(backup)
        print(f"\n  Jurnal sudah kosong. {total} setup dihapus, cadangan aman.")
    finally:
        journal.db.close()
    pause()


def find_ids():
    if bot_on():
        print("\n  Bot sedang jalan. Tutup dulu jendela bot, lalu coba lagi.")
        pause()
        return
    here("-m", "copier.main", "--cari-id")
    pause()


def run_tests():
    here("-m", "pytest", "-q")
    pause()


def tools_menu():
    settings = Settings(os.path.join(ROOT, "config.yaml"), bot_running=bot_on)
    while True:
        cfg = header()
        print("  UTILITAS\n")
        pick = choose(["Pilih channel & topik sumber sinyal",
                       "Pengaturan SOP (risiko, TP, BE, trailing, pengaman, simbol)",
                       "Cocokkan nama pair dengan broker (setelah ganti broker/akun)",
                       "Coba baca gambar sinyal (tanpa Telegram)",
                       "Cek kesiapan (MT5, Telegram, Claude)",
                       "Riwayat setup",
                       "Reset jurnal trade (hapus riwayat, ada cadangan)",
                       "Cari ID Telegram (kotak masuk & ID kamu)",
                       "Tes logika program"], back="Kembali")
        if pick is None:
            return
        [pick_source, settings.run, lambda: match_screen(settings), try_image,
         lambda: readiness(cfg), lambda: history(cfg), lambda: reset_journal(cfg),
         find_ids, run_tests][pick]()


def main():
    for stream in (sys.stdout, sys.stderr):   # symbols like ● on any Windows console
        stream.reconfigure(encoding="utf-8", errors="replace")
    os.chdir(ROOT)
    load_dotenv(os.path.join(ROOT, ".env"))
    while True:
        header()
        pick = choose(["Jalankan", "Utilitas"], back="Keluar")
        if pick is None:
            return
        [start_menu, tools_menu][pick]()


if __name__ == "__main__":
    main()
