"""GUI 없이 검증 가능한 워크플로 규칙 함수 테스트.

이 함수들은 app/gui/main_window.py 에서 옮겨 온 것이다.
"모델이 설치돼 있는가", "위젯 값을 파라미터 키로 바꾸라" 같은 판단을
화면이 아니라 워크플로 모듈이 맡는다 — 그래야 GUI 없이 검증된다.
"""
from __future__ import annotations

import pytest

from app.comfy.workflow import (
    WIDGET_KEY_TO_INPUT, ParameterSpec, collect_extra, input_of,
    infer_parameters, installed_models, missing_models, model_folder,
)

OPTIONS = {
    "diffusion_models": ["unetA.safetensors", "unetB.safetensors"],
    "text_encoders": ["clip.safetensors"],
    "vae": ["vae.safetensors"],
    "loras": ["lora.safetensors"],
}


def _params(**extra) -> dict:
    """테스트용 parameters 맵. 키 -> ParameterSpec."""
    base = {
        "unet": ParameterSpec("unet", "1", "unet_name", "확산 모델",
                              "model:diffusion_models"),
        "clip": ParameterSpec("clip", "2", "clip_name", "텍스트 인코더",
                              "model:text_encoders"),
        "sampler": ParameterSpec("sampler", "6", "sampler_name", None, "combo"),
        "lora_strength": ParameterSpec("lora_strength", "16", "strength_model",
                                        None, "float"),
    }
    base.update(extra)
    return base


# --- 매핑 ---------------------------------------------------------------

def test_input_of_maps_widget_key_to_comfy_input():
    assert input_of("unet") == "unet_name"
    assert input_of("checkpoint") == "ckpt_name"
    assert input_of("clip") == "clip_name"
    assert input_of("vae") == "vae_name"
    assert input_of("lora") == "lora_name"
    assert input_of("sampler") == "sampler_name"
    assert input_of("scheduler") == "scheduler"
    # 매핑에 없는 키는 그대로
    assert input_of("steps") == "steps"
    assert set(WIDGET_KEY_TO_INPUT) >= {"unet", "clip", "vae", "lora"}


def test_model_folder_reads_kind_prefix():
    assert model_folder(_params(), "unet") == "diffusion_models"
    assert model_folder(_params(), "clip") == "text_encoders"
    # 워크플로에 없는 키 / kind 에 접두사가 없으면 빈 문자열
    assert model_folder(_params(), "sampler") == ""
    assert model_folder(_params(), "nope") == ""


# --- 설치 판정 -----------------------------------------------------------

def test_installed_models_filters_by_folder():
    assert installed_models(OPTIONS, _params(), "unet") == [
        "unetA.safetensors", "unetB.safetensors",
    ]
    assert installed_models(OPTIONS, _params(), "clip") == ["clip.safetensors"]
    assert installed_models(OPTIONS, _params(), "sampler") == []


def test_missing_models_detects_uninstalled_selection():
    assert missing_models(
        OPTIONS, _params(), {"unet": "MISSING.safetensors"}
    ) == [("unet", "MISSING.safetensors")]

    assert missing_models(OPTIONS, _params(), {"unet": "unetA.safetensors"}) == []


def test_missing_models_ignores_placeholder_and_empty():
    """"(사용 안 함)" 같은 표시값과 빈 값은 판정 대상이 아니다."""
    assert missing_models(OPTIONS, _params(), {"unet": "(사용 안 함)"}) == []
    assert missing_models(OPTIONS, _params(), {"unet": ""}) == []


def test_missing_models_does_not_judge_when_list_unavailable():
    """ComfyUI 목록을 못 받았으면 '설치 안 됨'으로 보지 않는다."""
    assert missing_models({}, _params(), {"unet": "anything.safetensors"}) == []
    assert missing_models(None, _params(), {"unet": "anything.safetensors"}) == []


def test_missing_models_reports_every_bad_selection():
    got = missing_models(OPTIONS, _params(), {
        "unet": "MISSING.safetensors",
        "clip": "MISSING-CLIP.safetensors",
    })
    assert got == [
        ("unet", "MISSING.safetensors"),
        ("clip", "MISSING-CLIP.safetensors"),
    ]


# --- 값 조립 -------------------------------------------------------------

def test_collect_extra_maps_widget_keys_to_parameter_keys():
    """위젯 키가 워크플로의 파라미터 키로 바뀐다."""
    extra = collect_extra(_params(), {
        "unet": "unetA.safetensors",
        "sampler": "euler",
    })
    assert extra == {"unet": "unetA.safetensors", "sampler": "euler"}


def test_collect_extra_skips_values_the_workflow_has_no_slot_for():
    """워크플로가 받지 않는 입력은 보내지 않는다(기본값 유지)."""
    extra = collect_extra(_params(), {"clip": "clip.safetensors"})
    assert extra == {"clip": "clip.safetensors"}
    # sampler 는 파라미터가 있는 경우에만 실린다
    params = _params(sampler=ParameterSpec("sampler", "6", "sampler_name", None, "combo"))
    assert collect_extra(params, {"sampler": "euler"}) == {"sampler": "euler"}


def test_collect_extra_adds_lora_strength_when_key_present():
    extra = collect_extra(
        _params(), {"unet": "unetA.safetensors"},
        lora_key="lora_strength", lora_strength=0.654,
    )
    assert extra["lora_strength"] == 0.65


def test_collect_extra_omits_lora_strength_without_key():
    """워크플로에 strength_model 이 없으면 강도를 보내지 않는다."""
    extra = collect_extra(_params(), {}, lora_key=None, lora_strength=0.65)
    assert "lora_strength" not in extra


# --- CLIP 로더의 type ----------------------------------------------------

def _clip_loader_prompt(cls="CLIPLoader", count=1) -> dict:
    """CLIP 로더가 있는 워크플로. type 값이 박혀 있다."""
    inputs = {"type": "lumina2"}
    for i in range(1, count + 1):
        inputs[f"clip_name{i if count > 1 else ''}"] = f"clip{i}.safetensors"
    return {cls: {"class_type": cls, "inputs": inputs}}


def test_clip_type_is_inferred_from_the_loader_node():
    """CLIP 로더 옆의 type 입력을 조작 대상에 넣는다.

    회귀 근거: 이게 없으면 '어떤 CLIP 인지' 를 바꿀 수 없었다.
    (Flux 는 flux, Z-Image 는 lumina2, Qwen 은 qwen_image)
    """
    spec = infer_parameters(_clip_loader_prompt())["clip_type"]
    assert spec.input == "type"
    assert spec.kind == "choice", "파일 목록이 아니라 선택지형이다"
    assert spec.default == "lumina2", "워크플로에 박힌 값을 기본으로 둔다"
    assert spec.node_class == "CLIPLoader", "선택지 조회에 노드 종류가 필요하다"


def test_clip_type_uses_the_multi_clip_loader_node():
    prompt = {
        "10": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "a.safetensors", "clip_name2": "b.safetensors",
            "type": "flux",
        }},
        # 값만 있고 실제로 쓰이지 않는 로더는 뒤로 밀려나야 한다
        "11": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "c.safetensors", "type": "stable_diffusion",
        }},
    }
    specs = infer_parameters(prompt)
    assert specs["clip_type"].node == "10", "실제로 쓰이는 쪽이어야 한다"
    assert specs["clip_type"].node_class == "DualCLIPLoader"
    assert specs["clip_type"].default == "flux"


def test_clip_type_is_absent_without_a_clip_loader():
    """CLIP 로더가 없으면 칸도 없다. (예: CheckpointLoader 만 쓰는 SD)"""
    prompt = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "sd.safetensors", "type": "안쓰임"}},
    }
    assert "clip_type" not in infer_parameters(prompt)


def test_clip_type_is_absent_when_type_is_linked():
    """type 이 다른 노드와 연결돼 있으면 값을 고를 수 없다."""
    prompt = {
        "1": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "a.safetensors", "type": ["9", 0]}},
    }
    assert "clip_type" not in infer_parameters(prompt)


def test_input_of_maps_numbered_clip_slots():
    """회귀: CLIP 2~4개 워크플로의 선택이 조용히 버려졌다.

    위젯 키는 clip1~clip4 이고 ComfyUI 입력 이름은 clip_name1~clip_name4 다.
    대응표에 없어 그대로 돌려주면 워크플로에서 아무것도 찾지 못했다.
    """
    assert input_of("clip1") == "clip_name1"
    assert input_of("clip2") == "clip_name2"
    assert input_of("clip4") == "clip_name4"
    assert input_of("clip_type") == "type"
    # clip5 처럼 대응표에 없는 번호도 규칙대로 붙는다
    assert input_of("clip5") == "clip_name5"


def test_multi_clip_and_type_selections_reach_the_request():
    """고른 CLIP 파일과 타입이 실제 파라미터 키로 전달된다."""
    prompt = {
        "10": {"class_type": "DualCLIPLoader", "inputs": {
            "clip_name1": "a.safetensors", "clip_name2": "b.safetensors",
            "type": "flux",
        }},
    }
    specs = infer_parameters(prompt)
    extra = collect_extra(specs, {
        "clip1": "new1.safetensors",
        "clip2": "new2.safetensors",
        "clip_type": "sdxl",
    })
    assert extra == {
        "clip1": "new1.safetensors",
        "clip2": "new2.safetensors",
        "clip_type": "sdxl",
    }
