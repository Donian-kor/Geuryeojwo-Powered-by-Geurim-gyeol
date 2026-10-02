"""워크플로 등록 전 검사 모듈 테스트.

회귀 근거 (실측):
- Z-Anime / ERNIE 는 rgthree 등 미설치 노드가 있어서 API 로 내보내도
  class_type 이 빠진 노드와 UNKNOWN_* 입력이 남는다.
- Z-Anime 는 요구 모델(z-anime-distill-8step-aio)와 설치된 모델
  (z-anime-base-aio)이 이름만 비슷한 '다른 모델'이다.
- Z-Anime / ERNIE 는 SaveImage 가 2개라 어느 쪽을 받을지 고를해야 한다.
- ERNIE 의 LoadImage 는 결과와 연결이 끊겨 있다. 이걸로 막으면 안 된다.
"""
from __future__ import annotations

from app.comfy.check import (
    LEVEL_BLOCK, LEVEL_INFO, LEVEL_OK, LEVEL_WARN, check_fitness, check_format,
    check_models, check_nodes, check_workflow, nodes_without_class_type,
    output_nodes, required_models, similar_models,
)

INSTALLED = {
    "checkpoints": ["z-anime-base-aio-fp8.safetensors", "RealVisXL_V5.0_fp16.safetensors"],
    "diffusion_models": ["qwen-image-2.1-UC-NVFP4.safetensors"],
    "text_encoders": ["qwen3vl_8b_int8_convrot.safetensors"],
    "vae": ["qwen_image_2.1_vae_bf16.safetensors"],
    "loras": ["qwen-image-2.1-uncensored-lora.safetensors"],
}


def _minimal(overrides: dict | None = None) -> dict:
    """기본 워크플로에 overrides 를 합친다.

    노드 ID 에 숫자가 아닌 문자가 섞여 있어 ** 키워드로 넘기기 어렵다.
    """
    base = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "z-anime-base-aio-fp8.safetensors"}},
        "3": {"class_type": "KSampler",
              "inputs": {"seed": 1, "steps": 10, "cfg": 1.0}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
    }
    base.update(overrides or {})
    return base


# --- 1) 형식 ------------------------------------------------------------

def test_api_prompt_passes_format_check():
    assert check_format(_minimal()) is None


def test_ui_format_is_blocked_with_export_instructions():
    ui = {"nodes": [{"id": 1, "type": "KSampler"}], "links": []}
    item = check_format(ui)
    assert item is not None
    assert item.level == LEVEL_BLOCK
    assert any("Export Workflow (API)" in a for a in item.actions)


def test_empty_document_is_blocked():
    assert check_format({}).level == LEVEL_BLOCK


def test_wrapped_prompt_key_is_recognised():
    doc = {"name": "x", "prompt": _minimal()}
    assert check_format(doc) is None


# --- 2) 노드 ------------------------------------------------------------

def test_node_without_class_type_is_blocked():
    prompt = {
        "54": {"inputs": {"UNKNOWN": -1}, "_meta": {"title": "Seed Control"}},
        "6": {"class_type": "KSampler", "inputs": {"seed": ["54", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["6", 0]}},
    }
    item = check_nodes(prompt, None)
    assert item.level == LEVEL_BLOCK
    assert "Seed Control" in item.detail
    assert item.actions, "해결 방법을 함께 줘야 한다"


def test_nodes_without_class_type_lists_titles():
    prompt = {"a": {"inputs": {}, "_meta": {"title": "X"}},
              "b": {"inputs": {}, "_meta": {"title": "Y"}}}
    found = nodes_without_class_type(prompt)
    assert [t for _, t in found] == ["X", "Y"]


def test_unknown_inputs_alone_warn():
    prompt = {"1": {"class_type": "X", "inputs": {"UNKNOWN": 1},
                    "_meta": {"title": "T"}},
              "9": {"class_type": "SaveImage", "inputs": {}}}
    assert check_nodes(prompt, None).level == LEVEL_WARN


def test_unknown_node_type_is_blocked_when_known_types_given():
    prompt = {"1": {"class_type": "NopeNode", "inputs": {}},
              "9": {"class_type": "SaveImage", "inputs": {}}}
    item = check_nodes(prompt, {"SaveImage", "KSampler"})
    assert item.level == LEVEL_BLOCK
    assert "NopeNode" in item.detail


def test_known_node_types_pass():
    prompt = {"9": {"class_type": "SaveImage", "inputs": {}}}
    assert check_nodes(prompt, {"SaveImage"}) is None


def test_node_types_skipped_when_known_types_absent():
    """목록을 못 받았으면 '설치 안 됨' 으로 단정하지 않는다."""
    prompt = {"1": {"class_type": "NopeNode", "inputs": {}}}
    assert check_nodes(prompt, None) is None


# --- 3) 모델 ------------------------------------------------------------

def test_required_models_grouped_by_folder():
    prompt = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "u.safetensors"}},
              "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "c.safetensors"}}}
    assert required_models(prompt) == {"diffusion_models": ["u.safetensors"],
                                       "text_encoders": ["c.safetensors"]}


def test_all_models_installed_is_ok():
    assert check_models(_minimal(), INSTALLED).level == LEVEL_OK


def test_missing_model_gives_path_and_link():
    prompt = {"1": {"class_type": "UNETLoader",
                    "inputs": {"unet_name": "z_image_turbo_bf16.safetensors"}},
              "9": {"class_type": "SaveImage", "inputs": {}}}
    item = check_models(prompt, INSTALLED, models_dir="C:/models")
    assert item.level == LEVEL_WARN
    joined = " ".join(f"{a} {b}" for a, b in item.rows)
    assert "z_image_turbo_bf16.safetensors" in joined
    assert "C:/models/diffusion_models" in joined.replace("\\", "/")
    assert item.links and "huggingface.co" in item.links[0][1]


def test_similar_name_is_flagged_as_different_model():
    """이름만 비슷한 다른 모델을 조용히 대신 쓰면 안 된다."""
    prompt = _minimal({
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "z-anime-distill-8step-aio-fp8.safetensors"}},
        "9": {"class_type": "SaveImage", "inputs": {}},
    })
    item = check_models(prompt, INSTALLED)
    joined = " ".join(f"{a} {b}" for a, b in item.rows)
    assert "z-anime-base-aio-fp8.safetensors" in joined
    assert "다른 모델일 수 있음" in joined


def test_similar_models_ignores_other_extensions():
    assert similar_models("a.safetensors", ["a.gguf", "b.png"]) == []


def test_no_model_verdict_when_list_unavailable():
    """회귀: 확인도 안 하고 '모두 설치' 라고 말하면 안 된다.

    서버 목록을 못 받았을 때 '이상 없음' 으로 보고하면
    사용자는 그대로 믿고 실행하고 실패한다.
    """
    item = check_models(_minimal(), None)
    assert item.level == LEVEL_INFO
    assert item.level != LEVEL_OK


def test_no_model_requirement_returns_none():
    assert check_models({"9": {"class_type": "SaveImage", "inputs": {}}}, INSTALLED) is None


# --- 4) 적합성 ----------------------------------------------------------

def test_missing_output_node_is_blocked():
    prompt = {"3": {"class_type": "KSampler", "inputs": {}}}
    assert check_fitness(prompt).level == LEVEL_BLOCK


def test_single_output_passes():
    assert check_fitness(_minimal()) is None


def test_two_outputs_warn_and_are_reported():
    prompt = _minimal({"95": {"class_type": "SaveImage",
                              "inputs": {"images": ["3", 0]},
                              "_meta": {"title": "Upscaled"}}})
    assert check_fitness(prompt).level == LEVEL_WARN
    assert output_nodes(prompt) == ["9", "95"]


def test_reachable_load_image_is_blocked():
    """이미지를 입력으로 받는 워크플로는 쓸 수 없다."""
    prompt = {
        "7": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
        "8": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["7", 0], "vae": ["2", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}},
    }
    item = check_fitness(prompt)
    assert item.level == LEVEL_BLOCK
    assert "이미지" in item.title


def test_orphan_load_image_does_not_block():
    """회귀: ERNIE 의 LoadImage 는 안내용이라 연결이 끊겨 있다.

    연결이 안 된 노드를 이유로 막으면 정상 워크플로를 거절한다.
    """
    prompt = _minimal({"127": {"class_type": "LoadImage",
                               "inputs": {"image": "a.png"}}})
    assert check_fitness(prompt) is None


# --- 5) 전체 ------------------------------------------------------------

def test_report_ready_when_everything_installed():
    report = check_workflow(_minimal(), {"CheckpointLoaderSimple", "KSampler",
                                         "SaveImage"}, INSTALLED)
    assert report.ready and not report.blocked


def test_report_blocked_by_missing_nodes():
    prompt = _minimal({"54": {"inputs": {}, "_meta": {"title": "Seed Control"}}})
    report = check_workflow(prompt, None, INSTALLED)
    assert report.blocked


def test_format_failure_short_circuits():
    """형식이 다르면 뒤 단계는 검사하지 않는다."""
    report = check_workflow({"nodes": [], "links": []}, None, INSTALLED)
    assert len(report.items) == 1
    assert report.blocked


def test_outputs_exposed_on_report():
    prompt = _minimal({"95": {"class_type": "SaveImage", "inputs": {}}})
    report = check_workflow(prompt, None, INSTALLED)
    assert report.outputs == ["9", "95"]


def test_real_workflow_files_all_produce_reports():
    """저장소에 든 실제 워크플로로도 검사기가 죽지 않아야 한다."""
    from pathlib import Path

    files = sorted(Path("workflows").glob("*.json"))
    assert files, "워크플로 예시가 있어야 한다"
    for path in files:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        report = check_workflow(data, None, INSTALLED)
        assert report.items, path.name