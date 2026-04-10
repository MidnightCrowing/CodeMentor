"""
core/security.py
================
Lightweight password hashing utilities.
"""

from __future__ import annotations

import hashlib
import secrets


def hash_password(password: str, rounds: int = 120_000) -> str:
    """
    Hash password using PBKDF2-HMAC-SHA256.

    Stored format: pbkdf2_sha256$<rounds>$<salt>$<hash>
    """
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), rounds)
    return f"pbkdf2_sha256${rounds}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds_str, salt, digest = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        rounds = int(rounds_str)
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), rounds)
    return secrets.compare_digest(dk.hex(), digest)
