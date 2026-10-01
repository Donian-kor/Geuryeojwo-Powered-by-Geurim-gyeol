from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScannedModel:
    """스캔된 모델 정보 (v0.1 §44.7 models/scanner.py)."""

    path: Path
    name: str
    kind: str  # "llm" | "image"
    size_gb: float


class ModelScanner:
    """Model 스캐너 (v0.1 §44.7 models/scanner.py).

    models/ 디렉토리에서 GGUF(LLM)와 이미지 모델(safetensors/ckpt/디렉토리)을 발견한다.
    """

    GGUF_EXTS = {".gguf"}
    IMAGE_EXTS = {".safetensors", ".ckpt", ".bin", ".pt"}

    def __init__(self, root: Path):
        self.root = root

    def scan_llm(self) -> list[ScannedModel]:
        """LLM 모델(.gguf) 스캔."""
        llm_dir = self.root / "llm"
        if not llm_dir.exists():
            return []
        models = []
        for p in sorted(llm_dir.glob("*.gguf")):
            models.append(ScannedModel(p, p.name, "llm", round(p.stat().st_size / 1024**3, 2)))
        return models

    def scan_image(self) -> list[ScannedModel]:
        """이미지 모델 스캔."""
        cp_dir = self.root / "checkpoints"
        if not cp_dir.exists():
            return []
        models = []
        for p in sorted(cp_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in self.IMAGE_EXTS:
                models.append(ScannedModel(p, p.name, "image", round(p.stat().st_size / 1024**3, 2)))
            elif p.is_dir():
                models.append(ScannedModel(p, p.name, "image", 0.0))
        return sorted(models, key=lambda m: m.name.lower())
