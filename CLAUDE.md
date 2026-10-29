# Proyek: Bot Eksekutor Sinyal Trading (MT5 / Exness)

Bot yang mengeksekusi sinyal trading **tanpa emosi** ke MT5 (Exness): limit entry, TP bertahap, SL, BE, trailing. Bot **tidak menganalisa**. Sinyal datang dari satu grup Telegram (gambar TradingView: garis biru = entry, merah = SL, hitam = TP), dibaca **Claude Code** (`claude -p`, langganan Pro user), lalu masuk ke satu channel privat "kotak masuk" dalam format standar `SETUP`, dan bot meminta konfirmasi user lewat tombol Telegram sebelum memasang order.

**Status:** tahap 1 selesai dibangun dan teruji di MT5 demo. User menjalankan sisa uji sendiri (BE/trailing di MT5 asli, dashboard desktop) sebelum live di akun cent.

## Device baru? Baca dulu

1. [INSTALL.md](INSTALL.md): langkah instal dari nol. Tuntun user satu langkah per giliran.
2. [README.md](README.md): cara kerja, SOP, menu, perintah bot.
3. [FORMAT_SETUP.md](FORMAT_SETUP.md): format `SETUP`/`UPDATE` kosong + contoh.
4. [DESKTOP.md](DESKTOP.md): dashboard desktop opsional (Trading Manager), hanya di branch `codex/desktop-manager` sampai digabung.
5. `STATUS_DAN_LANJUTAN.md`: posisi terakhir, semua keputusan, sisa tugas. **Tidak ada di repo** (catatan perencanaan sengaja tidak di-push); hanya di folder perencanaan PC lama `F:\Plan sistem trade\`. Kalau tidak ada, tanya user.

Pengecekan awal yang boleh Claude jalankan sendiri di device baru: `python --version`, `git --version`, `claude auth status`, `python -m pip install -r requirements.txt`, `python -m pytest -q`, dan isi `.env` hanya **terisi/kosong** (jangan pernah menampilkan nilainya).

## Aturan main

- **Bahasa Indonesia**, gaya santai. User bukan programmer: jelaskan dengan bahasa awam, satu langkah per giliran.
- **Helicopter view dulu**, detail teknis belakangan. Kalau user bertanya pendapat, jawab dulu; jangan langsung mengubah file.
- **Saat user sedang menguji bot, jelaskan masalah dan usulan perbaikan dulu, tunggu "ya" sebelum mengubah kode.**
- **Claude tidak mengeksekusi order** dan tidak menekan beli/jual. Claude menulis program; user yang menjalankan bot (`MENU.bat` atau Trading Manager).
- **Jangan minta atau menerima rahasia di chat**: token bot, API ID/hash Telegram, password, kode login, file `pembaca.session`. User mengisinya sendiri ke `.env`. ID channel/user bukan rahasia.
- **Paket/repo dari luar wajib dicek dulu** sebelum dipasang atau dijalankan.
- **Uji di akun demo** sebelum live. Live nanti di **akun cent Exness** (saldo USC; bot otomatis mengalikan nilai $ x100).
- Commit boleh dengan identitas git repo (`Rinek22-awam` + email noreply). **Push hanya dengan izin user** setiap kali.
- `config.yaml` lokal biasanya berisi **setelan uji user yang tidak di-commit**. Kalau perlu meng-commit kunci config baru, stage bagian itu saja.
- Jangan menjalankan bot/pembaca sungguhan dari sesi Claude; itu tugas user. Membaca MT5/Telegram untuk pengecekan (tanpa order) boleh, dan sebutkan kalau melakukannya.
- Di Windows PowerShell 5.1, tanda kutip di `git commit -m` rusak; tulis pesan ke file lalu `git commit -F`.

## Branch

| Branch | Isi |
|---|---|
| `tahap-1` | Versi utama yang sudah teruji di demo |
| `codex/desktop-manager` | `tahap-1` + dashboard desktop (dibuat dengan GPT/Codex, diperiksa Claude). Digabung ke `tahap-1` setelah lolos uji demo |
| `main` | Masih kode repo asal. Digabung setelah uji demo lolos |

## Peta kode

| Folder / file | Isi |
|---|---|
| `copier/` | Bot: format setup, gerbang, eksekutor, penjaga posisi (BE/trailing), jurnal SQLite, Telegram Bot API, pencegah jalan dobel |
| `reader/` | Pembaca: Telethon (akun user), Claude membaca gambar (`vision.py`, dikunci hanya tool Read), aturan arah/entry/simbol (`chart.py`), pesan teks → UPDATE |
| `panel/` | `MENU.bat`: Jalankan, Utilitas, Pengaturan SOP (edit `config.yaml` tanpa merusak komentar), cek kesiapan, reset jurnal |
| `desktop/` | *(branch dashboard)* Trading Manager PySide6. `engine.py` = turunan `App` yang meneruskan perintah ke handler Telegram asli; `control.py` = antrean perintah + snapshot (`data/desktop-control.db`). **Tidak boleh mengubah logika mesin** |
| `desktop_entry.py`, `build_desktop.py` | *(branch dashboard)* Titik masuk GUI dan pembuat `.exe` (PyInstaller, build ramping ±100 MB) |
| `tests/` | MT5 tiruan, Telegram tiruan, Claude tiruan. `python -m pytest -q` (tes Qt dilewati kalau `.desktop-deps` tidak ada) |
| `config.yaml` | Semua angka SOP. Rahasia di `.env` |

## Keputusan yang sudah dikunci

- Eksekusi oleh kode, bukan AI. AI (Claude) hanya **menyalin** angka dan warna dari gambar; arah, entry, simbol ditentukan kode, lalu dicek gerbang dan dikonfirmasi user.
- Kotak masuk = satu channel Telegram privat; bot hanya membaca channel itu. Pembaca memposting sebagai akun user (bot tidak menerima postingannya sendiri).
- Dua entry → pakai yang paling dekat ke TP. Dua SL → SL1. Highrisk → hanya ditandai ⚠️, risiko tetap. Update channel → bot ikut SOP sendiri; cancel/close hanya jadi tombol.
- Risiko dua mode: persen saldo atau nominal $; bisa ditimpa per setup (`Risk:`).
- Limit yang harganya sudah lewat TP1 → ⚠️ dan ditanya, bukan ditolak; market (dan stop yang jadi market) tetap ditolak.
- Mode TP: `partial` (pembagian per TP, boleh 0) atau `satu` (semua lot di TP ke-n). BE dan trailing selalu menurut harga, berdiri sendiri dari mode TP.
- Reset jurnal: cadangan otomatis di `data/`, nomor setup mulai lagi dari #1 (user terima risiko tombol Telegram lama).
- Risiko "sistem mati diam-diam" (MT5 putus / bot mati tanpa pemberitahuan) **diterima user**, karena SL/TP selalu terpasang di MT5.
- Gemini tidak dipakai (berbayar). OCR tidak dipakai (keputusan user).
- Bybit ditunda; MT5 duluan.

## Belum selesai (ringkas; rinciannya di STATUS)

- Uji user: BE/trailing di MT5 asli (termasuk SELL), limit kedaluwarsa 12 jam, sinyal live dari grup, dashboard dengan bot sungguhan.
- Sebelum live: tinjau setelan uji di `config.yaml` lokal (risiko, BE, maks setup, loss harian), akun cent (nama pair akhiran `c`, matikan "hanya demo"), gabung branch, tentukan PC atau VPS.
- Kecil: kata kunci pesan update/highrisk dari contoh asli grup; nama topik di log pembaca; dashboard "Bot _pembaca" dan log berulang saat MT5 putus.
- Ide (belum dieksekusi): pesan update dari grup masuk logika bot. Ditunda: Bybit, jalur 2 (analisa Claude dari TradingView), mode otomatis penuh.
