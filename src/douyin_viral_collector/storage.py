import contextlib
import json
import os
import sqlite3
from pathlib import Path


@contextlib.contextmanager
def lock(path):
    """OS releases the advisory lock even after a process crash."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open('a+b')
    try:
        f.seek(0)
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                f.write(b'0'); f.flush()
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise RuntimeError('another collect task is running') from None
    try:
        yield
    finally:
        f.close()


class Store:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'collect.sqlite3', timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,name TEXT,status TEXT,last_check TEXT,error TEXT);
        CREATE TABLE IF NOT EXISTS works(
          account_id TEXT, id TEXT, payload TEXT, likes INTEGER, status TEXT DEFAULT 'discovered',
          raw TEXT, body TEXT, checked_at TEXT, archived_at TEXT, attempts INTEGER DEFAULT 0,
          error TEXT, PRIMARY KEY(account_id,id));
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS events(at TEXT DEFAULT CURRENT_TIMESTAMP,kind TEXT,message TEXT);
        PRAGMA user_version=1;
        ''')
        self.db.commit()

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def execute(self, sql, args=()):
        with self.db:
            return self.db.execute(sql, args)

    def event(self, kind, message):
        self.execute('INSERT INTO events(kind,message) VALUES(?,?)', (kind, message))

    def get(self, key, default=None):
        r = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def set(self, key, value):
        self.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, json.dumps(value)))

    def backup(self):
        import time
        p = self.root / 'backups' / (str(time.time_ns()) + '.sqlite3')
        p.parent.mkdir(exist_ok=True)
        with contextlib.closing(sqlite3.connect(p)) as target:
            self.db.backup(target)
        return str(p)
