"""모델 파일 내용 기반 분석 (v0.1 §9, §11).

파일명이 아니라 safetensors 헤더에 기록된 텐서 이름/모양을 읽어
파일 유형과 아키텍처를 판별한다. ComfyUI의 model_detection 방식을
차용하되, 그려줘에 필요한 최소한만 구현한다.

핵심: 헤더에는 모든 텐서 이름과 모양이 기록되어 있으므로
6GB 파일도 데이터를 로드하지 않고 밀리초 단위로 판별할 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ComponentKind(Enum):
    """파일 유형 (v0.1 §9)."""

    UNET = "unet"
    VAE = "vae"
    CLIP = "clip"
    CLIP_VISION = "clip_vision"
    LORA = "lora"
    DIFFUSERS_DIR = "diffusers_dir"
    GGUF = "gguf"
    UNKNOWN = "unknown"


@dataclass
class FileInspection:
    """파일 분석 결과."""

    path: Path
    kind: ComponentKind
    architecture: str = "unknown"
    tensor_count: int = 0
    error: str | None = None
    shapes: dict[str, list[int]] = field(default_factory=dict)


# LoRA 시그니처 (ComfyUI lora.py와 동일한 표기)
LORA_MARKERS = ("lora_down", "lora_up", "lora_unet", "lora_te", "lora_ckpt")


def read_tensor_keys(path: Path) -> list[str]:
    """safetensors 헤더에서 텐서 이름만 읽는다 (데이터 미로드)."""
    from safetensors import safe_open

    with safe_open(str(path), framework="pt") as f:
        return list(f.keys())


def read_tensor_shapes(path: Path) -> dict[str, list[int]]:
    """safetensors 헤더에서 텐서 이름과 모양만 읽는다 (데이터 미로드)."""
    from safetensors import safe_open

    with safe_open(str(path), framework="pt") as f:
        return {k: list(f.get_slice(k).get_shape()) for k in f.keys()}


def classify_by_keys(keys: list[str], shapes: dict[str, list[int]]) -> tuple[ComponentKind, str]:
    """텐서 이름/모양으로 유형과 아키텍처를 판별한다 (v0.1 §11)."""
    joined = "\n".join(keys)

    # LoRA — 다른 판별보다 먼저 (일부 LoRA가 model. 프리픽스를 가진다)
    if any(marker in joined for marker in LORA_MARKERS):
        return ComponentKind.LORA, "lora"

    # CLIP Vision
    if any(k.startswith("visual.") for k in keys):
        return ComponentKind.CLIP_VISION, "clip_vision"

    # 확산 모델 (U-Net / Transformer)
    if any(k.startswith("model.diffusion_model.") or k.startswith("model.unet.")
           or k.startswith("unet.") for k in keys):
        return ComponentKind.UNET, _detect_unet_arch(keys, shapes)

    if any(k.startswith("x_embedder.") or k.startswith("transformer_blocks.")
           or k.startswith("double_blocks.") for k in keys):
        if any("context_embedder" in k for k in keys):
            return ComponentKind.UNET, "flux"
        return ComponentKind.UNET, "sd3"

    # VAE
    if any(k.startswith("first_stage_model.") for k in keys):
        return ComponentKind.VAE, "vae"
    if any(k.startswith("encoder.") for k in keys) and any(
            k.startswith("decoder.") for k in keys
    ):
        return ComponentKind.VAE, "vae"

    # 텍스트 인코더
    if any(k.startswith("cond_stage_model.") for k in keys):
        return ComponentKind.CLIP, "clip"
    if any(k.startswith("text_model.") or k.startswith("text_encoders.")
           or k.startswith("conditioner.embedders.") for k in keys):
        return ComponentKind.CLIP, "clip"

    return ComponentKind.UNKNOWN, "unknown"


def _detect_unet_arch(keys: list[str], shapes: dict[str, list[int]]) -> str:
    """U-Net 구조로 아키텍처를 판별한다.

    SD1.5와 SDXL은 키 이름만으로 구분되지 않는다.
      - SDXL: add_embedding.linear_*, time_text_embed, 또는 conv_in in_channels=9
      - SD1.5: conv_in in_channels=4
    """
    if any("context_embedder" in k for k in keys):
        return "flux"
    if any(k.startswith("x_embedder.") for k in keys):
        return "sd3"
    if any(k.startswith("add_embedding.linear_") for k in keys):
        return "sdxl"
    if any("time_text_embed" in k for k in keys):
        return "sdxl"

    conv_in = (
        shapes.get("model.diffusion_model.input_blocks.0.0.weight")
        or shapes.get("unet.conv_in.weight")
    )
    if conv_in and len(conv_in) == 4:
        if conv_in[1] == 9:
            return "sdxl"
        if conv_in[1] == 4:
            return "sd15"

    depth = sum(
        1 for k in keys
        if k.startswith("model.diffusion_model.down_blocks.")
        and ".resnets." in k
    )
    if depth > 30:
        return "sd21"
    if depth > 0:
        return "sd15"

    return "unknown"


def _arch_from_model_index(folder: Path) -> str:
    """Diffusers 폴더의 아키텍처를 model_index.json에서 읽는다."""
    import json

    try:
        data = json.loads((folder / "model_index.json").read_text(encoding="utf-8"))
        joined = " ".join(str(v) for v in data.values()).lower()
        for keyword, arch in (
            ("flux", "flux"),
            ("stable_diffusion_3", "sd3"),
            ("stable_diffusion_xl", "sdxl"),
            ("stable_diffusion", "sd15"),
        ):
            if keyword in joined:
                return arch
        return "unknown"
    except Exception:
        return "unknown"


def inspect_file(path: Path) -> FileInspection:
    """파일 하나를 분석한다 (v0.1 §9)."""
    path = Path(path)

    if path.is_dir():
        if (path / "model_index.json").exists():
            return FileInspection(path, ComponentKind.DIFFUSERS_DIR, _arch_from_model_index(path))
        return FileInspection(path, ComponentKind.UNKNOWN, "unknown")

    suffix = path.suffix.lower()

    if suffix == ".gguf":
        with open(path, "rb") as f:
            magic = f.read(4)
        if magic != b"GGUF":
            return FileInspection(path, ComponentKind.UNKNOWN, "llm", error="GGUF 헤더 손상")
        return FileInspection(path, ComponentKind.GGUF, "llm")

    if suffix == ".safetensors":
        try:
            shapes = read_tensor_shapes(path)
            keys = list(shapes.keys())
            kind, arch = classify_by_keys(keys, shapes)
            return FileInspection(path, kind, arch, len(keys), shapes=shapes)
        except Exception as exc:
            return FileInspection(path, ComponentKind.UNKNOWN, error=str(exc))

    if suffix == ".ckpt":
        # torch pickle은 meta 디바이스 지연 로드로 키만 읽는다
        try:
            import torch

            state = torch.load(str(path), map_location="meta", weights_only=True)
            keys = list(state.keys())
            shapes = {k: list(state[k].shape) for k in keys if hasattr(state[k], "shape")}
            kind, arch = classify_by_keys(keys, shapes)
            return FileInspection(path, kind, arch, len(keys), shapes=shapes)
        except Exception as exc:
            return FileInspection(path, ComponentKind.UNKNOWN, error=str(exc))

    return FileInspection(path, ComponentKind.UNKNOWN)