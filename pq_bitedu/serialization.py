"""Deterministic serialization helpers."""

from __future__ import annotations

import json
from typing import Any


def normalize_for_json(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    if isinstance(value, tuple):
        return [normalize_for_json(item) for item in value]
    if isinstance(value, list):
        return [normalize_for_json(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): normalize_for_json(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }
    return value


def canonical_json_bytes(value: Any) -> bytes:
    normalized = normalize_for_json(value)
    return json.dumps(
        normalized,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def decode_signature_json(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8"))
