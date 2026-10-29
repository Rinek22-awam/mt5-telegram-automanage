"""Journal: the system's ledger in a local SQLite file. Survives restarts."""
import json
import os
import sqlite3
import time
from typing import List, Optional

from .models import Setup

_SCHEMA = """
CREATE TABLE IF NOT EXISTS setups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL, updated REAL, status TEXT, reason TEXT DEFAULT '',
    symbol TEXT, broker_symbol TEXT, side TEXT, entry REAL, sl REAL, tps TEXT,
    order_type TEXT, entry2 REAL, sl2 REAL, risk_mode TEXT, risk_value REAL,
    source TEXT, note TEXT, raw TEXT,
    msg_chat INTEGER, msg_id INTEGER, posted REAL,
    confirm_msg_id INTEGER, confirm_deadline REAL, warning TEXT DEFAULT '',
    expires REAL, risk_amount REAL, total_lot REAL,
    peak REAL, tp_level INTEGER DEFAULT 0, pnl REAL,
    UNIQUE (msg_chat, msg_id)
);
CREATE TABLE IF NOT EXISTS legs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_id INTEGER, idx INTEGER, ticket INTEGER, volume REAL, tp REAL,
    status TEXT, fill_price REAL, fill_time REAL, profit REAL, next_try REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_id INTEGER, time REAL, kind TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


class Journal:
    def __init__(self, path: str = "data/jurnal.db", clock=time.time):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.clock = clock

    # --- setups -------------------------------------------------------------
    def add_setup(self, s: Setup, status: str, **meta) -> int:
        now = self.clock()
        row = dict(created=now, updated=now, status=status, symbol=s.symbol, side=s.side,
                   entry=s.entry, sl=s.sl, tps=json.dumps(s.tps), order_type=s.order_type,
                   entry2=s.entry2, sl2=s.sl2, risk_mode=s.risk_mode, risk_value=s.risk_value,
                   source=s.source, note=s.note, raw=s.raw)
        row.update(meta)
        cols = ", ".join(row)
        cur = self.db.execute(f"INSERT INTO setups ({cols}) VALUES ({', '.join('?' * len(row))})",
                              list(row.values()))
        self.db.commit()
        return cur.lastrowid

    def get(self, setup_id: int) -> Optional[dict]:
        r = self.db.execute("SELECT * FROM setups WHERE id = ?", (setup_id,)).fetchone()
        return _row(r)

    def update(self, setup_id: int, **fields):
        fields["updated"] = self.clock()
        if "tps" in fields:
            fields["tps"] = json.dumps(fields["tps"])
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE setups SET {sets} WHERE id = ?", [*fields.values(), setup_id])
        self.db.commit()

    def by_status(self, *statuses) -> List[dict]:
        q = f"SELECT * FROM setups WHERE status IN ({', '.join('?' * len(statuses))}) ORDER BY id"
        return [_row(r) for r in self.db.execute(q, statuses)]

    def since(self, t: float) -> List[dict]:
        return [_row(r) for r in self.db.execute(
            "SELECT * FROM setups WHERE created >= ? ORDER BY id", (t,))]

    def reset(self, backup_to: str) -> int:
        """Copy the journal to `backup_to`, then forget all setups, legs and events.
        Bot state (stop mode, Telegram offset) is kept, and numbering carries on
        so old Telegram buttons cannot hit a new setup. Returns how many setups were removed."""
        dest = sqlite3.connect(backup_to)
        self.db.backup(dest)
        dest.close()
        n = self.db.execute("SELECT COUNT(*) FROM setups").fetchone()[0]
        self.db.executescript("DELETE FROM setups; DELETE FROM legs; DELETE FROM events;")
        return n

    def message_seen(self, chat: int, msg_id: int) -> bool:
        return self.db.execute("SELECT 1 FROM setups WHERE msg_chat = ? AND msg_id = ?",
                               (chat, msg_id)).fetchone() is not None

    # --- legs ---------------------------------------------------------------
    def add_leg(self, setup_id: int, idx: int, ticket: int, volume: float, tp: float, status: str):
        self.db.execute("INSERT INTO legs (setup_id, idx, ticket, volume, tp, status) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (setup_id, idx, ticket, volume, tp, status))
        self.db.commit()

    def legs(self, setup_id: int) -> List[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM legs WHERE setup_id = ? ORDER BY idx", (setup_id,))]

    def update_leg(self, leg_id: int, **fields):
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE legs SET {sets} WHERE id = ?", [*fields.values(), leg_id])
        self.db.commit()

    def all_tickets(self) -> set:
        return {r[0] for r in self.db.execute("SELECT ticket FROM legs")}

    # --- events and key/value -----------------------------------------------
    def event(self, setup_id: Optional[int], kind: str, detail: str = ""):
        self.db.execute("INSERT INTO events (setup_id, time, kind, detail) VALUES (?, ?, ?, ?)",
                        (setup_id, self.clock(), kind, detail))
        self.db.commit()

    def events(self, setup_id: int) -> List[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM events WHERE setup_id = ? ORDER BY id", (setup_id,))]

    def get_kv(self, key: str, default=None):
        r = self.db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def set_kv(self, key: str, value):
        self.db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
                        (key, json.dumps(value)))
        self.db.commit()


def backup_path(db_path: str) -> str:
    """Where a reset keeps the old journal, e.g. data/jurnal-cadangan-20261029-213000.db."""
    return os.path.join(os.path.dirname(db_path), f"jurnal-cadangan-{time.strftime('%Y%m%d-%H%M%S')}.db")


def _row(r) -> Optional[dict]:
    if r is None:
        return None
    d = dict(r)
    d["tps"] = json.loads(d["tps"] or "[]")
    return d
