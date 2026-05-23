"""
Tiny Fernet wrapper for encrypting per-guild Navidrome credentials
before they hit SQLite. The key comes from BOT_SECRET_KEY in the env
(must be a 32-byte url-safe base64 string; generate with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).

If the env key changes, all stored credentials become unreadable -
admins would need to re-run /library setup. This is intentional: it's
how you "rotate" credentials if you suspect the DB leaked.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet


_fernet: Fernet | None = None


def _instance() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.environ.get("BOT_SECRET_KEY")
        if not key:
            raise RuntimeError(
                "BOT_SECRET_KEY not set. Generate one with:\n"
                "  python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(value: str) -> str:
    return _instance().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt(value: str) -> str:
    return _instance().decrypt(value.encode("utf-8")).decode("utf-8")
