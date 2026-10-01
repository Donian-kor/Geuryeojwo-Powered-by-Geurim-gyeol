from __future__ import annotations

import json
from pathlib import Path

from .profile import ModelProfile
from .scanner import ModelScanner, ScannedModel


class ModelRegistry:
    """Model Registry (v0.1 §10, §11, §44.7 models/registry.py).

    ModelScanner로 스캔한 모델에 대해 ModelProfile을 매핑한다.

    판별 우선순위 (v0.1 §11):
        1. User Override        (config/user_models.json)
        2. Explicit Configuration (config/image_profiles.json)
        3~4. Registry / Metadata
        5. Filename Heuristic
        6. Default Profile
    """

    def __init__(self, root: Path, profile_file: Path, override_file: Path | None = None):
        self.root = root
        self.profile_file = profile_file
        self.override_file = override_file or profile_file.parent / "user_models.json"
        self.profiles: dict[str, ModelProfile] = self._load_profiles()
        self.overrides: dict[str, ModelProfile] = self._load_overrides()
        self.scanner = ModelScanner(root)

    def _load_profiles(self) -> dict[str, ModelProfile]:
        if self.profile_file.exists():
            try:
                raw = json.loads(self.profile_file.read_text(encoding="utf-8"))
                return {k: ModelProfile(k, **v) for k, v in raw.items()}
            except Exception:
                pass
        return {}

    def _load_overrides(self) -> dict[str, ModelProfile]:
        """사용자 Override 로드 (v0.1 §3.5, §11 1순위)."""
        if not self.override_file.exists():
            return {}
        try:
            raw = json.loads(self.override_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
        overrides = {}
        for name, config in raw.items():
            if name.startswith("_") or not isinstance(config, dict):
                continue
            config.setdefault("source", "override")
            overrides[name] = ModelProfile(name=name, **config)
        return overrides

    def save_override(self, filename: str, **config) -> ModelProfile:
        """사용자 Override를 저장한다 (v0.1 §3.5)."""
        if self.override_file.exists():
            raw = json.loads(self.override_file.read_text(encoding="utf-8"))
        else:
            raw = {}
        raw[filename] = config
        self.override_file.parent.mkdir(parents=True, exist_ok=True)
        self.override_file.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.overrides = self._load_overrides()
        return self.overrides[filename]

    def scan_llm(self) -> list[ScannedModel]:
        """LLM 모델 스캔 (scanner 위임)."""
        return self.scanner.scan_llm()

    def scan_image(self) -> list[ScannedModel]:
        """이미지 모델 스캔 (scanner 위임)."""
        return self.scanner.scan_image()

    def profile_for(self, path: Path) -> ModelProfile:
        """모델 경로로부터 아키텍처 프로필을 결정한다 (v0.1 §11)."""
        name = path.name.lower()

        # 1. User Override (최우선)
        for key, profile in self.overrides.items():
            if key.lower() == name:
                return profile

        # 2. Explicit Configuration (image_profiles.json)
        for key, profile in self.profiles.items():
            if key.lower() in name or profile.architecture.lower() in name:
                return profile

        # 5. Filename Heuristic
        return self._heuristic_profile(path)

    def _heuristic_profile(self, path: Path) -> ModelProfile:
        """파일명 휴리스틱 아키텍처 판별 (v0.1 §11 5순위)."""
        name = path.name.lower()
        for keyword, (arch, style, negative) in self.HEURISTICS.items():
            if keyword in name:
                return ModelProfile(
                    path.name, "image", arch, style, negative, "auto", source="heuristic"
                )
        return ModelProfile(
            path.name, "image", "unknown", "sentence", True, "auto", source="default"
        )

    HEURISTICS = {
        "flux": ("flux", "sentence", False),
        "sd3": ("sd3", "sentence", False),
        "stable-diffusion-3": ("sd3", "sentence", False),
        "sdxl": ("sdxl", "sentence", True),
        "xl_base": ("sdxl", "sentence", True),
        "sd21": ("sd21", "tag", True),
        "sd_21": ("sd21", "tag", True),
        "sd15": ("sd15", "tag", True),
        "sd_15": ("sd15", "tag", True),
        "v1-5": ("sd15", "tag", True),
    }
