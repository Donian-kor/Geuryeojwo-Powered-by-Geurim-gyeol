from __future__ import annotations

from pathlib import Path
import json

from .policy import PromptPolicy
from .builder import PromptBuilder, PromptResult
from .validator import PromptValidator, ValidationResult


class PromptEngine:
    """프롬프트 엔진 (v0.1 §13, §44.7).

    Policy, Builder, Validator 하위 모듈을 조합하여
    프롬프트 강화, 빌드, 검증을 수행한다.
    """

    def __init__(self, profile_file: Path, dictionary_file: Path, logger=None):
        self.logger = logger
        self.policy = PromptPolicy(profile_file)
        self.dictionary = json.loads(dictionary_file.read_text(encoding="utf-8")) if dictionary_file.exists() else {}
        self.builder = PromptBuilder(self.policy, logger)
        self.validator = PromptValidator(logger)

    def policy_for(self, architecture: str) -> dict:
        """아키텍처별 정책 반환 (backward compat)."""
        return self.policy.get_policy(architecture)

    def system_prompt(self, architecture: str) -> str:
        """시스템 프롬프트 반환 (backward compat)."""
        return self.policy.system_prompt(architecture)

    def fallback(self, user: str, architecture: str) -> str:
        """LLM 없이 대체 프롬프트 생성 (backward compat)."""
        return self.policy.fallback(user, architecture)

    def negative(self, architecture: str, enabled: bool = True) -> str:
        """Negative prompt 생성 (backward compat)."""
        return self.policy.negative_prompt(architecture, self.dictionary, enabled)

    def build(self, user_prompt: str, architecture: str, llm=None) -> tuple[str, str]:
        """프롬프트 빌드 - positive, negative 반환."""
        result = self.builder.build(user_prompt, architecture, llm, self.dictionary)
        return result.positive, result.negative

    def validate_prompt(self, prompt: str) -> ValidationResult:
        """프롬프트 검증."""
        return self.validator.validate_prompt(prompt)

    def validate_parameters(self, width: int, height: int, steps: int, cfg: float) -> ValidationResult:
        """파라미터 검증."""
        return self.validator.validate_parameters(width, height, steps, cfg)

    def build_validated(
        self,
        user_prompt: str,
        architecture: str,
        width: int,
        height: int,
        steps: int,
        cfg: float,
        llm=None,
    ) -> PromptResult:
        """검증 + 빌드를 한 번에 수행한다."""
        validation = self.validate_prompt(user_prompt)
        if not validation.valid:
            raise ValueError(f"Prompt validation failed: {'; '.join(validation.errors)}")

        return self.builder.build(user_prompt, architecture, llm, self.dictionary)
