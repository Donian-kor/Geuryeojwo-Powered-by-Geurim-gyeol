from __future__ import annotations
import re
from pathlib import Path
import json

class PromptEngine:
    def __init__(self, profile_file: Path, dictionary_file: Path, logger):
        self.logger = logger
        self.profiles = json.loads(profile_file.read_text(encoding="utf-8")) if profile_file.exists() else {}
        self.dictionary = json.loads(dictionary_file.read_text(encoding="utf-8")) if dictionary_file.exists() else {}

    def policy(self, architecture: str) -> dict:
        return self.profiles.get(architecture, self.profiles.get("default", {"prompt_style":"sentence","use_negative":True}))

    def system_prompt(self, architecture: str) -> str:
        p = self.policy(architecture)
        if p.get("prompt_style") == "tag":
            return "Convert the user's idea into concise English image tags separated by commas. Do not write a prose sentence. Preserve concrete subject, clothing, environment, lighting, composition and style. Output only the final prompt."
        return "Expand the user's idea into one detailed, coherent English visual description. Do not add explanations or headings. Describe subject, composition, environment, lighting, camera/view, materials and artistic style when useful. Output only the final image prompt."

    def fallback(self, user: str, architecture: str) -> str:
        cleaned = re.sub(r"\s+", " ", user).strip()
        if not cleaned:
            return ""
        if architecture in {"sd15", "sd21"}:
            return f"{cleaned}, detailed illustration, cinematic lighting, high detail"
        return f"A detailed visual scene of {cleaned}, natural composition, refined lighting, high detail"

    def negative(self, architecture: str, enabled: bool = True) -> str:
        if not enabled or not self.policy(architecture).get("use_negative", True):
            return ""
        parts = []
        for key in ("quality_tags", "anatomy_tags"):
            parts.extend(self.dictionary.get(key, []))
        return ", ".join(parts)

    def build(self, user_prompt: str, architecture: str, llm=None) -> tuple[str, str]:
        if llm:
            try:
                positive = llm.generate(self.system_prompt(architecture), user_prompt)
            except Exception as exc:
                self.logger.warning("LLM prompt enhancement failed: %s", exc)
                positive = self.fallback(user_prompt, architecture)
        else:
            positive = self.fallback(user_prompt, architecture)
        return positive.strip(), self.negative(architecture)
