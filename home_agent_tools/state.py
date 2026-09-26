"""Local control store. Credential material is hashed or stored in the encrypted vault."""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class State:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.db() as db:
            db.executescript(
                """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS agents (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
              fingerprint TEXT UNIQUE NOT NULL, token_id TEXT NOT NULL,
              services TEXT NOT NULL, expires REAL NOT NULL, active INTEGER NOT NULL,
              created REAL NOT NULL, last_used REAL);
            CREATE TABLE IF NOT EXISTS observations (
              owner TEXT NOT NULL, service TEXT NOT NULL, status TEXT NOT NULL,
              identity TEXT, checked REAL NOT NULL, PRIMARY KEY(owner,service));
            CREATE TABLE IF NOT EXISTS events (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, actor TEXT NOT NULL,
              action TEXT NOT NULL, service TEXT, outcome TEXT NOT NULL, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS requests (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, agent TEXT NOT NULL,
              service TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS secrets (
              kind TEXT NOT NULL, owner TEXT NOT NULL, encrypted TEXT NOT NULL,
              PRIMARY KEY(kind,owner));
            CREATE TABLE IF NOT EXISTS oauth_clients (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, redirects TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS authorizations (
              id TEXT PRIMARY KEY, client TEXT NOT NULL, redirect TEXT NOT NULL,
              state TEXT NOT NULL, challenge TEXT NOT NULL, services TEXT NOT NULL,
              days INTEGER NOT NULL, owner TEXT, status TEXT NOT NULL, expires REAL NOT NULL,
              code_hash TEXT, agent TEXT);
            CREATE TABLE IF NOT EXISTS access_tokens (
              hash TEXT PRIMARY KEY, agent TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS refresh_tokens (
              hash TEXT PRIMARY KEY, agent TEXT NOT NULL, client TEXT NOT NULL,
              consumed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS ha_states (
              hash TEXT PRIMARY KEY, owner TEXT NOT NULL, binding TEXT NOT NULL,
              expires REAL NOT NULL);
            """
            )

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, owner, actor, action, service=None, outcome="success"):
        with self.db() as db:
            db.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, owner, actor, action, service, outcome, time.time()),
            )
            # Bounded retention; never retain tool arguments/results or tokens.
            db.execute("DELETE FROM events WHERE at < ?", (time.time() - 30 * 86400,))

    def observation(self, owner, service, status, identity=None):
        with self.db() as db:
            old = db.execute(
                "SELECT identity FROM observations WHERE owner=? AND service=?",
                (owner, service),
            ).fetchone()
            changed = bool(
                old and old["identity"] and identity and old["identity"] != identity
            )
            if changed:
                # A different upstream account must not inherit agent grants.
                for row in db.execute(
                    "SELECT id,services FROM agents WHERE owner=? AND active=1",
                    (owner,),
                ).fetchall():
                    if service in json.loads(row["services"]):
                        db.execute(
                            "UPDATE agents SET active=0 WHERE id=?", (row["id"],)
                        )
            # A transient failure must not erase the last verified identity.
            retained_identity = identity or (old["identity"] if old else None)
            db.execute(
                "INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?)",
                (owner, service, status, retained_identity, time.time()),
            )
        return changed

    def request(self, owner, agent, service):
        now = time.time()
        with self.db() as db:
            existing = db.execute(
                "SELECT id FROM requests WHERE owner=? AND agent=? AND service=? AND status='pending' AND expires>?",
                (owner, agent, service, now),
            ).fetchone()
            if existing:
                return existing["id"]
            request_id = uuid.uuid4().hex
            db.execute(
                "INSERT INTO requests VALUES (?,?,?,?,?,?,?)",
                (request_id, owner, agent, service, "pending", now, now + 86400),
            )
            return request_id
