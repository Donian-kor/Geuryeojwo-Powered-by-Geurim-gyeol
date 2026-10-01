"""모델 번들 조립 (v0.1 §9, §44.7).

models/ 아래 폴더 하나 = 모델 하나. 폴더 안의 파일은 이름이 아니라
내용(safetensors 헤더)으로 분류해 컴포넌트를 찾아낸다.

사용자는 폴더를 만들고 파일을 넣기만 하면 된다:

    models/
    ├── Qwen2.5-7B/
    │   └── qwen2.5-7b-q4_k_m.gguf
    │
    ├── RealVisXL_V5.0/
    │   ├── realvisxlv5.safetensors     ← 번들 ckpt
    │   └── my_style.safetensors        ← LoRA (선택)
    │
    └── flux1-dev/                       ← Diffusers 원본
        └── model_index.json

폴더 안의 서브폴더(vae/, lora/, clip/)는 정돈용 선택 사항이며,
없어도 100% 동작한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .inspector import ComponentKind, FileInspection, inspect_file

# 번들이 되려면 확산 모델(U-Net/Transformer)이 반드시 있어야 한다
_REQUIRED_KIND = ComponentKind.UNET


@dataclass
class ModelBundle:
    """폴더 하나에서 조립한 모델 (v0.1 §9)."""

    folder: Path
    name: str
    kind: str  # "image" | "llm"
    architecture: str = "unknown"

    # 이미지 모델 구성요소
    main: Path | None = None
    vae: Path | None = None
    text_encoders: list[Path] = field(default_factory=list)
    loras: list[Path] = field(default_factory=list)
    is_diffusers_dir: bool = False

    # 진단 정보
    size_gb: float = 0.0
    files: list[FileInspection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """실제로 실행 가능한 번들인지 여부."""
        if self.kind == "llm":
            return self.main is not None
        return self.is_diffusers_dir or self.main is not None

    @property
    def load_target(self) -> Path | None:
        """어댑터에 넘길 경로 (Diffusers 폴더면 폴더 자체)."""
        if self.is_diffusers_dir:
            return self.folder
        return self.main

    def describe(self) -> str:
        """드롭다운 표기용 한 줄."""
        if self.kind == "llm":
            return f"{self.name} (LLM)"
        extras = []
        if self.vae:
            extras.append("VAE")
        if self.text_encoders:
            extras.append(f"TextEncoder x{len(self.text_encoders)}")
        if self.loras:
            extras.append(f"LoRA x{len(self.loras)}")
        suffix = f" + {' + '.join(extras)}" if extras else ""
        return f"{self.name} ({self.architecture}){suffix}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "architecture": self.architecture,
            "size_gb": self.size_gb,
            "is_diffusers_dir": self.is_diffusers_dir,
            "has_vae": self.vae is not None,
            "text_encoder_count": len(self.text_encoders),
            "lora_count": len(self.loras),
            "warnings": self.warnings,
        }


def _folder_size_gb(folder: Path) -> float:
    """폴더 전체 크기 (GB)."""
    total = 0
    for path in folder.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return round(total / (1024**3), 2)


def _collect_files(folder: Path) -> list[Path]:
    """폴더에서 모델 파일과 Diffusers 마커를 모은다.

    파일명 순서가 아니라 접두어 우선순위로 정렬한다.
    UNet 같은 핵심 컴포넌트가 LoRA에 밀리지 않도록 한다.
    """
    model_suffixes = (".safetensors", ".ckpt", ".gguf", ".bin", ".pt")
    markers = ("model_index.json",)

    candidates = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() in model_suffixes or path.name in markers:
            candidates.append(path)

    def priority(path: Path) -> tuple:
        name = path.name.lower()
        if name in markers:
            return (0, name)  # Diffusers 마커가 최우선
        # unet/diffusion_model 같은 확산 모델을 그 다음으로
        if "unet" in name or "diffusion" in name or "transformer" in name:
            return (1, name)
        if "lora" in name:
            return (9, name)  # LoRA는 마지막
        return (5, name)

    return sorted(candidates, key=priority)


def build_bundle(folder: Path) -> ModelBundle | None:
    """폴더 하나를 분석해 ModelBundle로 조립한다 (v0.1 §9).

    Returns:
        ModelBundle 또는 유효한 모델이 없으면 None
    """
    folder = Path(folder)
    if not folder.is_dir():
        return None

    files = _collect_files(folder)
    if not files:
        return None

    inspections = []
    for path in files:
        try:
            inspections.append(inspect_file(path))
        except Exception as exc:  # 개별 파일 실패는 무시하고 계속
            inspections.append(
                FileInspection(path, ComponentKind.UNKNOWN, error=str(exc))
            )

    # Diffusers 마커가 있으면 폴더 자체를 모델로 사용한다
    if (folder / "model_index.json").exists():
        from .inspector import arch_from_model_index

        return ModelBundle(
            folder=folder,
            name=folder.name,
            kind="image",
            architecture=arch_from_model_index(folder),
            main=folder,
            is_diffusers_dir=True,
            size_gb=_folder_size_gb(folder),
            files=inspections,
        )

    bundle = ModelBundle(
        folder=folder,
        name=folder.name,
        kind="image",
        size_gb=_folder_size_gb(folder),
        files=inspections,
    )

    clips: list[Path] = []
    for inspection in inspections:
        kind = inspection.kind
        if kind == ComponentKind.GGUF:
            # GGUF가 있으면 LLM 번들이다
            return ModelBundle(
                folder=folder,
                name=folder.name,
                kind="llm",
                architecture="llm",
                main=inspection.path,
                size_gb=bundle.size_gb,
                files=inspections,
            )
        if kind == _REQUIRED_KIND and bundle.main is None:
            bundle.main = inspection.path
            bundle.architecture = inspection.architecture
        elif kind == ComponentKind.VAE and bundle.vae is None:
            bundle.vae = inspection.path
        elif kind == ComponentKind.CLIP:
            clips.append(inspection.path)
        elif kind == ComponentKind.LORA:
            bundle.loras.append(inspection.path)

    # CLIP은 용량순으로 정렬 (SDXL은 CLIP-L → OpenCLIP 순서)
    clips.sort(key=lambda p: p.stat().st_size if p.exists() else 0)
    bundle.text_encoders = clips

    # 텍스트 인코더가 따로 있으면 번들이 아니라 분리 배포로 경고
    if bundle.main is not None and clips:
        bundle.warnings.append(
            f"분리 텍스트 인코더 {len(clips)}개를 찾았습니다. "
            f"현재는 단일 파일 번들만 지원하므로 무시됩니다."
        )

    if not bundle.is_valid:
        return None

    return bundle