"""Generation/result data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerationRecord:
    generation_id: str
    original_prompt: str
    enhanced_prompt: str | None = None
    negative_prompt: str | None = None
    workflow: str | None = None
    workflow_hash: str | None = None
    model: str | None = None
    seed: int | None = None
    results: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
