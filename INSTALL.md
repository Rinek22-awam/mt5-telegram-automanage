# Pasang di Device Baru

Panduan memasang sistem ini dari nol di PC Windows baru. Ditulis untuk dua pembaca:
**kamu** (yang mengerjakan langkah berisi akun, password, dan klik di aplikasi) dan
**Claude** (yang membantu: mengecek, memasang paket, menjalankan tes, dan menuntun).

> **Aturan tetap:** rahasia (token bot, API Telegram, password MT5, kode login) **tidak pernah**
> dikirim ke chat Claude. Kamu sendiri yang mengisinya ke file `.env`, dan file itu tidak ikut git.

---

## 0. Gambaran singkat

```
Grup sinyal (gambar) → PEMBACA (akun Telegram-mu + Claude membaca gambar)
                                   ↓ posting SETUP / UPDATE
                        Channel privat "kotak masuk"
                                   ↓ dibaca
                        BOT (bot Telegram) → gerbang → tombol Ya/Tidak → MT5 (Exness)
```

Dua program, dijalankan dari **`MENU.bat`**:
- **Bot** (`copier/`): membaca kotak masuk, minta konfirmasi, memasang order di MT5, menjaga posisi (BE, trailing).
- **Pembaca** (`reader/`): menonton grup sinyal, gambar dibaca Claude Code (`claude -p`), hasilnya diposting ke kotak masuk.

---

## 1. Yang harus ada di PC

| Bahan | Catatan | Cek |
|---|---|---|
| Windows 10/11 64-bit | Paket MetaTrader5 untuk Python hanya ada di Windows | |
| **Python 3.13** (64-bit) | Saat instal centang **"Add python.exe to PATH"**. Versi lain mungkin jalan, tapi yang teruji 3.13.5 | `python --version` |
| **Git** | | `git --version` |
| **MT5 desktop** dari Exness | Login ke akun Exness (demo untuk uji, cent untuk live) | buka aplikasinya |
| **Claude Code** (CLI `claude`) | Mata pembaca. Ikut langganan Claude Pro, tanpa API key | `claude --version` |
| Telegram | Akun utama yang sudah join grup sinyal | |

## 2. Ambil kode

```
git clone https://github.com/Rinek22-awam/mt5-telegram-automanage.git
cd mt5-telegram-automanage
git checkout tahap-1
```

`tahap-1` adalah branch kerja (belum digabung ke `main` sampai uji demo lolos; cek `git branch -a`).

Atur identitas git **khusus repo ini** (bukan global):

```
git config user.name "Rinek22-awam"
git config user.email "333410072+Rinek22-awam@users.noreply.github.com"
```

## 3. Pasang paket Python

```
python -m pip install -r requirements.txt
python -m pytest -q
```

Semua tes harus lolos. Tes tidak butuh MT5, Telegram, atau Claude: semuanya pakai tiruan.

## 4. Isi file `.env` (kamu sendiri, bukan Claude)

```
copy .env.example .env
```

Buka `.env` dengan Notepad dan isi:

| Kunci | Dari mana | Rahasia? |
|---|---|---|
| `TG_BOT_TOKEN` | @BotFather. Bot lama bisa dipakai lagi: di @BotFather `/mybots` → pilih bot → *API Token*. Bot sekarang: **@baburinek_bot** | **Ya** |
| `TG_INBOX_CHANNEL_ID` | ID channel kotak masuk "Rinek's Corner" (`-1004394603314`). Bisa dicari: MENU → Utilitas → *Cari ID Telegram* | Tidak |
| `TG_ADMIN_USER_ID` | ID akun Telegram-mu (`5724712294`), cara cari sama | Tidak |
| `TG_API_ID`, `TG_API_HASH` | https://my.telegram.org → *API development tools*. Aplikasi lama tetap bisa dipakai (lihat lagi di halaman itu) | **Ya** |
| `MT5_LOGIN` dst. | **Kosongkan.** Login langsung di aplikasi MT5 lebih aman | Ya |

Kalau channel kotak masuk atau bot dibuat baru: bot harus jadi **admin** di channel kotak masuk, dan akun Telegram-mu juga admin (pembaca memposting sebagai akunmu, karena bot tidak menerima postingannya sendiri). Kirim `/start` ke bot di chat pribadi.

## 5. Login Claude Code (kamu sendiri)

```
claude auth login
claude auth status
```

Harus `"loggedIn": true`. Aplikasi Claude desktop dan CLI punya login masing-masing.

## 6. Siapkan MT5

1. Login akun Exness di MT5 desktop. Akun harus tipe **hedging** (bot menolak akun netting).
2. Klik tombol **Algo Trading** sampai hijau.
3. Nama simbol beda tiap broker/akun (Exness demo `XAUUSDm`, cent `XAUUSDc`, broker lain bisa `GOLD`). Jalankan MENU → Utilitas → **Cocokkan nama pair dengan broker**: menu mengusulkan, kamu setujui, tersimpan. Ulangi setiap ganti broker/akun.
4. Akun **real/cent**: Pengaturan SOP → Pengaman → *Hanya boleh akun demo* = tidak (minta ketik `REAL`).

## 7. Pertama kali menjalankan

Klik dua kali **`MENU.bat`**, lalu:

1. **Utilitas → Pilih channel & topik sumber sinyal.** Pertama kali minta nomor HP (`+62...`), kode dari aplikasi Telegram, dan password 2FA kalau ada; ketik di jendela itu saja. Lalu ketik ID grup sinyal dan pilih topiknya.
   Sumber asli: grup **`-1002631236672`** ("Trabar AMF"), topik **`78395`**.
2. **Utilitas → Coba baca gambar sinyal** → seret satu gambar sinyal dari grup sumber ke jendela → harus jadi `SETUP` dengan angka yang sama dengan gambar.
3. **Utilitas → Cek kesiapan** → semua ✅.
4. **Jalankan → Bot + Pembaca.** Di Telegram muncul "🤖 Bot nyala".

## 8. Yang TIDAK ada di git (tidak ikut pindah otomatis)

| File | Isi | Di device baru |
|---|---|---|
| `.env` | Semua rahasia | Isi ulang (langkah 4) |
| `pembaca.session` | Login Telegram pembaca = akses penuh ke akunmu | **Login ulang** (langkah 7.1). Jangan disalin lewat chat/cloud. Hapus dari device lama |
| `data/jurnal.db` | Riwayat semua setup | Boleh disalin dari device lama ke `data/` kalau mau riwayat tetap ada. Jangan disalin saat bot di device lama masih jalan |
| `logs/` | Log bot dan pembaca | Tidak perlu |

**Jangan jalankan bot di dua device sekaligus.** Keduanya akan membaca kotak masuk yang sama dan bisa mengeksekusi satu sinyal dua kali. Matikan di device lama dulu. (Pengaman anti-dobel hanya bekerja di satu PC.)

## 9. Catatan perencanaan

Dokumen rencana, status terakhir, dan keputusan proyek ada di folder `docs/` repo ini kalau sudah disalin ke sana; kalau belum, dokumen itu hanya ada di PC lama (`F:\Plan sistem trade\`). Status terakhir selalu ada di `STATUS_DAN_LANJUTAN.md`.

## 10. Masalah yang pernah muncul

| Gejala | Penyebab | Jalan keluar |
|---|---|---|
| Konfirmasi telat 10–30 detik, log "Telegram lambat/putus" | Koneksi ke Telegram tersendat | Sudah ditangani bot (coba lagi otomatis); cek jaringan/VPN |
| "Batas loss harian tercapai" terus saat uji | Pengaman 3% sudah kena | Masa uji: Pengaturan SOP → Pengaman → naikkan sementara (misal 20), kembalikan ke 3 sebelum live |
| Pembaca: "Claude gagal membaca: OAuth ..." | CLI `claude` belum login / sesi habis | `claude auth login` |
| "Bot sudah jalan di jendela lain" | Bot sudah menyala | Pakai jendela yang ada, atau tutup dulu |
| Setup ditolak "Simbol ... tidak ada di MT5" | Nama simbol beda (akhiran `m`/`c`, ganti broker) | Utilitas → Cocokkan nama pair dengan broker |
| Gambar contoh lama ditolak "Entry terlalu jauh" / "TP1 sudah terlewat" | Harga di gambar sudah basi | Normal; gerbang bekerja |
