# MT5 Telegram Automanage

Bot yang membaca **setup berformat standar** dari satu channel Telegram privat (kotak masuk), minta konfirmasi kamu lewat tombol Telegram, lalu mengeksekusinya ke **MetaTrader 5** dan menjaga posisinya sesuai SOP: limit entry, TP bertahap, SL ke BE, trailing bertingkat, dan batas waktu limit. Bot **tidak menganalisa**.

Dikembangkan dari [MT5-Automation-Labs/mt5-telegram-signal-copier](https://github.com/MT5-Automation-Labs/mt5-telegram-signal-copier) (MIT). Yang dipakai ulang: perhitungan lot dan ide cek validasi. Pembaca Telegram, gerbang, eksekutor, dan penjaga posisi ditulis ulang.

```
📥 Channel privat ──► Gerbang ──► Konfirmasi (tombol) ──► Eksekutor ──► MT5
   (format standar)    │  cek dasar, dobel/mirip,                          │
                       │  batas loss & setup aktif                         ▼
                       └──────────────► Jurnal ◄──────────── Penjaga posisi (BE, trailing)
```

> **Pasang di PC baru:** ikuti [INSTALL.md](INSTALL.md). **Format setup** siap salin: [FORMAT_SETUP.md](FORMAT_SETUP.md). **Dashboard desktop** (opsional, branch `codex/desktop-manager`): [DESKTOP.md](DESKTOP.md).

## MENU.bat: satu pintu untuk semuanya

Klik dua kali **`MENU.bat`**. Di atas menu selalu tampil: bot/pembaca sedang jalan atau mati, sumber sinyal, dan risiko.

```
1. Jalankan
   1. Bot saja
   2. Bot + Pembaca
2. Utilitas
   1. Pilih channel & topik sumber sinyal
   2. Pengaturan SOP (risiko, pembagian TP, BE, trailing, entry, gerbang, pengaman, pembaca, simbol)
   3. Cocokkan nama pair dengan broker (setelah ganti broker/akun)
   4. Coba baca gambar sinyal (tanpa Telegram)
   5. Cek kesiapan (MT5, Telegram, Claude)
   6. Riwayat setup
   7. Reset jurnal trade (hapus riwayat, ada cadangan)
   8. Cari ID Telegram (kotak masuk & ID kamu)
   9. Tes logika program
```

- Bot dan pembaca masing-masing jalan di **jendela sendiri**; tutup jendelanya untuk mematikan.
- **Ganti broker atau akun** (misal ke akun cent): login akun baru di MT5, lalu *Cocokkan nama pair dengan broker*. Menu membaca daftar simbol MT5, mengusulkan nama yang cocok (`XAUUSD` → `XAUUSDc`, atau `GOLD` di broker lain), menanyakan kalau ada beberapa kemungkinan (misal `XAUUSDm` vs `XAUUSD247m`), lalu menyimpan setelah kamu setujui. Saat trading, bot tidak pernah menebak nama; ia hanya memakai tabel yang sudah disimpan, dan memberi tahu di Telegram kalau ada nama yang tidak ada di MT5.
- Bot dan pembaca **tidak bisa jalan dobel**. Kalau dinyalakan dua kali, yang kedua langsung berhenti, supaya satu sinyal tidak dieksekusi dua kali.
- **Pengaturan SOP** mengubah `config.yaml` langsung: nilai dicek dulu (misal risiko harus angka 0.01–20), komentar di file tetap utuh, dan config yang bikin bot gagal jalan ditolak. Perubahan berlaku setelah bot dinyalakan ulang. Mematikan "hanya demo" minta konfirmasi ketik `REAL`.

## Format setup

Tulis di channel kotak masuk. Baris pertama harus berisi kata `SETUP`. Format kosong siap salin dan contoh lengkap: [FORMAT_SETUP.md](FORMAT_SETUP.md).

```
SETUP
Pair: XAUUSD
Arah: BUY
Entry: 3987.26
SL: 3981.26
TP1: 3993.26
TP2: 3999.26
TP3: 4005.26
Sumber: outlook_gold
```

| Baris | Wajib | Isi |
|---|---|---|
| `Pair` | ya | Nama pair seperti di sinyal. Diterjemahkan ke nama MT5 lewat `simbol:` di `config.yaml` |
| `Arah` | ya | `BUY` / `SELL` (boleh juga `LONG`/`SHORT`/`BELI`/`JUAL`) |
| `Entry` | ya, kecuali MARKET | Harga entry |
| `SL` | ya | Stop loss |
| `TP1`, `TP2`, ... | minimal satu | Urutan bebas, bot mengurutkan dari yang terdekat |
| `Order` | tidak | `LIMIT` (default), `STOP`, atau `MARKET` |
| `Risk` | tidak | Menimpa risiko di config untuk setup ini saja: `0.5%` atau `$20` |
| `Entry2`, `SL2` | tidak | Dicatat di jurnal, tidak dipakai (SOP: entry pertama, SL1) |
| `Highrisk` | tidak | `ya` = diberi tanda ⚠️ HIGHRISK di konfirmasi dan selalu ditanya. Risiko tetap normal |
| `Sumber`, `Catatan` | tidak | Untuk jurnal dan evaluasi channel |

### Update dari sumber

```
UPDATE
Sumber: outlook
Aksi: CANCEL
Teks: cancel setup gold
```

`Aksi: INFO` diteruskan ke chat pribadimu. `CANCEL` / `CLOSE` muncul dengan tombol (batalkan limit / tutup posisi) untuk setup terakhir dari sumber yang sama. **Bot tidak bertindak sebelum tombol ditekan**; SOP bot (BE, trailing) tetap jalan.

Angka boleh format biasa (`3987.26`) atau Indonesia (`3.987,26`). Postingan tanpa kata `SETUP` di baris pertama diabaikan. Postingan `SETUP` yang salah format dilaporkan ke chat pribadimu, tidak dieksekusi.

## Apa yang dicek gerbang

- Simbol ada di MT5, SL dan TP di sisi yang benar, SL belum terlewat harga. TP1 sudah terlewat → order market ditolak, order limit tetap ditanyakan dengan tanda ⚠️ (limit menunggu harga balik ke entry).
- Postingan tidak basi (default 30 menit), entry tidak terlalu jauh dari harga (default 1%).
- **Dobel** (sama persis dalam 24 jam) → ditolak. **Mirip** (pair & arah sama, entry dekat) → tetap ditanyakan dengan tanda ⚠️.
- Bot tidak sedang di-stop, setup aktif belum penuh (default 3), batas loss harian belum kena (default 3%).
- Lot hasil hitungan tidak di bawah minimum broker.

Setelah kamu tekan **Ya**, cek harga diulang sekali lagi sebelum order dikirim.

## SOP penjaga posisi

- **Mode TP** (`tp.mode`, diatur di MENU → Pengaturan SOP → Pembagian lot per TP):
  - `partial` (bawaan): lot dibagi per TP sesuai `tp.bagi` (default 3 TP: 50/30/20). Angka **0** = tanpa lot di TP itu, misal `0 40 60` = TP2 40%, TP3 60%. Kalau lot terlalu kecil untuk dibagi, TP terjauh yang ada lot-nya dibuang. Pilihan *Kembalikan semua pembagian partial ke bawaan*, atau ketik `bawaan` di satu baris, untuk balik ke preset.
  - `satu`: semua lot jadi satu order di TP ke-`tp.satu_ke`. Setup dengan TP lebih sedikit → TP terakhir.
  - Di mode apa pun, BE dan trailing jalan menurut **harga**: TP1 tersentuh → SL ke BE walaupun di TP1 tidak ada lot.
- **TP1 kena** → SL semua kaki sisa digeser ke entry + 10% jarak SL (`be_jarak_aman_r`).
- **TP2 kena** → SL ke TP1, **TP3 kena** → SL ke TP2, dst. SL tidak pernah dilonggarkan.
- Geser SL gagal → dicoba ulang tiap 15 detik. Harga sudah melewati SL baru sebelum sempat digeser → kaki ditutup di harga pasar.
- Limit belum ke-fill setelah 12 jam → dibatalkan.
- Semua status disimpan di jurnal (`data/jurnal.db`). Setelah restart, bot membaca ulang kondisi MT5 dan melanjutkan, termasuk TP yang kena saat bot mati.
- SL dan TP selalu terpasang di MT5. Kalau bot mati, posisi tetap terlindungi, tapi BE/trailing berhenti.

## Perintah di chat pribadi dengan bot

| Perintah | Fungsi |
|---|---|
| `/status` | Saldo, setup aktif, TP yang sudah kena |
| `/stop` | Tolak setup baru + batalkan semua limit. Posisi yang jalan tetap dijaga |
| `/lanjut` | Terima setup lagi |
| `/limit` | Daftar limit yang menunggu: nomor, pair, arah, entry, SL, jam habis. Ada tombol batal per setup |
| `/hapuslimit` | Hapus semua limit yang belum ke-fill, tanpa mode stop. Posisi yang jalan tidak disentuh (ada tombol konfirmasi) |
| `/tutupsemua` | Tutup semua posisi dan limit bot (ada tombol konfirmasi) |
| `/resetjurnal` | Hapus riwayat setup (ada tombol konfirmasi). Hanya bisa kalau tidak ada setup aktif |

**Reset jurnal** (lewat `/resetjurnal` atau `MENU.bat` → Utilitas → *Reset jurnal trade*): riwayat setup dihapus, jadi cek dobel mulai dari nol. Jurnal lama disalin dulu ke `data/jurnal-cadangan-<tanggal>.db`. Nomor setup mulai lagi dari #1; mode stop tetap. Jangan pencet tombol di pesan Telegram dari sebelum reset: nomornya bisa sama dengan setup baru. Batas loss harian tidak ikut ter-reset karena dihitung dari MT5. Ditolak kalau masih ada limit terpasang atau posisi jalan; dari menu juga ditolak kalau bot sedang jalan (pakai `/resetjurnal`).

## Pengaturan

Semua angka SOP ada di [`config.yaml`](config.yaml), lengkap dengan penjelasan. Ubah lalu restart bot. Yang paling sering diubah:

```yaml
risiko:
  mode: persen     # persen = % saldo | dolar = nominal tetap
  persen: 1.0
  dolar: 10
```

Rahasia **tidak** ditulis di `config.yaml`, tapi di `.env` (tidak ikut ke git).

## Pasang dan uji di akun demo

1. **Install** (sekali saja), dari folder ini:
   ```
   pip install -r requirements.txt
   copy .env.example .env
   ```
2. **Bot Telegram:** buat bot di @BotFather, tempel tokennya ke `TG_BOT_TOKEN` di `.env`. Jangan kirim token ke siapa pun.
3. **Channel kotak masuk:** buat channel **privat**, tambahkan bot sebagai **admin**. Kirim `/start` ke bot di chat pribadi.
4. **Cari ID:** `MENU.bat` → Utilitas → *Cari ID Telegram*, kirim satu postingan di channel, tekan Enter. Salin dua angka yang muncul ke `TG_INBOX_CHANNEL_ID` dan `TG_ADMIN_USER_ID`.
5. **MT5:** buka MT5 desktop, login ke akun **demo** Exness (tipe hedging). Di Market Watch, cek nama simbol gold (misal `XAUUSDm`) dan sesuaikan bagian `simbol:` di `config.yaml`. Di MT5: Tools → Options → Expert Advisors → centang **Allow algorithmic trading**.
6. **Jalankan:** `MENU.bat` → Jalankan → *Bot saja*. Bot jalan di jendelanya sendiri; tutup jendela itu untuk mematikan. Bot mengirim "🤖 Bot nyala" ke chat pribadimu. Bot menolak jalan kalau MT5 login ke akun real (`akun.hanya_demo: true`).
7. **Uji fungsi** (bukan strategi). Pakai entry dekat harga sekarang supaya cepat ke-fill:
   - Setup BUY limit di bawah harga → muncul konfirmasi → **Ya** → 3 limit order muncul di MT5 (tab Trade).
   - Setelah ke-fill dan TP1 kena: SL kaki sisa pindah ke BE.
   - Setup yang sama dikirim lagi → ditolak "Dobel".
   - Tekan **Tidak** → tidak ada order.
   - `/stop` → limit hilang. `/lanjut` → normal lagi.
   - Matikan bot (Ctrl+C) saat ada posisi jalan, nyalakan lagi → posisi tetap dijaga.
   - Ganti `risiko.mode` ke `dolar`, restart → lot di konfirmasi berubah sesuai nominal.

## Pembaca sinyal (program kedua)

Menonton **channel sinyal** pakai akun Telegram-mu, membaca gambar sinyal dengan **Claude** (Claude Code, ikut langganan Pro), lalu memposting `SETUP` (beserta gambar aslinya) ke channel kotak masuk. Pesan teks dari channel sinyal diposting sebagai `UPDATE`. Pembaca **tidak pernah trading**; semua tetap lewat gerbang dan konfirmasi bot.

Claude hanya menyalin label angka dan warna garis (merah = SL, biru = entry, hitam = TP). Yang menentukan arah, entry, dan simbol adalah kode biasa:
- **Arah:** SL di bawah entry = BUY, di atas = SELL.
- **Dua entry:** dipakai yang paling dekat ke TP (yang ke-fill duluan); yang lain dicatat sebagai `Entry2`.
- **Simbol:** dari nama di gambar kalau ada, kalau tidak dari besar harga (`simbol_dari_harga` di config: 1.000–10.000 = gold, di atas 10.000 = BTC).
- **Highrisk:** kata seperti "high risk" di caption gambar → baris `Highrisk: ya`.
- Gambar yang tidak terbaca atau bukan sinyal tetap diposting sebagai `UPDATE` INFO beserta alasannya, jadi kamu tahu.

Pembaca memposting pakai akunmu (bukan bot), karena bot Telegram tidak menerima postingannya sendiri. Akunmu harus admin di channel kotak masuk.

### Pasang pembaca

1. **API Telegram:** buka https://my.telegram.org → login → *API development tools* → buat aplikasi (nama bebas). Salin **api_id** dan **api_hash** ke `TG_API_ID` dan `TG_API_HASH` di `.env`. Ini akses ke akunmu: jangan dibagikan.
2. **Login Claude Code:** buka PowerShell, ketik `claude auth login`, lalu login di browser dengan akun Claude Pro-mu. Cukup sekali. Cek dengan `claude auth status`.
   Claude di pembaca dikunci: hanya boleh membaca file gambar di folder sementara, tanpa MCP dan tanpa pengaturan lain. Pemakaiannya ikut kuota Pro.
3. **Coba Claude dulu, tanpa Telegram:** `MENU.bat` → Utilitas → *Coba baca gambar sinyal*, lalu seret gambar (misal `contoh_sinyal/01_...png`) ke jendela menu dan tekan Enter. Hasilnya harus `SETUP` dengan angka yang sama dengan gambar.
4. **Pilih channel dan topik sinyal:** `MENU.bat` → Utilitas → *Pilih channel & topik sumber sinyal*. Pertama kali kamu diminta nomor HP (format `+62...`) dan kode login dari Telegram; login tersimpan di `pembaca.session` (tidak ikut git, jangan dibagikan). Muncul daftar channel → ketik ID channel sinyal → muncul daftar topiknya → ketik nomor topik sinyal (atau `0` untuk semua topik). Pilihanmu langsung disimpan ke `config.yaml`; tekan Enter saja kalau cuma mau melihat.
5. **Jalankan:** `MENU.bat` → Jalankan → *Bot + Pembaca*. Dua jendela terbuka, biarkan dua-duanya menyala.

## Akun cent

Bot mengenali akun cent Exness (mata uang **USC**). Nilai dolar di `config.yaml` dan baris `Risk: $20` otomatis dikali 100 (= 2000 USC). Mode persen tidak berubah. Ganti nama simbol di bagian `simbol:` ke versi cent (misal `XAUUSDc`, `BTCUSDc`; cek di Market Watch) dan `akun.hanya_demo: false`, karena Exness tidak punya demo cent.

## Tes logika (tanpa MT5 dan Telegram)

```
python -m pytest -q
```

Tes memakai MT5 tiruan (`tests/fake_mt5.py`) yang mengisi limit dan menutup SL/TP saat harga digerakkan. Tes tampilan dashboard butuh Qt (`.desktop-deps`, lihat [DESKTOP.md](DESKTOP.md)); tanpa itu tesnya dilewati.

## Isi folder

```
copier/setup_format.py  teks postingan -> Setup (format standar)
copier/gate.py          cek dasar, dobel/mirip di jurnal, pengaman
copier/executor.py      hitung lot (2 mode risiko), pasang order per TP
copier/guard.py         penjaga posisi: fill, BE, trailing, kedaluwarsa, retry
copier/journal.py       jurnal SQLite
copier/broker.py        pembungkus MetaTrader5 (mode pengisian order, status kaki)
copier/telegram.py      klien Bot API Telegram (tanpa paket tambahan)
copier/app.py           alur kotak masuk -> konfirmasi -> eksekusi, perintah
copier/main.py          titik masuk bot
copier/single.py        pencegah bot/pembaca jalan dobel
reader/chart.py         hasil baca Claude -> SETUP (arah, entry, simbol)
reader/vision.py        panggilan Claude Code (claude -p) yang dikunci
reader/updates.py       pesan teks channel -> UPDATE
reader/main.py          pembaca: akun Telegram-mu menonton channel sinyal
panel/                  MENU.bat: menu, pengaturan SOP, cek kesiapan
desktop/                dashboard Trading Manager (PySide6), lihat DESKTOP.md
desktop_entry.py        titik masuk dashboard
build_desktop.py        pembuat TradingManager.exe
config.yaml             semua angka SOP
FORMAT_SETUP.md         format SETUP/UPDATE kosong + contoh
```

## Disclaimer

Trading forex, logam, indeks, dan CFD dengan margin berisiko tinggi dan bisa rugi melebihi deposit. Software ini tanpa garansi dan bukan nasihat keuangan. Selalu uji di akun demo dulu.

## Lisensi

MIT © 2026 StanleyDaniels (kode asli). Perubahan di fork ini mengikuti lisensi yang sama.
