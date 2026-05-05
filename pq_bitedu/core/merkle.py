"""Merkle tree helpers."""

from __future__ import annotations

from typing import Iterable, List

from ..crypto.hashing import hash_hex


def merkle_root(items: Iterable[str]) -> str:
    level: List[str] = list(items)
    if not level:
        return hash_hex(b"")
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        next_level: List[str] = []
        for index in range(0, len(level), 2):
            next_level.append(hash_hex(bytes.fromhex(level[index]) + bytes.fromhex(level[index + 1])))
        level = next_level
    return level[0]
