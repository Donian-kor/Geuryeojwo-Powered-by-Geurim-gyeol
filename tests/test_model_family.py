"""모델 계열 판별 테스트.

한 워크플로는 한 계열의 모델에만 동작한다. (Qwen 워크플로에 SDXL 을 넣으면
ComfyUI 가 실행 단계에서 실패한다) 그래서 다른 계열을 골라 막는다.

판별이 '파일명'이 아니라 '텐서 이름 구조' 로 된다는 것이 핵심이다.
사람이 지어 naming 은 근거가 못 된다. (juggernautXL_ragnarok)
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from app.comfy.model_family import (
    FAMILY_UNKNOWN, clear_cache, detect_file_family, detect_prompt_family,
    family_label, is_compatible, prompt_model_files,
)

# 실제 파일에서 확인한 신호만 쓴다. 없는 신호를 넣으면 통과가 아니라
# 통과가 아니라 '실제에서 실패한다'
QWEN_KEYS = ["transformer_blocks.0.attn.to_q.weight",
             "txt_in.weight", "img_in.weight", "norm_out.weight"]
SDXL_KEYS = ["conditioner.embedders.0.linear_1.weight",
             "conditioner.embedders.1.linear_1.weight",
             "model.diffusion_model.input_blocks.0.0.weight",
             "first_stage_model.encoder.conv_in.weight"]
SD_KEYS = ["conditioner.transformer.text_model.encoder.layers.0.weight",
           "model.diffusion_model.input_blocks.0.0.weight",
           "first_stage_model.encoder.conv_in.weight"]
ZIMAGE_KEYS = ["model.diffusion_model.cap_embedder.weight",
               "model.diffusion_model.noise_refiner.blocks.0.weight",
               "model.diffusion_model.x_embedder.weight",
               "text_encoders.qwen3_4b.layers.0.weight"]
ERNIE_KEYS = ["model.diffusion_model.adaLN_modulation.weight",
              "model.diffusion_model.final_linear.weight",
              "text_encoders.ministral3_3b.layers.0.weight"]


def _safetensors(path: Path, keys) -> Path:
    """헤더만 있는 safetensors 를 만든다. 판별은 헤더만 읽는다."""
    header = {k: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]}
              for k in keys}
    header["__metadata__"] = {}
    blob = json.dumps(header).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(blob)) + blob)
    return path


def _models_dir(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    (root / "checkpoints").mkdir(parents=True)
    (root / "diffusion_models").mkdir(parents=True)
    return root


def test_families_are_told_apart_by_tensor_structure(tmp_path):
    root = _models_dir(tmp_path)
    cases = {
        "qwen.safetensors": (QWEN_KEYS, "qwen-image"),
        "xl.safetensors": (SDXL_KEYS, "sdxl"),
        "base.safetensors": (SD_KEYS, "sd"),
        "zimage.safetensors": (ZIMAGE_KEYS, "zimage"),
        "ernie.safetensors": (ERNIE_KEYS, "ernie"),
    }
    for name, (keys, expected) in cases.items():
        path = _safetensors(root / "checkpoints" / name, keys)
        assert detect_file_family(path) == expected, name


def test_sdxl_is_not_mistaken_for_sd(tmp_path):
    """SDXL 과 SD 1.5 는 conditioner 구조가 다르다."""
    root = _models_dir(tmp_path)
    assert detect_file_family(_safetensors(
        root / "checkpoints" / "a.safetensors", SDXL_KEYS)) == "sdxl"
    assert detect_file_family(_safetensors(
        root / "checkpoints" / "b.safetensors", SD_KEYS)) == "sd"


def test_unknown_structure_is_not_guessed(tmp_path):
    """모르는 구조면 빈 값을 준다. 틀린 계열로 단정하지 않는다."""
    root = _models_dir(tmp_path)
    path = _safetensors(root / "checkpoints" / "weird.safetensors",
                        ["something.entirely_different.weight"])
    assert detect_file_family(path) == FAMILY_UNKNOWN
    assert family_label(FAMILY_UNKNOWN) == ""


def test_non_safetensors_and_missing_files_are_unknown(tmp_path):
    root = _models_dir(tmp_path)
    assert detect_file_family(root / "checkpoints" / "upscaler.pth") == FAMILY_UNKNOWN
    assert detect_file_family(root / "checkpoints" / "없음.safetensors") == FAMILY_UNKNOWN


def test_workflow_family_comes_from_the_model_it_ships_with(tmp_path):
    """워크플로 계열은 CLIP 타입이 아니라 '워크플로가 물고 있는 모델' 에서.

    추측하지 않고 실제 파일을 본다. (clip_type 하나로是不够했다)
    """
    root = _models_dir(tmp_path)
    _safetensors(root / "diffusion_models" / "qwen.safetensors", QWEN_KEYS)
    prompt = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": "qwen.safetensors"}},
    }
    assert detect_prompt_family(prompt, root) == "qwen-image"


def test_workflow_with_uninstalled_model_stays_unknown(tmp_path):
    """워크플로가 가리키는 모델이 이 컴퓨터에 없으면 모르는 상태로 둔다.

    모른다고 아무것도 막지 않는 것이, 추측해서 쓸 수 있는 모델까지 막는
    것보다 낫다.
    """
    root = _models_dir(tmp_path)
    prompt = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": "없는모델.safetensors"}},
    }
    assert detect_prompt_family(prompt, root) == FAMILY_UNKNOWN


def test_linked_model_input_is_skipped(tmp_path):
    prompt = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": ["2", 0]}},
    }
    assert prompt_model_files(prompt) == []


def test_incompatibility_only_blocks_when_both_are_known():
    assert is_compatible("qwen-image", "qwen-image")
    assert not is_compatible("qwen-image", "sdxl")
    # 한쪽이라도 모르면 막지 않는다
    assert is_compatible("qwen-image", FAMILY_UNKNOWN)
    assert is_compatible(FAMILY_UNKNOWN, "sdxl")
    assert is_compatible(FAMILY_UNKNOWN, FAMILY_UNKNOWN)


def test_cache_is_refreshed_when_the_model_is_replaced(tmp_path):
    """판별 결과를 캐시하지만 파일이 바뀌면 다시 판별한다."""
    root = _models_dir(tmp_path)
    path = root / "checkpoints" / "m.safetensors"
    _safetensors(path, SDXL_KEYS)
    assert detect_file_family(path) == "sdxl"

    path.unlink()
    _safetensors(path, QWEN_KEYS)
    assert detect_file_family(path) == "qwen-image", "교체한 파일을 반영해야 한다"

    clear_cache()
    assert detect_file_family(path) == "qwen-image"