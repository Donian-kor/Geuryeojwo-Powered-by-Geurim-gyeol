from __future__ import annotations

import json
from pathlib import Path


class PromptPolicy:
    """Prompt 정책 관리 (v0.1 §13, §44.7 prompt/policy.py).

    모델 아키텍처별로 다른 프롬프트 스타일(tag/sentence)과
    negative prompt 사용 여부를 결정한다.
    """

    DEFAULT_POLICY = {
        "prompt_style": "sentence",
        "use_negative": True,
    }

    SYSTEM_PROMPTS = {
        "tag": (
            "Convert the user's idea into concise English image tags "
            "separated by commas. Do not write a prose sentence. "
            "Preserve concrete subject, clothing, environment, lighting, "
            "composition and style. Output only the final prompt."
        ),
        "sentence": (
            "Expand the user's idea into one detailed, coherent English "
            "visual description. Do not add explanations or headings. "
            "Describe subject, composition, environment, lighting, "
            "camera/view, materials and artistic style when useful. "
            "Output only the final image prompt."
        ),
    }

    FALLBACK_SUFFIXES = {
        "sd15": "detailed illustration, cinematic lighting, high detail",
        "sd21": "detailed illustration, cinematic lighting, high detail",
        "sdxl": "A detailed visual scene of {prompt}, natural composition, refined lighting, high detail",
        "flux": "A detailed visual scene of {prompt}, natural composition, refined lighting, high detail",
    }

    def __init__(self, profile_file: Path):
        self._profiles: dict = {}
        if profile_file.exists():
            self._profiles = json.loads(profile_file.read_text(encoding="utf-8"))

    def get_policy(self, architecture: str) -> dict:
        """아키텍처별 프롬프트 정책 반환."""
        return self._profiles.get(
            architecture,
            self._profiles.get("default", dict(self.DEFAULT_POLICY)),
        )

    def get_prompt_style(self, architecture: str) -> str:
        """프롬프트 스타일 (tag/sentence) 반환."""
        return self.get_policy(architecture).get("prompt_style", "sentence")

    def use_negative_prompt(self, architecture: str) -> bool:
        """Negative prompt 사용 여부 반환."""
        return self.get_policy(architecture).get("use_negative", True)

    def system_prompt(self, architecture: str) -> str:
        """LLM에 전달할 시스템 프롬프트 반환."""
        style = self.get_prompt_style(architecture)
        return self.SYSTEM_PROMPTS[style]

    def fallback(self, user_prompt: str, architecture: str) -> str:
        """LLM 없이 대체 프롬프트 생성."""
        import re
        cleaned = re.sub(r"\s+", " ", user_prompt).strip()
        if not cleaned:
            return ""

        if architecture in ("sd15", "sd21"):
            suffix = self.FALLBACK_SUFFIXES.get(architecture, "detailed illustration, cinematic lighting, high detail")
            return f"{cleaned}, {suffix}"

        template = self.FALLBACK_SUFFIXES.get(architecture)
        if template and "{prompt}" in template:
            return template.format(prompt=cleaned)
        return f"A detailed visual scene of {cleaned}, natural composition, refined lighting, high detail"

    def negative_prompt(self, architecture: str, dictionary: dict, enabled: bool = True) -> str:
        """Negative dictionary 기반 negative prompt 생성."""
        if not enabled or not self.use_negative_prompt(architecture):
            return ""
        parts = []
        for key in ("quality_tags", "anatomy_tags"):
            parts.extend(dictionary.get(key, []))
        return ", ".join(parts)
