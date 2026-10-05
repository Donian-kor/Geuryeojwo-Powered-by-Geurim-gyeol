"""프롬프트 인퇰서 자동 주입 (워크플로에 인퇰서 노드가 없는 경우).

배경: 워크플로에 인퇰서 노드가 없으면 예전에는 스위치가 아예 사라져
LLM 을 못 썼다. 이제는 프로그램이 실행 그래프에 노드를 직접 넣는다.
여기서는 '넣어도 되는 경우' 와 '넣으면 안 되는 경우' 를 나눠 검증한다.

넣으면 안 되는 경우:
- 텍스트 인코더가 여러 개인 모델 (Flux clip_l/t5xxl, SD3 3개)
  → 어느 인코더에 붙여야 할지 워크플로마다 달라 정할 수 없다
- 이미 인퇰서 노드가 있는 워크플로 → 중복이 된다

네트워크는ComfyUI 응답을 대체하고, Qt 창은 QT_QPA_PLATFORM=offscreen(conftest) 을 쓴다.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.comfy.client import (
    ComfyClient, SystemInfo, _input_default, _input_options,
)
from app.engine.comfy_engine import (
    GeurimGyeolEngine, _enhancer_model, _enhancer_switch_gate,
    _find_enhancer_node, _free_node_id, injection_block_reason, injection_target,
)

ENHANCER_CLASS = "QwenImage21PromptEnhancerT8"

# ComfyUI object_info 응답을 그대로 옮긴 형태 (실측 구조)
FAKE_DEFAULTS = {
    "prompt": "",
    "api_mode": "온라인 AI 상점",
    "max_output_chars": 0,
    "wh_ratio": "auto",
    "transparent_alpha": False,
    "ai_workshop_model": "gemini-3.5-flash",
}
FAKE_OPTIONS = {
    "api_mode": ["온라인 AI 상점", "로컬 GGUF (llama.cpp / Qwen, 무설정)"],
    "local_model": ["qwen_pe_t2i_heretic-Q4_K_M.gguf"],
    "custom_model": [],          # 자유 입력이라 선택지 없음
    "ai_workshop_model": ["gemini-3.5-flash"],
}

# SDXL 처럼 프롬프트 문자열 입력이 하나뿐인 워크플로 (주입 가능)
SINGLE_TEXT_WORKFLOW = {
    "4": {"class_type": "CLIPTextEncode", "inputs": {
        "text": "고양이", "clip": ["2", 0]}},
    "5": {"class_type": "EmptyLatentImage",
          "inputs": {"width": 512, "height": 512}},
    "6": {"class_type": "KSampler", "inputs": {
        "seed": 1, "steps": 20, "cfg": 7.0,
        "model": ["3", 0], "positive": ["4", 0], "negative": ["4", 0],
        "latent_image": ["5", 0]}},
    "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["8", 0]}},
    "8": {"class_type": "VAELoader", "inputs": {"vae_name": "v.safetensors"}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["7", 0]}},
    "2": {"class_type": "CheckpointLoaderSimple",
          "inputs": {"ckpt_name": "sdxl.safetensors"}},
    "3": {"class_type": "EmptyModel", "inputs": {}},
}

# Flux 처럼 인코더 입력이 둘인 워크플로 (주입 금지)
MULTI_ENCODER_WORKFLOW = {
    "4": {"class_type": "CLIPTextEncodeFlux", "inputs": {
        "clip_l": "고양이", "t5xxl": "고양이", "width": 512, "height": 512,
        "clip": ["2", 0]}},
    "6": {"class_type": "KSampler", "inputs": {
        "seed": 1, "steps": 20, "cfg": 7.0, "positive": ["4", 0],
        "latent_image": ["5", 0]}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["6", 0]}},
}
# krea2 turbo t2i 스타일: LLM(TextGenerate) 노드가 이미 존재하고,
# 사용자 프롬프트는 PrimitiveStringMultiline 의 "value" 에 직접 들어있다.
# TextGenerate 가 인enhancer 로 인정되어야 하고,
# 상수 노드의 "value" 를 붙일 자리로 인정되어야 한다.
KREA2_WORKFLOW = {
    "30:16": {"class_type": "TextGenerate", "inputs": {
        "system_prompt": "You are an expert prompt engineer.",
        "user_prompt": ["30:17", 0], "model": "qwen_pe_t2i_heretic-Q4_K_M.gguf"}},
    "30:17": {"class_type": "StringConcatenate", "inputs": {
        "string_a": ["30:18", 0], "string_b": ["30:19", 0]}},
    "30:18": {"class_type": "PrimitiveStringMultiline",
              "inputs": {"value": "You are an expert prompt engineer."}},
    "30:19": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "고양이"}},
    "30:11": {"class_type": "CLIPLoader", "inputs": {"clip_name": "clip.safetensors"}},
    "30:6": {"class_type": "CLIPTextEncode", "inputs": {
        "text": ["30:16", 0], "clip": ["30:11", 0]}},
    "30:5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512}},
    "30:8": {"class_type": "KSampler", "inputs": {
        "seed": 1, "steps": 20, "cfg": 7.0, "model": ["30:7", 0],
        "positive": ["30:6", 0], "latent_image": ["30:5", 0]}},
    "29": {"class_type": "SaveImage", "inputs": {"images": ["30:8", 0]}},
}


def _write_workflow(root, name: str, prompt: dict) -> None:
    (root / "workflows" / f"{name}.json").write_text(
        json.dumps({"name": name, "prompt": prompt}, ensure_ascii=False),
        encoding="utf-8",
    )


def _mock_comfy(monkeypatch, *, local_models=("pe.gguf",)):
    """인퇰서 관련 object_info 조회를 대체한다."""
    options = dict(FAKE_OPTIONS)
    options["local_model"] = list(local_models)

    async def _defaults(self, node_class):
        if node_class != ENHANCER_CLASS:
            return {}
        return dict(FAKE_DEFAULTS)

    async def _node_options(self, node_class, input_name):
        if node_class != ENHANCER_CLASS:
            return []
        return list(options.get(input_name, []))

    monkeypatch.setattr(ComfyClient, "get_node_defaults", _defaults)
    monkeypatch.setattr(ComfyClient, "get_node_options", _node_options)
    monkeypatch.setattr(
        GeurimGyeolEngine, "online", property(lambda self: True)
    )


def _engine(tmp_path, monkeypatch, workflow: dict, name="wf", **kw) -> GeurimGyeolEngine:
    root = tmp_path / "root"
    for folder in ("config", "workflows", "outputs", "sessions"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    _write_workflow(root, name, workflow)
    _mock_comfy(monkeypatch, **kw)
    eng = GeurimGyeolEngine(root)
    eng.refresh_workflows()
    eng.system_info = SystemInfo(online=True, error="")
    eng.select_workflow(name)
    return eng


# --- object_info 해석 ------------------------------------------------


def test_input_options_reads_t8_combo_shape():
    """T8 팩식 ["COMBO", {options:[...]}] 에서 선택지를 읽는다."""
    spec = ["COMBO", {"options": ["a", "b"], "default": "a"}]
    assert _input_options(spec) == ["a", "b"]


def test_input_options_ignores_free_text_string():
    """자유 입력 STRING 은 선택지가 없다.

    회귀: ["STRING", {...}] 를 선택지로 읽으면 타입 이름 'STRING' 이
    LLM 모델명으로 기록된다 (기록에 'STRING' 이 찍히는 원인).
    """
    spec = ["STRING", {"display_name": "사용자 정의 모델 ID", "default": ""}]
    assert _input_options(spec) == []


def test_input_options_reads_legacy_nested_shape():
    """구버전 [[...], {...}] 모양도 읽는다 (KSampler)."""
    assert _input_options([["euler", "heun"], {}]) == ["euler", "heun"]


def test_input_default_prefers_installed_option():
    """선언 기본값이 설치 목록에 없으면 첫 번째 선택지를 쓴다."""
    spec = ["COMBO", {"default": "없는모델.gguf", "options": ["있는모델.gguf"]}]
    assert _input_default(spec) == "있는모델.gguf"


# --- 붙일 자리 판정 --------------------------------------------------


def test_textgenerate_is_recognized_as_enhancer(tmp_path, monkeypatch):
    """TextGenerate 노드는 인enhancer 로 인정된다.

    회귀: krea2 turbo t2i 워크플로는 LLM 노드 class_type 이 'TextGenerate' 이다.
    _ENHANCER_TYPES 에 없으면 인enhancer 로 인식되지 않아 스위치가
    비활성화되었다.
    """
    eng = _engine(tmp_path, monkeypatch, KREA2_WORKFLOW)
    assert _find_enhancer_node(eng.active_workflow.prompt) == "30:16"


def test_constant_node_value_is_injection_target():
    """상수 노드(PrimitiveStringMultiline)의 value 에 붙일 수 있다.

    회귀: krea2 turbo t2i 는 positive 가 PrimitiveStringMultiline 의
    'value' 를 가리킨다. _PROMPT_TEXT_INPUTS 에 'value' 가 없어
    _prompt_text_inputs 가 빈 목록이 되고 '프롬프트를 직접 받지 않습니다'
    라고 차단되었다.
    """
    prompt = {
        "19": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "고양이"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ["19", 0]}},
    }
    wf = type("W", (), {"prompt": prompt, "parameters": {
        "positive": type("S", (), {"node": "19", "input": "value"})(),
    }})()
    assert injection_target(wf) == ("19", "value")
    assert injection_block_reason(wf) == ""


def test_encoder_with_value_string_is_still_refused():
    """인코더 노드의 값 문자열 앞에는 붙이지 않는다.

    회귀: 상수 노드 예외를 넣으면서 "inputs 에 문자열이 있으면 통과" 로
    느슨하게 쓰면, 인코더(CLIPTextEncodeFlux 등)까지 통과해 버린다.
    """
    prompt = {
        "4": {"class_type": "CLIPTextEncode", "inputs": {
            "value": "고양이", "clip": ["2", 0]}},
    }
    wf = type("W", (), {"prompt": prompt, "parameters": {
        "positive": type("S", (), {"node": "4", "input": "value"})(),
    }})()
    assert injection_target(wf) is None
    assert injection_block_reason(wf) != ""


# --- 워크플로 내장 분기 스위치 -------------------------------------


def test_enhancer_gate_finds_boolean_behind_switch():
    """분기 노드의 on_true 가 인퇰서면 그 조건 노드가 스위치다.

    회귀 근거: krea2 turbo t2i 는 'Boolean (Refine Prompt?)' 값이 JSON 에
    true 로 박혀 있어 프로그램 스위치를 꺼도 LLM 이 돕는다.
    """
    prompt = {
        "16": {"class_type": "TextGenerate", "inputs": {"prompt": ["17", 0]}},
        "21": {"class_type": "ComfySwitchNode", "inputs": {
            "switch": ["24", 0], "on_false": ["19", 0], "on_true": ["16", 0]}},
        "24": {"class_type": "PrimitiveBoolean", "inputs": {"value": True}},
    }
    assert _enhancer_switch_gate(prompt, "16") == "24"


def test_enhancer_gate_ignores_switch_that_leaves_enhancer():
    """인퇰서를 건드리지 않는 분기 노드는 스위치로 보지 않는다."""
    prompt = {
        "16": {"class_type": "TextGenerate", "inputs": {}},
        "22": {"class_type": "ComfySwitchNode", "inputs": {
            "switch": ["23", 0], "on_false": ["10", 0], "on_true": ["15", 0]}},
        "23": {"class_type": "PrimitiveBoolean", "inputs": {"value": False}},
    }
    assert _enhancer_switch_gate(prompt, "16") is None


def test_enhancer_gate_returns_none_without_switch(tmp_path, monkeypatch):
    """분기 노드가 없는 워크플로는 프로그램 스위치가 곧바로 통한다."""
    eng = _engine(tmp_path, monkeypatch, KREA2_WORKFLOW)
    assert _enhancer_switch_gate(eng.active_workflow.prompt, "30:16") is None


def test_injection_target_found_for_single_text_input(tmp_path, monkeypatch):
    """문자열 입력이 하나인 텍스트 인코더에는 붙일 수 있다."""
    eng = _engine(tmp_path, monkeypatch, SINGLE_TEXT_WORKFLOW)
    assert injection_target(eng.active_workflow) == ("4", "text")


def test_injection_target_refused_for_multi_encoder(tmp_path, monkeypatch):
    """Flux(clip_l/t5xxl) 처럼 인코더가 둘이면 붙이지 않는다."""
    eng = _engine(tmp_path, monkeypatch, MULTI_ENCODER_WORKFLOW)
    assert injection_target(eng.active_workflow) is None
    assert "프롬프트" in injection_block_reason(eng.active_workflow)


def test_injection_target_refused_when_already_present(tmp_path, monkeypatch):
    """이미 인퇰서 노드가 있으면 중복으로 넣지 않는다."""
    prompt = json.loads(json.dumps(SINGLE_TEXT_WORKFLOW))
    prompt["14"] = {
        "class_type": ENHANCER_CLASS,
        "inputs": {"prompt": "고양이", "local_model": "pe.gguf"},
    }
    prompt["4"]["inputs"]["text"] = ["14", 0]
    eng = _engine(tmp_path, monkeypatch, prompt)

    assert _find_enhancer_node(eng.active_workflow.prompt) == "14"
    assert injection_target(eng.active_workflow) is None
    assert injection_block_reason(eng.active_workflow) == ""

    _, payload = eng._payload(eng.build_request(prompt="강아지"))
    assert _find_enhancer_node(payload) == "14", "새 노드를 끼워 넣으면 안 된다"


def test_block_reason_names_the_node_for_multi_encoder():
    """사유 문구에 어느 노드인지 나와야 사용자가 고칠 수 있다."""
    wf = type("W", (), {"prompt": MULTI_ENCODER_WORKFLOW, "parameters": {
        "positive": type("S", (), {"node": "4", "input": "clip_l"})(),
    }})()
    assert "4" in injection_block_reason(wf)


# --- 주입 결과 --------------------------------------------------------


def test_payload_injects_enhancer_before_text_encoder(tmp_path, monkeypatch):
    """인퇰서 노드가 없으면 payload 에 추가하고 프롬프트를 연결한다."""
    eng = _engine(tmp_path, monkeypatch, SINGLE_TEXT_WORKFLOW)
    _, payload = eng._payload(eng.build_request(prompt="바다 위 증기선"))

    injected = _find_enhancer_node(payload)
    assert injected is not None, "인퇰서 노드가 주입돼야 한다"

    # 텍스트 인코더는 원문 대신 인퇰서 출력을 받는다
    assert payload["4"]["inputs"]["text"] == [injected, 0]

    node = payload[injected]
    assert node["class_type"] == ENHANCER_CLASS
    assert node["inputs"]["prompt"] == "바다 위 증기선"


def test_injected_node_fills_every_required_input(tmp_path, monkeypatch):
    """필수 입력이 하나라도 비면 ComfyUI 가 노드를 거부한다.

    회귀 근거: 실제로 이 노드는 prompt/api_mode/max_output_chars/
    wh_ratio/transparent_alpha/ai_workshop_model 을 요구한다.
    """
    eng = _engine(tmp_path, monkeypatch, SINGLE_TEXT_WORKFLOW)
    _, payload = eng._payload(eng.build_request(prompt="고양이"))

    inputs = payload[_find_enhancer_node(payload)]["inputs"]
    for name in FAKE_DEFAULTS:
        assert name in inputs, f"필수 입력 {name} 이 비어 있다"


def test_injected_node_prefers_local_gguf_over_online_api(tmp_path, monkeypatch):
    """GGUF 가 깔려 있으면 로컬 백엔드를 고른다.

    회귀 근거: 노드 기본값은 '온라인 AI 상점' 이라 API 키가 없으면
    실제 실행에서 QwenImage21PromptEnhancerError 로 실패했다.
    """
    eng = _engine(tmp_path, monkeypatch, SINGLE_TEXT_WORKFLOW)
    _, payload = eng._payload(eng.build_request(prompt="고양이"))

    inputs = payload[_find_enhancer_node(payload)]["inputs"]
    assert "gguf" in inputs["api_mode"].lower()
    assert inputs["local_model"] == "pe.gguf"
    # 자유 입력인 custom_model 에는 타입 이름이 새어들면 안 된다
    assert inputs.get("custom_model") in (None, "")


def test_injected_node_records_llm_model_name(tmp_path, monkeypatch):
    """자동 주입된 경우에도 LLM 모델명이 기록된다 (LLM: N/A 방지)."""
    eng = _engine(tmp_path, monkeypatch, SINGLE_TEXT_WORKFLOW)
    _, payload = eng._payload(eng.build_request(prompt="고양이"))
    assert _enhancer_model(payload) == "pe.gguf"


def test_switch_off_leaves_prompt_untouched(tmp_path, monkeypatch):
    """스위치를 끄면 주입하지도 않고 원문을 그대로 보낸다."""
    eng = _engine(tmp_path, monkeypatch, SINGLE_TEXT_WORKFLOW)
    _, payload = eng._payload(
        eng.build_request(prompt="고양이", enhance_prompt=False)
    )
    assert _find_enhancer_node(payload) is None
    assert payload["4"]["inputs"]["text"] == "고양이"


def test_injection_does_not_touch_workflow_object(tmp_path, monkeypatch):
    """주입은 payload 사본에만 일어나야 한다.

    회귀: 워크플로 객체를 직접 고치면 두 번째 생성에서 노드가 두 개가 된다.
    """
    eng = _engine(tmp_path, monkeypatch, SINGLE_TEXT_WORKFLOW)
    before = json.dumps(eng.active_workflow.prompt, sort_keys=True)

    for _ in range(3):
        eng._payload(eng.build_request(prompt="고양이"))

    after = json.dumps(eng.active_workflow.prompt, sort_keys=True)
    assert before == after


def test_injected_node_id_never_collides():
    """이미 같은 이름의 노드가 있으면 다른 번호를 쓴다."""
    assert _free_node_id({}) == "prompt_enhancer_1"
    assert _free_node_id({"prompt_enhancer_1": {}}) == "prompt_enhancer_2"
    assert _free_node_id({"prompt_enhancer_2": {}}) == "prompt_enhancer_1"


# --- 준비 상태 안내 ---------------------------------------------------


def test_enhancer_status_reports_missing_gguf(tmp_path, monkeypatch):
    """GGUF 가 없으면 이유를 알려준다 (조용히 실패하지 않게)."""
    eng = _engine(tmp_path, monkeypatch, SINGLE_TEXT_WORKFLOW, local_models=())
    ok, message = eng.enhancer_status()
    assert ok is False
    assert "GGUF" in message


def test_enhancer_status_ok_when_gguf_installed(tmp_path, monkeypatch):
    eng = _engine(tmp_path, monkeypatch, SINGLE_TEXT_WORKFLOW)
    ok, _ = eng.enhancer_status()
    assert ok is True


def test_missing_enhancer_node_falls_back_to_raw_prompt(tmp_path, monkeypatch):
    """인함서 노드가 아예 없으면 원본 프롬프트로 생성한다 (조용히 실패 X)."""
    eng = _engine(tmp_path, monkeypatch, SINGLE_TEXT_WORKFLOW)

    async def _no_defaults(self, node_class):
        return {}

    monkeypatch.setattr(ComfyClient, "get_node_defaults", _no_defaults)
    eng._enhancer_defaults = None

    _, payload = eng._payload(eng.build_request(prompt="고양이"))

    assert _find_enhancer_node(payload) is None
    assert payload["4"]["inputs"]["text"] == "고양이"


# --- GUI 스위치 -------------------------------------------------------


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _window(eng, qapp, monkeypatch, tmp_path):
    """엔진을 갈아 끼운 MainWindow 를 만든다."""
    import app.gui.main_window as mw

    monkeypatch.setattr(mw, "ROOT", tmp_path)
    monkeypatch.setattr(mw, "GeurimGyeolEngine", lambda root: eng)
    monkeypatch.setattr(
        GeurimGyeolEngine, "model_options", lambda self: {}
    )
    monkeypatch.setattr(
        GeurimGyeolEngine, "sampler_options",
        lambda self: {"sampler": ["euler"], "scheduler": ["normal"]},
    )
    monkeypatch.setattr(
        GeurimGyeolEngine, "enhancer_status",
        lambda self: (True, "인ㅎㅏㄴ서 사용 가능"),
    )
    window = mw.MainWindow()
    window.show()
    qapp.processEvents()
    return window


def test_switch_stays_enabled_and_explains_auto_add(qapp, tmp_path, monkeypatch):
    """인함서 노드가 없어도 켤 수 있고, 자동으로 추가됨을 알려준다."""
    eng = _engine(tmp_path, monkeypatch, SINGLE_TEXT_WORKFLOW)
    window = _window(eng, qapp, monkeypatch, tmp_path)
    try:
        # 인함서 스위치는 '고급' 안에 있다. 사용자가 여는 경로를 그대로 따른다.
        window.advanced_btn.setChecked(True)
        window._setup_enhancer({}, {})
        assert window.enhance.isVisible() is True
        assert window.enhance.isEnabled() is True
        assert "자동으로 추가" in window.enhance.toolTip()
    finally:
        window.close()


def test_switch_is_disabled_for_multi_encoder_workflow(qapp, tmp_path, monkeypatch):
    """붙일 수 없으면 조용히 사라지지 않고 이유를 남기고 끈다."""
    eng = _engine(tmp_path, monkeypatch, MULTI_ENCODER_WORKFLOW)
    window = _window(eng, qapp, monkeypatch, tmp_path)
    try:
        window._setup_enhancer({}, {})
        assert window.enhance.isChecked() is False
        assert window.enhance.isEnabled() is False
        assert window.enhance.toolTip() != ""
    finally:
        window.close()


def test_warning_appears_when_gguf_missing(qapp, tmp_path, monkeypatch):
    """켜놨는데 GGUF 가 없으면 상태바에 경고가 보인다."""
    eng = _engine(tmp_path, monkeypatch, SINGLE_TEXT_WORKFLOW, local_models=())
    window = _window(eng, qapp, monkeypatch, tmp_path)
    try:
        window.advanced_btn.setChecked(True)
        window._setup_enhancer({}, {})
        window._enhancer_status = (False, "인함서용 GGUF 모델이 설치돼 있지 않습니다.")
        window._update_enhancer_warning()
        assert window.enhancer_warning.isVisible() is True
        assert "GGUF" in window.enhancer_warning.text()

        window.enhance.setChecked(False)
        assert window.enhancer_warning.isVisible() is False
    finally:
        window.close()