"""SOP settings screen: every number in config.yaml, editable without opening the file."""
import yaml

from copier.config import with_defaults
from copier.setup_format import parse_number

from .ui import ask, choose, clear, pause, title
from .yamledit import add_value, remove_value, set_value

# (path, label, kind, options, note)
# kind: float | int | bool | choice | text | float_or_null | split
SECTIONS = [
    ("Risiko", [
        (("risiko", "mode"), "Mode risiko", "choice", ["persen", "dolar"],
         "persen = % dari saldo, dolar = nominal tetap per setup"),
        (("risiko", "persen"), "Risiko per setup (% saldo)", "float", (0.01, 20), "dipakai kalau mode persen"),
        (("risiko", "dolar"), "Risiko per setup ($)", "float", (0.01, 1e6),
         "dipakai kalau mode dolar; di akun cent otomatis x100"),
        (("risiko", "lot_maks"), "Lot maksimal per setup", "float", (0.01, 1e4), ""),
    ]),
    ("Pembagian lot per TP", [
        (("tp", "bagi", str(n)), f"Setup dengan {n} TP", "split", n, "persen lot tiap TP, dari TP1")
        for n in range(1, 6)
    ]),
    ("SOP posisi (BE dan trailing)", [
        (("sop", "be_setelah_tp"), "SL ke BE setelah TP ke-", "int", (0, 10), "0 = BE mati"),
        (("sop", "be_jarak_aman_r"), "Jarak aman BE (x jarak SL)", "float", (0, 1),
         "0.1 = SL dikunci 10% jarak SL di atas entry"),
        (("sop", "trailing"), "Trailing bertingkat", "bool", None, "TP2 kena -> SL ke TP1, dst."),
        (("sop", "tutup_jika_sl_baru_terlewat"), "Tutup kalau harga sudah lewat SL baru", "bool", None,
         "harga balik sebelum SL sempat digeser"),
    ]),
    ("Entry", [
        (("entry", "limit_kedaluwarsa_jam"), "Limit dibatalkan setelah (jam)", "float", (0.1, 720), ""),
        (("entry", "jika_harga_sudah_lewat"), "Harga sudah lebih bagus dari entry", "choice",
         ["market", "tolak"], "market = langsung masuk, tolak = setup ditolak"),
    ]),
    ("Gerbang (cek sebelum eksekusi)", [
        (("gerbang", "konfirmasi_wajib"), "Wajib konfirmasi Ya/Tidak", "bool", None, ""),
        (("gerbang", "konfirmasi_kedaluwarsa_menit"), "Konfirmasi kedaluwarsa (menit)", "int", (1, 1440), ""),
        (("gerbang", "umur_maks_setup_menit"), "Setup dianggap basi setelah (menit)", "int", (1, 1440), ""),
        (("gerbang", "jarak_maks_dari_harga_persen"), "Entry maks sejauh (% dari harga)", "float", (0.01, 50), ""),
        (("gerbang", "dobel_jendela_jam"), "Cek dobel dalam (jam)", "float", (0, 720), ""),
        (("gerbang", "mirip_jarak_entry_persen"), "Dianggap mirip kalau entry sedekat (%)", "float", (0, 10), ""),
    ]),
    ("Pengaman", [
        (("pengaman", "maks_setup_aktif"), "Maksimal setup aktif", "int", (1, 50), ""),
        (("pengaman", "loss_harian_persen"), "Stop di loss harian (%)", "float", (0, 100), "0 = mati"),
        (("pengaman", "loss_harian_dolar"), "Stop di loss harian ($)", "float_or_null", (0.01, 1e6),
         "kosong = mati"),
        (("akun", "hanya_demo"), "Hanya boleh akun demo", "bool", None,
         "matikan HANYA saat siap live (akun cent)"),
    ]),
    ("Pembaca sinyal", [
        (("pembaca", "nama_sumber"), "Nama sumber (untuk jurnal)", "text", None, ""),
        (("pembaca", "claude_model"), "Model Claude pembaca gambar", "choice", ["sonnet", "opus", "haiku"],
         "sonnet = seimbang, opus = paling teliti, haiku = paling hemat kuota"),
    ]),
]


def _get(cfg, path):
    for k in path:
        if isinstance(cfg, dict) and k not in cfg and k.isdigit():
            k = int(k)   # tp.bagi is keyed by number after loading
        cfg = cfg.get(k) if isinstance(cfg, dict) else None
    return cfg


def show(value) -> str:
    if isinstance(value, bool):
        return "ya" if value else "tidak"
    if value is None:
        return "-"
    if isinstance(value, list):
        return " / ".join(f"{v:g}" if isinstance(v, (int, float)) else str(v) for v in value)
    return f"{value:g}" if isinstance(value, float) else str(value)


def parse(kind, options, raw: str):
    """User text -> value. Raises ValueError with a message in Indonesian."""
    raw = raw.strip()
    if kind == "bool":
        if raw.lower() in ("y", "ya", "1", "on", "true"):
            return True
        if raw.lower() in ("t", "tidak", "n", "0", "off", "false"):
            return False
        raise ValueError("jawab y (ya) atau t (tidak)")
    if kind == "choice":
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw.lower() in options:
            return raw.lower()
        raise ValueError("pilih salah satu: " + ", ".join(options))
    if kind == "text":
        if not raw:
            raise ValueError("tidak boleh kosong")
        return raw
    if kind == "split":
        parts = [parse_number(x) for x in raw.replace("/", " ").replace(";", " ").split()]
        if len(parts) != options or any(p is None or p <= 0 for p in parts):
            raise ValueError(f"isi {options} angka positif, misal: " +
                             " ".join(["50", "30", "20", "10", "5"][:options]))
        return [int(p) if p == int(p) else p for p in parts]
    if kind == "float_or_null" and raw.lower() in ("", "0", "-", "mati", "kosong"):
        return None
    v = parse_number(raw)
    if v is None:
        raise ValueError("harus angka")
    lo, hi = options
    if not lo <= v <= hi:
        raise ValueError(f"harus antara {lo:g} dan {hi:g}")
    return int(v) if kind == "int" else v


class Settings:
    def __init__(self, path="config.yaml", bot_running=lambda: False):
        self.path, self.bot_running = path, bot_running

    def load_text(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read()

    def cfg(self):
        return with_defaults(yaml.safe_load(self.load_text()) or {})

    def save(self, text: str):
        with_defaults(yaml.safe_load(text) or {})   # refuse to write a config the bot cannot load
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def set(self, path, value):
        self.save(set_value(self.load_text(), path, value))

    # --- screens ------------------------------------------------------------
    def run(self):
        while True:
            clear()
            title("PENGATURAN SOP")
            cfg = self.cfg()
            r = cfg["risiko"]
            print(f"  Risiko sekarang: {r['persen']}% saldo" if r["mode"] == "persen"
                  else f"  Risiko sekarang: ${r['dolar']} per setup")
            print(f"  Akun: {'HANYA DEMO' if cfg['akun']['hanya_demo'] else 'demo & REAL boleh'}\n")
            names = [s for s, _ in SECTIONS] + ["Nama simbol di MT5"]
            pick = choose(names, back="Kembali")
            if pick is None:
                return
            if pick == len(SECTIONS):
                self.symbols()
            else:
                self.section(*SECTIONS[pick])

    def section(self, name, items):
        while True:
            clear()
            title(name.upper())
            cfg = self.cfg()
            rows = [f"{label:<42} {show(_get(cfg, path))}" for path, label, *_ in items]
            pick = choose(rows, back="Kembali")
            if pick is None:
                return
            self.edit(*items[pick])

    def edit(self, path, label, kind, options, note):
        current = _get(self.cfg(), path)
        print(f"\n  {label}: sekarang {show(current)}")
        if note:
            print(f"  ({note})")
        if kind == "choice":
            for i, o in enumerate(options, 1):
                print(f"    {i}. {o}")
        hint = {"bool": " (y/t)", "choice": " (nomor)", "float_or_null": " (kosong = mati)"}.get(kind, "")
        raw = ask(f"  Nilai baru{hint}, Enter saja = batal: ")
        if raw == "" and kind != "float_or_null":
            return
        if raw == "" and kind == "float_or_null" and current is None:
            return
        try:
            value = parse(kind, options, raw)
        except ValueError as e:
            print(f"\n  [X] {e}. Tidak diubah.")
            pause()
            return
        if path == ("akun", "hanya_demo") and value is False:
            if ask("  Yakin? Bot akan boleh trading di akun REAL. Ketik REAL untuk lanjut: ") != "REAL":
                print("  Dibatalkan.")
                pause()
                return
        self.set(path, value)
        print(f"\n  Tersimpan: {label} = {show(value)}")
        if self.bot_running():
            print("  Bot sedang jalan: perubahan berlaku setelah bot dinyalakan ulang.")
        pause()

    def symbols(self):
        while True:
            clear()
            title("NAMA SIMBOL DI MT5")
            print("  Nama di setup -> nama di MT5 (cek di Market Watch; akun cent pakai akhiran c)\n")
            mapping = self.cfg()["simbol"]
            keys = list(mapping)
            pick = choose([f"{k:<10} -> {v}" for k, v in mapping.items()] +
                          ["+ Tambah simbol", "Cocokkan otomatis dengan broker di MT5"], back="Kembali")
            if pick is None:
                return
            if pick == len(keys) + 1:
                from .symbols import match_screen
                match_screen(self)
                continue
            if pick == len(keys):
                k = ask("  Nama di setup (misal XAUUSD): ").upper()
                v = ask("  Nama di MT5 (misal XAUUSDc): ")
                if k and v:
                    self.save(add_value(self.load_text(), ("simbol",), k, v))
                continue
            k = keys[pick]
            v = ask(f"  {k}: nama baru di MT5 (Enter = batal, HAPUS = hapus): ")
            if v == "HAPUS":
                self.save(remove_value(self.load_text(), ("simbol", k)))
            elif v:
                self.set(("simbol", k), v)
