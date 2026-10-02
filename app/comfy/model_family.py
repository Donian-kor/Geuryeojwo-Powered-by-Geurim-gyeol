"""모델 계열 판별.

한 워크플로는 한 계열의 모델에만 동작한다. (Qwen 워크플로에 SDXL 체크포인트를
넣으면 ComfyUI 가 실행 단계에서 실패한다) 그래서 후보 목록에서 다른 계열을
골라 막는다.

판별은 파일명이 아니라 safetensors 헤더의 '텐서 이름 구조' 로 한다.
파일명은 사람이 지어 naming 이라 (juggernautXL_ragnarok) 근거가 약하고,
이름을 모르겠으면 아무것도 할 수 없다. 헤더만 읽으므로 모델을
불러오지 않아 아주 빠르다.

모르는 구조는 빈 문자열을 돌려준다. 추측해서 틀린 계열을 단정하지 않기
위해서다. 빈 값이면 화면은 아무것도 막지 않는다. (감춰서 못 쓰는 것보다
보여주는 편이 낫다)
"""
from __future__ import annotations

import json
import struct
import time
from pathlib import Path

# 계열 키 -> 사람이 읽을 이름
FAMILY_LABELS = {
    "qwen-image": "Qwen-Image",
    "zimage": "Z-Image",
    "flux": "Flux",
    "ernie": "ERNIE",
    "sdxl": "SDXL",
    "sd": "SD 1.5",
}
# 모르는 구조. 아무것도 막지 않는다.
FAMILY_UNKNOWN = ""

# (파일경로, 수정시각, 크기) -> 계열. 헤더를 매번 읽지 않도록.
_CACHE: dict[tuple[str, float, int], str] = {}

# 판별 가능한 입력 확장자
_SAFE_SUFFIXES = (".safetensors",)


def _safetensors_keys(path: Path) -> list[str] | None:
    """safetensors 헤더에서 텐서 이름만 읽는다. 모델을 로드하지 않는다.

    Returns:
        텐서 이름 목록. safetensors 가 아니면 None.
    """
    try:
        with path.open("rb") as handle:
            size = struct.unpack("<Q", handle.read(8))[0]
            header = json.loads(handle.read(size).decode("utf-8"))
    except Exception:
        return None
    return [k for k in header if k != "__metadata__"]


def _classify(keys: list[str]) -> str:
    """텐서 이름 구조로 계열을 정한다.

    순서가 중요하다. 더 구체적인 신호를 먼저 본다.
    (SDXL 은 conditioner.embedders 가 두 개다 — SD 1.5 와 구분된다)
    """
    prefixes = set()
    for key in keys:
        prefixes.add(key)
        # 앞 3단계까지만 보아도 충분하다
        parts = key.split(".")
        for i in range(2, 4):
            prefixes.add(".".join(parts[:i]))

    def has(prefix: str) -> bool:
        return any(k.startswith(prefix) for k in prefixes)

    # Qwen-Image — transformer 블록 + txt_in / img_in
    if has("transformer_blocks") and has("txt_in") and has("img_in"):
        return "qwen-image"
    # Z-Image (Lumina2) — cap_embedder / noise_refiner 가 특징
    if has("model.diffusion_model.cap_embedder") or \
            has("model.diffusion_model.noise_refiner"):
        return "zimage"
    # ERNIE — 내장 민스트럴 텍스트 인코더
    if has("text_encoders.ministral") or has("text_encoders.tekken_model"):
        return "ernie"
    # SDXL — 텍스트 인코더가 두 개다
    if has("conditioner.embedders.0") and has("conditioner.embedders.1"):
        return "sdxl"
    # SD 1.5 — conditioner.transformer.text_model
    if has("conditioner.transformer.text_model"):
        return "sd"
    return FAMILY_UNKNOWN


def detect_file_family(path: Path | str) -> str:
    """모델 파일의 계열. 모르면 빈 문자열.

    Args:
        path: .safetensors 파일 경로

    Returns:
        FAMILY_* 키 또는 FAMILY_UNKNOWN
    """
    path = Path(path)
    if path.suffix.lower() not in _SAFE_SUFFIXES or not path.exists():
        return FAMILY_UNKNOWN
    try:
        stat = path.stat()
    except OSError:
        return FAMILY_UNKNOWN
    key = (str(path), stat.st_mtime, stat.st_size)
    if key in _CACHE:
        return _CACHE[key]
    keys = _safetensors_keys(path)
    family = _classify(keys) if keys else FAMILY_UNKNOWN
    _CACHE[key] = family
    return family


def clear_cache() -> None:
    """모델을 새로 설치했을 때 판별 결과를 버린다."""
    _CACHE.clear()


def family_label(family: str) -> str:
    """계열 키를 사람이 읽을 이름으로."""
    return FAMILY_LABELS.get(family, "")


def is_compatible(workflow_family: str, model_family: str) -> bool:
    """이 모델을 이 워크플로에서 쓸 수 있는가.

    둘 중 하나를 모르면 막지 않는다. 추측해서 막으면 사용자가 이유를
    알 수 없게 된다.
    """
    if not workflow_family or not model_family:
        return True
    return workflow_family == model_family


def workflow_family(workflow, models_dir: Path | str = "") -> str:
    """로드된 워크플로의 계열.

    파일에 "family" 가 적혀 있으면 그것을, 없으면 물고 있는 모델을 본다.
    우리가 배포한 기본 워크플로는 모델 이름을 비워 두기 때문에 늘
    첫 번째 경로로 판별된다.
    """
    if workflow is None:
        return FAMILY_UNKNOWN
    declared = (workflow.meta or {}).get("family", "")
    return detect_prompt_family(
        workflow.prompt, models_dir, declared=declared
    )


def compatible_models(names, family: str, models_dir: Path | str,
                      folder: str) -> list[str]:
    """설치된 모델 중 이 계열에 맞는 파일만 (파일명 목록).

    판별불가 파일은 남긴다. 추측해서 빼면 쓸 수 있는 모델까지 잃는다.
    """
    if not family or not models_dir:
        return list(names)
    root = Path(models_dir) / folder
    return [
        name for name in names
        if is_compatible(family, detect_file_family(root / name))
    ]


def prompt_model_files(prompt: dict) -> list[str]:
    """워크플로가 실제로 쓰는 모델 파일명 (확산 모델·체크포인트).

    Returns:
        파일명 목록. 값이 링크인 것은 제외한다.
    """
    result = []
    for node in (prompt or {}).values():
        inputs = (node or {}).get("inputs") or {}
        for name in ("unet_name", "ckpt_name", "model_name"):
            value = inputs.get(name)
            if isinstance(value, str) and value.strip():
                result.append(value)
    return result


def detect_prompt_family(prompt: dict, models_dir: Path | str,
                         declared: str = "") -> str:
    """워크플로의 계열. 모르면 빈 문자열.

    Args:
        prompt: API 형식 워크플로 노드
        models_dir: ComfyUI models 폴더
        declared: 워크플로 파일이 밝힌 계열 (meta 의 "family").
            우리가 배포한 기본 워크플로는 모델 이름을 비워 두므로 이 값을 쓴다.

    Returns:
        계열 키. 모르면 FAMILY_UNKNOWN.
    """
    # 파일이 밝힌 계열이 가장 확실하다. 모델 파일이 없어도 안다.
    if declared in FAMILY_LABELS:
        return declared
    if not models_dir:
        return FAMILY_UNKNOWN
    root = Path(models_dir)
    for name in prompt_model_files(prompt):
        for folder in ("diffusion_models", "checkpoints"):
            family = detect_file_family(root / folder / name)
            if family:
                return family
    return FAMILY_UNKNOWN