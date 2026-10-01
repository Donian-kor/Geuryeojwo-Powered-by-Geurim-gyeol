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

    def __init__(self, policy, logger=None, negative_dict: dict | None = None):
        self.policy = policy
        self.logger = logger
        self.negative_dict = negative_dict or {}

    def build(self, user_prompt: str, architecture: str, llm=None, llm_name=None) -> PromptResult:
        """프롬프트 빌드 - positive, negative 반환.

        Args:
            user_prompt: 사용자 원본 프롬프트
            architecture: 이미지 모델 아키텍처 (sd15, sdxl, etc.)
            llm: 선택사항 LLM (프롬프트 강화용)
            llm_name: LLM 모델명 — LLM 프로필 조회용 (v0.1 §14)
        """
        original = user_prompt

        if llm:
            try:
                profile = getattr(llm, "profile", None)
                if llm_name is not None and profile:
                    temperature = profile.get("recommended_temperature", 0.7)
                    max_tokens = profile.get("recommended_token_limit", 500)
                else:
                    temperature, max_tokens = 0.7, 500
                positive = llm.generate(
                    self.policy.system_prompt(architecture),
                    user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
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
            architecture, self.negative_dict or {}, True
        )

        return PromptResult(
            positive=positive.strip(),
            negative=negative,
            original=original,
            enhanced=enhanced,
            policy_used=self.policy.get_prompt_style(architecture),
        )
