"""Tiny console helpers for the menu."""
import os


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def title(text: str):
    print("=" * 52)
    print(f"  {text}")
    print("=" * 52)
    print()


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def pause():
    ask("\n  Tekan Enter untuk kembali...")


def choose(items, back="Kembali"):
    """Numbered menu. Returns the 0-based index picked, or None for 0 / back."""
    for i, item in enumerate(items, 1):
        print(f"  {i}. {item}")
    print(f"  0. {back}")
    while True:
        raw = ask("\n  Pilih nomor: ")
        if raw in ("0", ""):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(items):
            return int(raw) - 1
        print("  Nomor tidak ada di daftar.")
