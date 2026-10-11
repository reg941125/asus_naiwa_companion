import json
import os
import sqlite3
from pathlib import Path

class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, check_same_thread=False)
        os.chmod(path, 0o600)
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at REAL, kind TEXT, payload TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT)")
        self.db.commit()

    def event(self, at, kind, payload):
        self.db.execute("INSERT INTO events(at,kind,payload) VALUES (?,?,?)", (at, kind, json.dumps(payload)))
        self.db.commit()

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO preferences VALUES (?,?)", (key, json.dumps(value)))
        self.db.commit()

    def delete_all(self):
        self.db.execute("DELETE FROM events")
        self.db.execute("DELETE FROM preferences")
        self.db.commit()

    def close(self):
        self.db.close()
