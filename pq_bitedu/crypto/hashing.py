"""Hash helpers."""

from __future__ import annotations

import hashlib


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def hash_once(data: bytes) -> bytes:
    return sha256(data)


def hash_hex(data: bytes) -> str:
    return hash_once(data).hex()


def hash_int(data: bytes) -> int:
    return int.from_bytes(hash_once(data), "big")
