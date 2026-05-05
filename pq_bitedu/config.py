"""Configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


def load_env_file(path: str = ".env", override: bool = False) -> Dict[str, str]:
    """
    Load a minimal dotenv file containing KEY=VALUE pairs.

    This avoids adding another dependency just to load API keys locally.
    """

    env_path = Path(path)
    if not env_path.is_absolute():
        env_path = Path(__file__).resolve().parents[1] / env_path
    loaded: Dict[str, str] = {}
    if not env_path.exists():
        return loaded

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = value
        loaded[key] = value
    return loaded
