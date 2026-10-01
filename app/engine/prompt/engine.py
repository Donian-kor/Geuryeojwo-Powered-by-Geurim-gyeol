from __future__ import annotations

from pathlib import Path
import json

from .policy import PromptPolicy
from .builder import PromptBuilder, PromptResult
from .validator import PromptValidator, ValidationResult


class LlmProfile:
    """LLM 프로필 (v0.1 §14).

    LLM은 프롬프트를 생성하는 엔진일 뿐이며, 최종 출력 형식은
    Target Image Model의 prompt_style이 결정한다.
    이 프로필은 LLM의 언어 능력과 권장 생성 파라미터만 제공한다.
    """

    DEFAULT = {
        "instruction_following": True,
        "multilingual": False,
        "korean_support": False,
        "max_context": 4096,
        "recommended_temperature": 0.7,
        "recommended_token_limit": 500,
    }

    def __init__(self, profile_file: Path | None = None):
        self._profiles: dict = {}
        if profile_file and profile_file.exists():
            try:
                self._profiles = json.loads(profile_file.read_text(encoding="utf-8"))
            except Exception:
                self._profiles = {}

    def get(self, model_name: str | Path | None) -> dict:
        """모델명으로 LLM 프로필 조회 (없으면 default)."""
        if model_name is None:
            return dict(self.DEFAULT)
        name = Path(model_name).name.lower()
        for key, profile in self._profiles.items():
            if key.startswith("_"):
                continue
            if key in name:
                return {**self.DEFAULT, **profile}
        return dict(self.DEFAULT)


class PromptEngine:
    """프롬프트 엔진 (v0.1 §13, §14, §44.7).

    Policy, Builder, Validator 하위 모듈을 조합하여
    프롬프트 강화, 빌드, 검증을 수행한다.
    """

    def __init__(
        self,
        profile_file: Path,
        dictionary_file: Path,
        logger=None,
        llm_profile_file: Path | None = None,
    ):
        self.logger = logger
        self.policy = PromptPolicy(profile_file)
        self.dictionary = json.loads(dictionary_file.read_text(encoding="utf-8")) if dictionary_file.exists() else {}
        self.llm_profiles = LlmProfile(llm_profile_file)
        self.builder = PromptBuilder(self.policy, logger, self.dictionary)
        self.validator = PromptValidator(logger)

    def llm_profile_for(self, model_name: str | Path | None) -> dict:
        """LLM 프로필 조회 (v0.1 §14)."""
        return self.llm_profiles.get(model_name)

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

    def build(self, user_prompt: str, architecture: str, llm=None, llm_name=None) -> PromptResult:
        """프롬프트 빌드 - PromptResult 반환."""
        return self.builder.build(user_prompt, architecture, llm, llm_name)

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
        llm_name=None,
    ) -> PromptResult:
        """검증 + 빌드를 한 번에 수행한다."""
        validation = self.validate_prompt(user_prompt)
        if not validation.valid:
            raise ValueError(f"Prompt validation failed: {'; '.join(validation.errors)}")

        return self.builder.build(user_prompt, architecture, llm, llm_name)
