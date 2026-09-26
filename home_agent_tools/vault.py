"""Authenticated encryption for credentials that must survive browser logout."""

import base64
import json

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class Vault:
    def __init__(self, state, secret):
        self.state = state
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"home-agent-tools/credential-vault/v1",
        ).derive(secret.encode())
        self.cipher = Fernet(base64.urlsafe_b64encode(key))

    def put(self, kind, owner, value, db=None):
        encrypted = self.cipher.encrypt(
            json.dumps({"kind": kind, "owner": owner, "value": value}).encode()
        ).decode()
        if db is not None:
            db.execute(
                "INSERT OR REPLACE INTO secrets VALUES (?,?,?)",
                (kind, owner, encrypted),
            )
        else:
            with self.state.db() as conn:
                self.put(kind, owner, value, conn)

    def get(self, kind, owner):
        with self.state.db() as db:
            row = db.execute(
                "SELECT encrypted FROM secrets WHERE kind=? AND owner=?", (kind, owner)
            ).fetchone()
        if not row:
            return None
        value = json.loads(self.cipher.decrypt(row["encrypted"].encode()))
        if value["kind"] != kind or value["owner"] != owner:
            raise InvalidToken("Credential binding mismatch")
        return value["value"]

    def delete(self, kind, owner):
        with self.state.db() as db:
            db.execute("DELETE FROM secrets WHERE kind=? AND owner=?", (kind, owner))
