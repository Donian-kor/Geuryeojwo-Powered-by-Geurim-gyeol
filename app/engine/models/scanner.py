"""모델 스캐너 (v0.1 §9).

models/ 아래의 각 폴더를 모델 1개로 취급한다. 폴더 이름은 자유이고,
그 안의 파일은 inspector가 내용으로 판별한다.
"""
from __future__ import annotations

from pathlib import Path

from .bundler import ModelBundle, build_bundle

# 숨김 폴더(.git 등)는 무시
_IGNORED = {".git", "__pycache__", ".vscode", ".kilo"}


class ModelScanner:
    """models/ 폴더 구조를 스캔한다 (v0.1 §9).

    구조:
        models/
        ├── Qwen2.5-7B/          → LLM 번들
        │   └── model.gguf
        └── RealVisXL_V5.0/      → 이미지 번들
            └── model.safetensors
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def _folders(self) -> list[Path]:
        if not self.root.exists():
            return []
        return [
            p for p in sorted(self.root.iterdir())
            if p.is_dir() and p.name not in _IGNORED and not p.name.startswith(".")
        ]

    def scan_all(self) -> list[ModelBundle]:
        """모든 폴더를 스캔해 유효한 번들만 반환한다."""
        bundles = []
        for folder in self._folders():
            bundle = build_bundle(folder)
            if bundle is not None:
                bundles.append(bundle)
        return bundles

    def scan_image(self) -> list[ModelBundle]:
        """이미지 모델 번들만 반환한다."""
        return [b for b in self.scan_all() if b.kind == "image"]

    def scan_llm(self) -> list[ModelBundle]:
        """LLM 번들만 반환한다."""
        return [b for b in self.scan_all() if b.kind == "llm"]

    def find_bundle(self, path: Path) -> ModelBundle | None:
        """경로가 속한 번들을 찾는다 (파일 경로 또는 폴더 경로)."""
        path = Path(path)
        folder = path if path.is_dir() else path.parent
        for bundle in self.scan_all():
            if bundle.folder == folder:
                return bundle
        return None
