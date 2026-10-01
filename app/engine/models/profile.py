from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class ModelProfile:
    """Model 프로필 (v0.1 §10, §44.7 models/profile.py).

    모델 아키텍처별로 다른 프롬프트 스타일, negative prompt 사용 여부,
    로더 전략을 정의한다.

    `source`는 이 프로필이 어디서 결정되었는지 기록한다 (v0.1 §11):
        "override"    - 사용자 강제 지정
        "config"      - image_profiles.json
        "heuristic"   - 파일명 휴리스틱
        "default"     - 기본 프로필
    """

    name: str
    kind: str
    architecture: str
    prompt_style: str = "sentence"
    use_negative: bool = True
    loader: str = "auto"
    estimated_vram: float | None = None
    default_steps: int = 20
    default_resolution: tuple[int, int] = (1024, 1024)
    sampler: str = "euler_a"
    scheduler: str = "default"
    source: str = "config"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
