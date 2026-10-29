"""Read-only dashboard I/O, run away from the Qt event loop."""
import errno
import json
import socket
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from copier.config import load_config
from copier.single import BOT_PORT, READER_PORT
from .control import FRESH_SECONDS, journal_snapshot
from .runtime import reader_state


def port_in_use(port):
    """Inspect the single-instance lock without connecting to its unaccepted backlog.

    The original lock holds an exclusive bind. A temporary bind either succeeds
    immediately (free) or fails immediately (in use). It never sends a packet.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(('127.0.0.1', port))
            return False
        except OSError as exc:
            if exc.errno in (errno.EADDRINUSE, errno.EACCES) or getattr(exc,'winerror',None) in (10048,10013):
                return True
            raise


class DashboardReader:
    def __init__(self, root, control_path):
        self.root, self.control_path = Path(root), Path(control_path)
        self._log_key = None
        self._log_text = ''

    def poll(self, command_ids=(), log_index=0):
        snapshot, results = {}, {}
        if self.control_path.exists():
            with closing(sqlite3.connect(self.control_path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
                db.row_factory=sqlite3.Row
                db.execute('BEGIN')
                state=db.execute('SELECT data FROM state WHERE id=1').fetchone()
                snapshot=json.loads(state['data']) if state else {}
                if command_ids:
                    marks=','.join('?' for _ in command_ids)
                    results={r['id']:dict(r) for r in db.execute(
                        f'SELECT id,status,result FROM commands WHERE id IN ({marks})',tuple(command_ids))}
        fresh=bool(snapshot.get('online') and 0<=time.time()-snapshot.get('heartbeat',0)<FRESH_SECONDS)
        if fresh:
            rows,events=snapshot.get('setups',[]),snapshot.get('events',[])
        else:
            cfg=load_config(self.root/'config.yaml')
            rows,events=journal_snapshot(self.root/cfg['bot']['jurnal'])
        reader=reader_state(self.root)
        reader_fresh=bool(reader.get('online') and 0<=time.time()-reader.get('heartbeat',0)<15)
        data=dict(snapshot=snapshot,rows=rows,events=events,results=results,
                  bot_on=fresh or port_in_use(BOT_PORT),
                  reader_on=reader_fresh or port_in_use(READER_PORT),log_index=log_index)
        if log_index:
            path=self.root/'logs'/['bot.log','pembaca.log','desktop-bot.log','desktop-reader.log'][log_index-1]
            try:
                stat=path.stat();key=(str(path),stat.st_mtime_ns,stat.st_size)
                if key!=self._log_key:
                    with path.open('rb') as stream:
                        stream.seek(max(0,stat.st_size-40000))
                        self._log_text=stream.read().decode('utf-8','replace')
                    self._log_key=key
                data['log_text']=self._log_text
            except OSError:
                data['log_text']='Belum ada log.'
        return data
