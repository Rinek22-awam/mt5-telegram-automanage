# Proyek: Bot Eksekutor Sinyal Trading (MT5 / Exness)

Bot yang mengeksekusi sinyal trading **tanpa emosi** ke MT5 (Exness): limit entry, TP bertahap, SL, BE, trailing. Bot **tidak menganalisa**. Sinyal datang dari satu grup Telegram (gambar TradingView: garis biru = entry, merah = SL, hitam = TP), dibaca **Claude Code** (`claude -p`, langganan Pro user), lalu masuk ke satu channel privat "kotak masuk" dalam format standar `SETUP`, dan bot meminta konfirmasi user lewat tombol Telegram sebelum memasang order.

## Device baru? Baca dulu

1. [INSTALL.md](INSTALL.md): langkah instal dari nol. Tuntun user satu langkah per giliran.
2. [README.md](README.md): cara kerja, format `SETUP`/`UPDATE`, SOP, menu.
3. `STATUS_DAN_LANJUTAN.md` (di `docs/` kalau sudah disalin, atau di folder perencanaan lama `F:\Plan sistem trade\`): posisi terakhir dan apa yang menunggu jawaban user.

Pengecekan awal yang boleh Claude jalankan sendiri di device baru: `python --version`, `git --version`, `claude auth status`, `python -m pip install -r requirements.txt`, `python -m pytest -q`, dan isi `.env` hanya **terisi/kosong** (jangan pernah menampilkan nilainya).

## Aturan main

- **Bahasa Indonesia**, gaya santai. User bukan programmer: jelaskan dengan bahasa awam, satu langkah per giliran.
- **Helicopter view dulu**, detail teknis belakangan. Kalau user bertanya pendapat, jawab dulu; jangan langsung mengubah file.
- **Saat user sedang menguji bot, jelaskan masalah dan usulan perbaikan dulu, tunggu "ya" sebelum mengubah kode.**
- **Claude tidak mengeksekusi order** dan tidak menekan beli/jual. Claude menulis program; user yang menjalankan bot (MENU.bat).
- **Jangan minta atau menerima rahasia di chat**: token bot, API ID/hash Telegram, password, kode login, file `pembaca.session`. User mengisinya sendiri ke `.env`. ID channel/user bukan rahasia.
- **Paket/repo dari luar wajib dicek dulu** sebelum dipasang atau dijalankan.
- **Uji di akun demo** sebelum live. Live nanti di **akun cent Exness** (saldo USC; bot otomatis mengalikan nilai $ x100).
- Commit boleh di branch `tahap-1` dengan identitas git repo (`Rinek22-awam` + email noreply). **Push hanya dengan izin user** setiap kali.
- Jangan menjalankan bot/pembaca sungguhan dari sesi Claude; itu tugas user. Membaca MT5/Telegram untuk pengecekan (tanpa order) boleh, dan sebutkan kalau melakukannya.

## Peta kode

| Folder | Isi |
|---|---|
| `copier/` | Bot: format setup, gerbang, eksekutor, penjaga posisi (BE/trailing), jurnal SQLite, Telegram Bot API, pencegah jalan dobel |
| `reader/` | Pembaca: Telethon (akun user), Claude membaca gambar (`vision.py`, dikunci hanya tool Read), aturan arah/entry/simbol (`chart.py`), pesan teks → UPDATE |
| `panel/` | `MENU.bat`: Jalankan, Utilitas, Pengaturan SOP (edit `config.yaml` tanpa merusak komentar), cek kesiapan |
| `tests/` | MT5 tiruan, Telegram tiruan, Claude tiruan. `python -m pytest -q` |
| `config.yaml` | Semua angka SOP. Rahasia di `.env` |

## Keputusan yang sudah dikunci

- Eksekusi oleh kode, bukan AI. AI (Claude) hanya **menyalin** angka dan warna dari gambar; arah, entry, simbol ditentukan kode, lalu dicek gerbang dan dikonfirmasi user.
- Kotak masuk = satu channel Telegram privat; bot hanya membaca channel itu. Pembaca memposting sebagai akun user (bot tidak menerima postingannya sendiri).
- Dua entry → pakai yang paling dekat ke TP. Dua SL → SL1. Highrisk → hanya ditandai ⚠️, risiko tetap. Update channel → bot ikut SOP sendiri; cancel/close hanya jadi tombol.
- Risiko dua mode: persen saldo atau nominal $; bisa ditimpa per setup (`Risk:`).
- Gemini tidak dipakai (berbayar). OCR tidak dipakai (keputusan user).
- Bybit ditunda; MT5 duluan.
