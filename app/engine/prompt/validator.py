from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValidationResult:
    """프롬프트 검증 결과 (v0.1 §44.7 prompt/validator.py)."""

    valid: bool
    errors: list[str]
    warnings: list[str]
    suggestions: list[str]


class PromptValidator:
    """프롬프트 검증기 (v0.1 §44.7 prompt/validator.py).

    프롬프트의 유효성, 안전성, 품질을 검증한다.
    """

    MIN_PROMPT_LENGTH = 3
    MAX_PROMPT_LENGTH = 2000
    MAX_SEED = 2**31 - 1

    FORBIDDEN_PATTERNS = [
        (r"<script", "스크립트 태그는 허용되지 않습니다"),
        (r"javascript:", "JavaScript 프로토콜은 허용되지 않습니다"),
        (r"data:text/html", "데이터 URL HTML은 허용되지 않습니다"),
    ]

    def __init__(self, logger=None):
        self.logger = logger

    def validate_prompt(self, prompt: str) -> ValidationResult:
        """프롬프트 유효성 검사."""
        errors = []
        warnings = []
        suggestions = []

        if not prompt or not prompt.strip():
            errors.append("프롬프트가 비어 있습니다")
            return ValidationResult(False, errors, warnings, suggestions)

        cleaned = prompt.strip()

        if len(cleaned) < self.MIN_PROMPT_LENGTH:
            errors.append(f"프롬프트가 너무 짧습니다 (최소 {self.MIN_PROMPT_LENGTH}자)")

        if len(cleaned) > self.MAX_PROMPT_LENGTH:
            errors.append(f"프롬프트가 너무 깁니다 (최대 {self.MAX_PROMPT_LENGTH}자)")

        for pattern, message in self.FORBIDDEN_PATTERNS:
            import re
            if re.search(pattern, cleaned, re.IGNORECASE):
                errors.append(message)

        if len(cleaned.split()) < 3:
            warnings.append("프롬프트가 구체적이지 않을 수 있습니다")

        if "..." in cleaned:
            suggestions.append("불필요한 생략 부호(...)를 제거하는 것을 권장합니다")

        valid = len(errors) == 0

        if not valid and self.logger:
            self.logger.warning("Prompt validation failed: %s", "; ".join(errors))

        return ValidationResult(valid, errors, warnings, suggestions)

    def validate_parameters(
        self,
        width: int,
        height: int,
        steps: int,
        cfg: float,
    ) -> ValidationResult:
        """생성 파라미터 검증."""
        errors = []
        warnings = []
        suggestions = []

        if width <= 0 or height <= 0:
            errors.append("너비와 높이는 양수여야 합니다")
        elif width > 2048 or height > 2048:
            warnings.append("해상도가 높아 VRAM 부족이 발생할 수 있습니다")
        elif width % 8 != 0 or height % 8 != 0:
            errors.append("너비와 높이는 8의 배수여야 합니다")

        if steps <= 0:
            errors.append("Steps는 0보다 커야 합니다")
        elif steps > 100:
            warnings.append("Steps가 많아 생성 시간이 오래 걸립니다")
        elif steps < 10:
            warnings.append("Steps가 낮아 품질이 떨어질 수 있습니다")

        if cfg < 1.0:
            errors.append("CFG는 1.0 이상이어야 합니다")
        elif cfg > 20.0:
            warnings.append("CFG가 높아 이미지 왜곡이 발생할 수 있습니다")
        elif cfg < 5.0:
            warnings.append("CFG가 낮아 프롬프트 반영도가 낮을 수 있습니다")

        valid = len(errors) == 0
        return ValidationResult(valid, errors, warnings, suggestions)

    def validate_seed(self, seed: int) -> bool:
        """Seed 값 검증."""
        return 0 <= seed <= self.MAX_SEED
