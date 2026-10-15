"""Load KEY=value pairs from ./.env into the environment (real env vars always win)."""
from __future__ import annotations

import os
from pathlib import Path


def load(path: Path | None = None) -> None:
    p = path or Path(__file__).resolve().parent.parent / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        if k.strip() and v and k.strip() not in os.environ:
            os.environ[k.strip()] = v
