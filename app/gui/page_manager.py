"""Lightweight page registry for the v0.7 modular GUI."""

from __future__ import annotations

from typing import Dict


class PageManager:
    """Registers named pages without coupling them to engine code."""

    def __init__(self) -> None:
        self._pages: Dict[str, object] = {}

    def register(self, name: str, page: object) -> None:
        self._pages[name] = page

    def get(self, name: str) -> object | None:
        return self._pages.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._pages)
