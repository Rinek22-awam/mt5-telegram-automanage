# Trading Manager untuk Windows

Antarmuka desktop bertema gelap netral/biru, berdasarkan desain FigCraft.
`MENU.bat` tetap tersedia. Aplikasi tidak menjalankan bot/pembaca saat pertama dibuka.

## Membuka aplikasi

Klik `TradingManager.exe` langsung di folder utama proyek. Biarkan folder `_internal` di sebelahnya.
Hasil build juga tersedia di `dist/TradingManager`.
Alternatif: `python desktop_entry.py` setelah memasang `requirements-desktop.txt`.

- Dashboard: persetujuan, pending (termasuk setup yang sebagian terisi), posisi berjalan, dan riwayat.
- Detail setup: level, estimasi sebelum persetujuan, rincian tiket, SL terkini, TP, dan hasil.
- Kontrol: setujui/tolak, batalkan pending per setup/semua, tutup per setup/semua, jeda/lanjut, reset jurnal.
- Pengaturan: seluruh field menu lama, pembagian partial bawaan, serta tambah/edit/hapus simbol broker.
- Utilitas: sumber/topik, pencocokan broker, uji gambar, cek kesiapan, cari ID, tes, riwayat, reset.
- Utilitas interaktif memakai kotak keluaran/jawaban di dalam aplikasi. Login dan kode hanya di perangkat lokal.
- Aktivitas: kejadian jurnal serta pilihan log bot/pembaca/desktop.
- Bot & pembaca: menyalakan program, menghentikan bot melalui antrean, serta penghentian pembaca secara kooperatif.

Tombol X menyembunyikan aplikasi ke ikon TM dekat jam. Menu Keluar hanya menutup antarmuka;
bot/pembaca yang sudah berjalan tetap berjalan. Untuk menghentikan keduanya, gunakan halaman
Bot & pembaca sebelum keluar. Tidak ada proses dihentikan paksa.

## Memakai bersama menu lama

Bot yang dimulai langsung oleh `MENU.bat` tidak mempunyai penghubung desktop. Aplikasi dapat
membaca jurnalnya, tetapi tombol trading desktop dinonaktifkan. Telegram tetap berfungsi.
Untuk memakai kontrol desktop, matikan bot menu lama dahulu, lalu jalankan dari aplikasi.
Port pencegah jalan ganda bot/pembaca tetap sama; keduanya tidak dapat dijalankan dobel.

Bot desktop tetap membaca channel dan tombol Telegram seperti biasa. Penjagaan posisi,
gerbang, ukuran lot, eksekutor, format pesan, dan jurnal asli tidak ditulis ulang.

## Penghubung dan pemulihan

`desktop.engine.DesktopApp` adalah adapter dari `copier.app.App`. Perintah diserialkan
pada thread bot yang sama dengan Telegram dan diteruskan ke handler Telegram asli.
Sebelum dijalankan, adapter memeriksa sesi bot, tenggat perintah, identitas akun, serta
setup/tiket/status saat konfirmasi. Status yang sudah berubah meminta konfirmasi ulang.
Persetujuan desktop mengedit pesan konfirmasi Telegram yang sama.

`data/desktop-control.db` menyimpan antrean lokal, hasil, dan snapshot bertanda waktu.
Perintah lama tidak dijalankan oleh sesi bot baru. Perintah yang terputus saat diproses
ditandai *unknown* dan tidak diulang otomatis; periksa MT5/jurnal sebelum mengulang.
Data basi/akun tidak tersedia mematikan kontrol desktop. UI offline hanya menampilkan jurnal.
`data/desktop-reader.json` serta penanda penghentian unik mengatur pembaca desktop.

Penyegaran dashboard membaca SQLite, konfigurasi, dan log di thread latar belakang.
Hanya satu pekerjaan baca yang diizinkan pada satu waktu, sehingga antrean tidak menumpuk
jika disk lambat. Status proses diperiksa melalui heartbeat dan probe bind lokal tanpa
membuka koneksi ke listener pencegah jalan ganda. Tabel, detail, dan log hanya diperbarui
saat isinya berubah agar fokus keyboard, pilihan teks, dan scroll tidak ter-reset.

Config, jurnal, `.env`, dan `pembaca.session` tetap di folder proyek, terpisah dari program.
Pengaturan disimpan menggunakan `panel.settings`/`panel.yamledit`, mempertahankan komentar
dan validasi menu lama. Mode REAL tetap memerlukan ketik `REAL`. Perubahan konfigurasi
memerlukan restart. Rahasia tidak dimasukkan ke paket build.

## Build dan pengujian

Dependensi tambahan berasal dari Qt/PyPI resmi: `PySide6-Essentials==6.10.0`
dan `pyinstaller==6.22.3`. GUI tidak memerlukan Qt Addons atau layanan web/cloud.

```
python -m pip install --target .desktop-deps PySide6-Essentials==6.10.0 pyinstaller==6.22.3
python -m pytest -q
python build_desktop.py
```

Untuk menyertakan tes Qt opsional, tambahkan `.desktop-deps` ke `PYTHONPATH`.

Build dibuat ramping (±100 MB): Pillow, `PySide6.QtNetwork`, `opengl32sw.dll` (grafis cadangan untuk PC
tanpa driver GPU), dan terjemahan bawaan Qt tidak ikut. `_internal` di folder utama diganti utuh setiap build.
Setelah build, `dist/`, `build/`, `*.spec`, dan `.desktop-deps/` boleh dihapus; aplikasi tidak membutuhkannya.
`.desktop-deps/` hanya perlu dipasang lagi (perintah pertama di atas) untuk build ulang atau tes Qt.
Tes memakai MT5/Telegram tiruan. `python desktop_entry.py --demo --smoke --screenshot preview.png`
membuka pratinjau data contoh, mengambil gambar, dan keluar tanpa memuat kredensial atau bot.
`TradingManager.exe --role self-check` memeriksa ketersediaan dependensi, tanpa koneksi trading.

Paket ini belum merupakan bukti validasi broker nyata. Uji pengoperasian di akun demo oleh user
tetap diperlukan: startup/login, fill/cancel/close, sinkronisasi Telegram, dan restart.
Kode sumber dipertahankan untuk revisi dan build ulang. Rilis berbentuk folder agar pustaka Qt
tetap terpisah dan dapat diganti; lisensi dependensi tersedia di `_internal`.
