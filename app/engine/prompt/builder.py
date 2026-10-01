from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PromptResult:
    """프롬프트 빌드 결과 (v0.1 §44.7 prompt/builder.py)."""

    positive: str
    negative: str
    original: str
    enhanced: bool
    policy_used: str


class PromptBuilder:
    """프롬프트 빌드기 (v0.1 §44.7 prompt/builder.py).

    원본 프롬프트 → 강화 프롬프트 + negative prompt 빌드.
    """

    def __init__(self, policy, logger=None):
        self.policy = policy
        self.logger = logger

    def build(
        self,
        user_prompt: str,
        architecture: str,
        llm=None,
        negative_dict: dict | None = None,
    ) -> PromptResult:
        """프롬프트를 빌드한다.

        Args:
            user_prompt: 사용자 원본 프롬프트
            architecture: 이미지 모델 아키텍처 (sd15, sdxl, etc.)
            llm: 선택사항 LLM (프롬프트 강화용)
            negative_dict: negative dictionary (prompt_profiles.json에서 로드)

        Returns:
            PromptResult: positive, negative, original, enhanced, policy_used
        """
        original = user_prompt

        if llm:
            try:
                positive = llm.generate(
                    self.policy.system_prompt(architecture),
                    user_prompt,
                )
                enhanced = True
            except Exception as exc:
                if self.logger:
                    self.logger.warning("LLM prompt enhancement failed: %s", exc)
                positive = self.policy.fallback(user_prompt, architecture)
                enhanced = False
        else:
            positive = self.policy.fallback(user_prompt, architecture)
            enhanced = False

        negative = self.policy.negative_prompt(
            architecture, negative_dict or {}, True
        )

        return PromptResult(
            positive=positive.strip(),
            negative=negative,
            original=original,
            enhanced=enhanced,
            policy_used=self.policy.get_prompt_style(architecture),
        )
