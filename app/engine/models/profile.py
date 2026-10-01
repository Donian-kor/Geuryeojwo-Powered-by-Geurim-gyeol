from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class ModelProfile:
    """Model 프로필 (v0.1 §10, §44.7 models/profile.py).

    모델 아키텍처별로 다른 프롬프트 스타일, negative prompt 사용 여부,
    로더 전략을 정의한다.
    """

    name: str
    kind: str
    architecture: str
    prompt_style: str = "sentence"
    use_negative: bool = True
    loader: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
