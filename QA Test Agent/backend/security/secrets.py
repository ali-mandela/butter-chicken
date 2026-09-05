"""In-memory secret store.

Credentials are NEVER written to the database, logs, traces, reports, or
LLM prompts. They live only in this process's memory, keyed by an opaque
`credential_ref`, and are resolved by the browser/execution layer at the
last possible moment. If SECRET_ENCRYPTION_KEY is set, values are encrypted
at rest in memory as well (defense in depth against memory dumps/logging
bugs), otherwise they are held in a plain dict for local/dev use.
"""
from __future__ import annotations

import base64
import os
import uuid
from dataclasses import dataclass
from typing import Optional

from cryptography.fernet import Fernet

from config.settings import get_settings

_MASK = "********"


@dataclass
class Credential:
    auth_type: str
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    oauth_config: Optional[dict] = None


class SecretStore:
    def __init__(self) -> None:
        settings = get_settings()
        key = settings.secret_encryption_key
        if key:
            self._fernet = Fernet(key.encode() if len(key) == 44 else Fernet.generate_key())
        else:
            self._fernet = Fernet(Fernet.generate_key())
        self._store: dict[str, bytes] = {}

    def put(self, credential: Credential) -> str:
        ref = f"cred-{uuid.uuid4().hex[:12]}"
        payload = _serialize(credential)
        self._store[ref] = self._fernet.encrypt(payload.encode())
        return ref

    def get(self, ref: str) -> Optional[Credential]:
        blob = self._store.get(ref)
        if blob is None:
            return None
        return _deserialize(self._fernet.decrypt(blob).decode())

    def delete(self, ref: str) -> None:
        self._store.pop(ref, None)

    @staticmethod
    def mask(_value: Optional[str]) -> str:
        return _MASK if _value else ""


def _serialize(c: Credential) -> str:
    import json

    return json.dumps(c.__dict__)


def _deserialize(raw: str) -> Credential:
    import json

    return Credential(**json.loads(raw))


_secret_store: Optional[SecretStore] = None


def get_secret_store() -> SecretStore:
    global _secret_store
    if _secret_store is None:
        _secret_store = SecretStore()
    return _secret_store
