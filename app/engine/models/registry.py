from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json

@dataclass(frozen=True)
class ModelProfile:
    name: str
    kind: str
    architecture: str
    prompt_style: str = "sentence"
    use_negative: bool = True
    loader: str = "auto"

class ModelRegistry:
    def __init__(self, root: Path, profile_file: Path):
        self.root = root
        self.profile_file = profile_file
        self.profiles = self._load_profiles()

    def _load_profiles(self):
        if self.profile_file.exists():
            try:
                raw = json.loads(self.profile_file.read_text(encoding="utf-8"))
                return {k: ModelProfile(k, **v) for k, v in raw.items()}
            except Exception:
                pass
        return {}

    def scan_llm(self) -> list[Path]:
        return sorted(self.root.joinpath("llm").glob("*.gguf"))

    def scan_image(self) -> list[Path]:
        paths = []
        for ext in ("*.safetensors", "*.ckpt", "*.bin"):
            paths.extend(self.root.joinpath("checkpoints").glob(ext))
        paths.extend(p for p in self.root.joinpath("checkpoints").iterdir() if p.is_dir())
        return sorted(set(paths), key=lambda p: p.name.lower())

    def profile_for(self, path: Path) -> ModelProfile:
        name = path.name.lower()
        for key, profile in self.profiles.items():
            if key.lower() in name or profile.architecture.lower() in name:
                return profile
        if any(x in name for x in ("flux",)):
            return ModelProfile(path.name, "image", "flux", "sentence", False, "auto")
        if any(x in name for x in ("sdxl", "xl")):
            return ModelProfile(path.name, "image", "sdxl", "sentence", True, "auto")
        if any(x in name for x in ("sd1", "1.5", "sd15", "sd2")):
            return ModelProfile(path.name, "image", "sd15", "tag", True, "auto")
        return ModelProfile(path.name, "image", "unknown", "sentence", True, "auto")
