# Format Setup untuk Bot

Kirim ke channel kotak masuk (**Rinek's Corner**) pakai akunmu sendiri. Bot tidak membaca postingan yang dia kirim sendiri.

## Format kosong

```
SETUP
Pair: 
Arah: 
Order: 
Entry: 
SL: 
TP1: 
TP2: 
TP3: 
Risk: 
Highrisk: 
Catatan: 
Sumber: 
```

| Baris | Wajib? | Isi |
|---|---|---|
| `SETUP` | **wajib, baris pertama** | Tanpa ini postingan diabaikan |
| `Pair` | **wajib** | `XAUUSD` / `GOLD` / `BTCUSD` (harus ada di daftar `simbol:` di `config.yaml`) |
| `Arah` | **wajib** | `BUY` / `SELL` (boleh `LONG`/`SHORT`/`BELI`/`JUAL`) |
| `Order` | boleh dihapus | `LIMIT` (bawaan), `STOP`, `MARKET` |
| `Entry` | **wajib**, kecuali MARKET | Harga entry |
| `SL` | **wajib** | Stop loss |
| `TP1`, `TP2`, ... | **minimal 1** | Boleh sampai TP5 |
| `Risk` | boleh dihapus | Untuk setup ini saja: `0.5%` atau `$20` |
| `Highrisk` | boleh dihapus | `ya` = diberi tanda ⚠️ dan selalu ditanya |
| `Catatan`, `Sumber` | boleh dihapus | Untuk jurnal |

Baris yang tidak dipakai **dihapus**, jangan dibiarkan kosong.

## Contoh

**1. BUY limit gold**
```
SETUP
Pair: XAUUSD
Arah: BUY
Entry: 4005.50
SL: 3995.50
TP1: 4015.50
TP2: 4025.50
TP3: 4035.50
Sumber: trabar
```

**2. SELL limit BTC**
```
SETUP
Pair: BTCUSD
Arah: SELL
Entry: 112500
SL: 113500
TP1: 111500
TP2: 110500
Sumber: trabar
```

**3. Langsung masuk market (tanpa Entry)**
```
SETUP
Pair: XAUUSD
Arah: SELL
Order: MARKET
SL: 4015
TP1: 3995
TP2: 3985
Sumber: manual
```

**4. Buy stop, risiko khusus, highrisk**
```
SETUP
Pair: XAUUSD
Arah: BUY
Order: STOP
Entry: 4012
SL: 4004
TP1: 4020
TP2: 4028
Risk: $20
Highrisk: ya
Catatan: breakout
Sumber: manual
```

## Batalkan atau tutup

Bot hanya memunculkan tombol, tidak bertindak sendiri.

```
UPDATE
Sumber: trabar
Aksi: CANCEL
Teks: cancel setup gold
```

`Aksi`: `INFO` (diteruskan saja), `CANCEL` (tombol batalkan limit), `CLOSE` (tombol tutup posisi). Yang kena: setup terakhir dari `Sumber` yang sama.

## Aturan penting

1. **Jangan pakai titik ribuan.** `112.500` dibaca **112,5** dan `4.005` dibaca **4,005**. Tulis `112500` dan `4005.50`. Format Indonesia lengkap (`4.005,50`) masih terbaca benar, tapi paling aman tanpa pemisah ribuan. Kalau salah tulis, setup ditolak "Entry terlalu jauh dari harga", tidak sampai jadi order.
2. **Kirim saat harga masih relevan.** Postingan lebih tua dari 30 menit ditolak (basi). Entry lebih dari 1% dari harga sekarang ditolak. (Angka ini bisa diubah di MENU → Pengaturan SOP → Gerbang.)
3. **Sisi harus benar.** BUY: SL di bawah entry, TP di atas entry. SELL: kebalikannya.
4. **Huruf besar/kecil bebas**, pemisah boleh `:` atau `=`. Urutan TP bebas, bot mengurutkan dari yang terdekat.
5. Setup yang **salah format** dilaporkan ke chat pribadimu beserta alasannya, tidak dieksekusi.
