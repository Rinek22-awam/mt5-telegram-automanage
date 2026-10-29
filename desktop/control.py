"""Local durable command queue. Only the bot process executes commands.

Commands belong to one bot session and the account/scope shown at confirmation.
An interrupted processing command is never retried automatically.
"""
import json
import sqlite3
import time
import uuid
from pathlib import Path
from contextlib import closing

FRESH_SECONDS = 30


class ControlStore:
    def __init__(self, path, clock=time.time, timeout=3):
        self.path, self.clock = str(path), clock
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=timeout)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, data TEXT);
        CREATE TABLE IF NOT EXISTS commands (
          id TEXT PRIMARY KEY, session TEXT, created REAL, expires REAL,
          payload TEXT, status TEXT, result TEXT);
        ''')

    def close(self):
        self.db.close()

    def publish(self, snapshot):
        snapshot = dict(snapshot, heartbeat=self.clock())
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES (1, ?)',
                            (json.dumps(snapshot, allow_nan=False),))

    def snapshot(self):
        row = self.db.execute('SELECT data FROM state WHERE id=1').fetchone()
        return json.loads(row['data']) if row else {}

    def fresh(self, snapshot=None):
        s = self.snapshot() if snapshot is None else snapshot
        return bool(s.get('online') and 0 <= self.clock()-s.get('heartbeat', 0) < FRESH_SECONDS)

    def submit(self, action, expected, setup_id=None):
        if not self.fresh(expected):
            raise ValueError('Bot tidak terhubung atau data sudah basi. Tunggu penyegaran.')
        payload = dict(action=action, setup_id=setup_id, account=expected['account_key'],
                       scope=scope_for(expected['setups'], action, setup_id))
        cid, now = uuid.uuid4().hex, self.clock()
        with self.db:
            self.db.execute('INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?, ?)',
                            (cid, expected['session'], now, now+90, json.dumps(payload), 'queued', ''))
        return cid

    def take(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute("SELECT * FROM commands WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                self.db.execute("UPDATE commands SET status='processing' WHERE id=?", (row['id'],))
        return dict(row) if row else None

    def finish(self, cid, status, result):
        with self.db:
            self.db.execute('UPDATE commands SET status=?, result=? WHERE id=?', (status, result, cid))

    def result(self, cid):
        r = self.db.execute('SELECT status,result FROM commands WHERE id=?', (cid,)).fetchone()
        return dict(r) if r else None

    def recover(self):
        with self.db:
            self.db.execute("UPDATE commands SET status='unknown', result=? WHERE status='processing'",
                            ('Proses sebelumnya terputus. Periksa MT5/jurnal; perintah tidak diulang.',))


def scope_for(rows, action, sid=None):
    """Bind destructive confirmation to exactly the setups and legs displayed."""
    if sid is not None:
        chosen = [r for r in rows if r['id'] == sid]
    elif action in ('close_all', 'cancel_all', 'pause', 'reset'):
        chosen = [r for r in rows if r['status'] in ('pending', 'running')]
    else:
        chosen = []
    if action in ('cancel_all', 'pause'):
        chosen = [r for r in chosen if any(l['status']=='pending' for l in r.get('legs', []))]
    return [dict(id=r['id'], created=r['created'], status=r['status'],
                 legs=[(l['ticket'], l['status']) for l in r.get('legs', [])]) for r in sorted(chosen,key=lambda r:r['id'])]


def journal_snapshot(path):
    """Read existing journal without creating or migrating it."""
    p = Path(path).resolve()
    if not p.exists():
        return [], []
    with closing(sqlite3.connect(p.as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        rows = [dict(r) for r in db.execute("SELECT * FROM setups ORDER BY id DESC LIMIT 300")]
        active_ids = {r['id'] for r in rows}
        for r in db.execute("SELECT * FROM setups WHERE status IN ('pending','running','awaiting_confirm') ORDER BY id DESC"):
            if r['id'] not in active_ids:
                rows.append(dict(r))
        for r in rows:
            r['tps'] = json.loads(r['tps'] or '[]')
            r['legs'] = [dict(l) for l in db.execute('SELECT * FROM legs WHERE setup_id=? ORDER BY idx',(r['id'],))]
        events = [dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 100')]
        return rows, events
