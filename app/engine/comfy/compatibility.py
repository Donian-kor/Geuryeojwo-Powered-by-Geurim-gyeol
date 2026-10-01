"""ComfyUI compatibility helpers.

Keep API-version-specific behavior here so GUI and workflow code do not need
ComfyUI-version conditionals.
"""

from __future__ import annotations


def prompt_interrupt_payload(prompt_id: str | None) -> dict:
    """Return a prompt-specific interrupt payload when possible."""
    return {"prompt_id": prompt_id} if prompt_id else {}


def vram_display_value(value) -> str:
    """Format optional VRAM values without raising on missing server data."""
    if value is None:
        return "정보 없음"
    try:
        return f"{float(value):.1f} GB"
    except (TypeError, ValueError):
        return "정보 없음"
