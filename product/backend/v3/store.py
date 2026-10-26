"""Transactional metadata index. Immutable result files never live in this index."""
from pathlib import Path
import json
import sqlite3
import threading
from contextlib import contextmanager


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, id TEXT NOT NULL, created TEXT NOT NULL,
                    status TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind,id));
                CREATE INDEX IF NOT EXISTS records_order ON records(kind,created DESC,id DESC);
                CREATE TABLE IF NOT EXISTS idempotency (
                    kind TEXT NOT NULL, key TEXT NOT NULL, body_hash TEXT NOT NULL,
                    record_id TEXT NOT NULL, PRIMARY KEY(kind,key));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, kind, value):
        with self.lock, self.connect() as db:
            db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?,?,?)',
                       (kind, value['id'], value['created_at'], value.get('status'),
                        json.dumps(value, ensure_ascii=False, allow_nan=False)))
        return value

    def get(self, kind, ident):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM records WHERE kind=? AND id=?', (kind, ident)).fetchone()
        return json.loads(row['payload']) if row else None

    def patch(self, kind, ident, **changes):
        with self.lock:
            value = self.get(kind, ident)
            if value is None:
                raise KeyError(ident)
            value.update(changes)
            return self.put(kind, value)

    def list(self, kind, limit=50, cursor=None, status=None):
        params = [kind]
        where = 'kind=?'
        if status:
            where += ' AND status=?'
            params.append(status)
        if cursor:
            anchor = self.get(kind, cursor)
            if not anchor:
                raise ValueError('分页游标不存在')
            where += ' AND (created < ? OR (created = ? AND id < ?))'
            params += [anchor['created_at'], anchor['created_at'], cursor]
        params.append(limit + 1)
        with self.connect() as db:
            rows = db.execute(f'SELECT payload FROM records WHERE {where} ORDER BY created DESC,id DESC LIMIT ?', params).fetchall()
        values = [json.loads(r['payload']) for r in rows]
        return values[:limit], values[limit-1]['id'] if len(values) > limit else None

    def all(self, kind):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM records WHERE kind=?', (kind,)).fetchall()
        return [json.loads(row['payload']) for row in rows]

    def lookup_key(self, kind, key):
        if not key:
            return None
        with self.connect() as db:
            row = db.execute('SELECT body_hash,record_id FROM idempotency WHERE kind=? AND key=?', (kind, key)).fetchone()
        return tuple(row) if row else None

    def reserve(self, kind, key, body_hash, value):
        """Caller serializes queue capacity; this transaction couples key and record."""
        with self.lock, self.connect() as db:
            if key:
                db.execute('INSERT INTO idempotency VALUES (?,?,?,?)', (kind, key, body_hash, value['id']))
            db.execute('INSERT INTO records VALUES (?,?,?,?,?)', (kind, value['id'], value['created_at'], value.get('status'), json.dumps(value, ensure_ascii=False)))
        return value
