"""Collision-resistant local identifiers."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def new_id(prefix: str = "gen") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return f"{prefix}_{stamp}_{uuid4().hex[:8]}"
