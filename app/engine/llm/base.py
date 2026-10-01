from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path


class BaseLLM(ABC):
    """LLM Adapter 추상 베이스 (v0.1 §44.7 llm/base.py).

    Local LLM 로드/생성/언로드의 공통 인터페이스를 정의한다.
    """

    @abstractmethod
    def load(self):
        """LLM을 메모리에 로드한다."""

    @abstractmethod
    def generate(self, system: str, user: str, temperature: float = 0.7, max_tokens: int = 500) -> str:
        """시스템 프롬프트와 사용자 프롬프트로부터 텍스트를 생성한다."""

    @abstractmethod
    def unload(self) -> None:
        """LLM을 메모리에서 언로드한다."""
