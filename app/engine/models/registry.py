from __future__ import annotations

import json
from pathlib import Path

from .profile import ModelProfile
from .scanner import ModelScanner, ScannedModel


class ModelRegistry:
    """Model Registry (v0.1 §10, §44.7 models/registry.py).

    ModelScanner로 스캔한 모델에 대해 ModelProfile을 매핑한다.
    """

    def __init__(self, root: Path, profile_file: Path):
        self.root = root
        self.profile_file = profile_file
        self.profiles: dict[str, ModelProfile] = self._load_profiles()
        self.scanner = ModelScanner(root)

    def _load_profiles(self) -> dict[str, ModelProfile]:
        if self.profile_file.exists():
            try:
                raw = json.loads(self.profile_file.read_text(encoding="utf-8"))
                return {k: ModelProfile(k, **v) for k, v in raw.items()}
            except Exception:
                pass
        return {}

    def scan_llm(self) -> list[ScannedModel]:
        """LLM 모델 스캔 (scanner 위임)."""
        return self.scanner.scan_llm()

    def scan_image(self) -> list[ScannedModel]:
        """이미지 모델 스캔 (scanner 위임)."""
        return self.scanner.scan_image()

    def profile_for(self, path: Path) -> ModelProfile:
        """모델 경로로부터 아키텍처 프로필 매핑."""
        name = path.name.lower()
        for key, profile in self.profiles.items():
            if key.lower() in name or profile.architecture.lower() in name:
                return profile
        if "flux" in name:
            return ModelProfile(path.name, "image", "flux", "sentence", False, "auto")
        if "sdxl" in name or "xl" in name:
            return ModelProfile(path.name, "image", "sdxl", "sentence", True, "auto")
        if any(x in name for x in ("sd1", "1.5", "sd15", "sd2")):
            return ModelProfile(path.name, "image", "sd15", "tag", True, "auto")
        return ModelProfile(path.name, "image", "unknown", "sentence", True, "auto")
