"""infer_parameters 가 틀린 값을 잡지 않는지 검증한다.

회귀 근거 두 가지 (실측에서 발견):

1. positive/negative 뒤바뀜
   ERNIE 워크플로는 positive 프롬프트가 인핸서 체인(링크)으로 들어오고,
   negative 프롬프트만 문자열로 들어 있다. 링크는 후보에서 빠지므로
   후보에 네거티브 노드 하나만 남아 'positive' 로 채택됐다.
   (GUI 에 네거티브 문장이 프롬프트로 표시되었다)

2. 링크된 상수 미해석
   ERNIE 워크플로는 해상도를 PrimitiveInt 노드로 빼내 둔다.
   (EmptyLatentImage.width = ["123:110", 0]) 링크를 건너뛰면
   width/height 를 아예 추출하지 못했다. 1024x1536 인 워크플로인데
   GUI 에 해상도가 비어 있었다.
"""
from __future__ import annotations

from app.comfy.workflow import Workflow, infer_parameters, resolve_constant


# --- 픽스처 --------------------------------------------------------------

def _ernie_workflow() -> dict:
    """ERNIE 구조: positive 는 링크, negative 는 문자열, 크기는 PrimitiveInt."""
    return {
        "74": {"class_type": "CLIPTextEncode",
               "inputs": {"text": ["122:119", 0], "clip": ["49", 0]}},
        "75": {"class_type": "CLIPTextEncode",
               "inputs": {"text": "Avoid blurry, low-quality", "clip": ["49", 0]}},
        "89": {"class_type": "KSampler",
               "inputs": {"seed": 1, "steps": 9, "cfg": 1,
                          "sampler_name": "euler", "scheduler": "simple",
                          "denoise": 1, "model": ["73", 0],
                          "positive": ["74", 0], "negative": ["75", 0],
                          "latent_image": ["123:109", 0]}},
        "123:109": {"class_type": "EmptyLatentImage",
                    "inputs": {"width": ["123:110", 0],
                               "height": ["123:111", 0], "batch_size": 1}},
        "123:110": {"class_type": "PrimitiveInt", "inputs": {"value": 1024}},
        "123:111": {"class_type": "PrimitiveInt", "inputs": {"value": 1536}},
    }


def _z_anime_workflow() -> dict:
    """Z-Anime 구조: positive/negative 문자열이 서로 다른 노드.

    네거티브 노드를 먼저 둔다. 거리가 같으면 순서대로 고르는 구현에서는
    여기가 틀린 곳이다.
    """
    return {
        "100": {"class_type": "CLIPTextEncode",
                "inputs": {"text": "Avoid blurry", "clip": ["97", 0]}},
        "20": {"class_type": "CLIPTextEncode",
               "inputs": {"text": "anime girl", "clip": ["97", 0]}},
        "17": {"class_type": "KSampler",
               "inputs": {"steps": 10, "cfg": 1.1, "sampler_name": "euler",
                          "scheduler": "beta", "denoise": 1,
                          "model": ["2", 0], "positive": ["20", 0],
                          "negative": ["100", 0], "latent_image": ["6", 0]}},
        "6": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 1024, "height": 1536, "batch_size": 1}},
    }


def _enhancer_workflow() -> dict:
    """기존 인핸서 워크플로 (TextEncode 4 는 positive/negative 양쪽에 연결)."""
    return {
        "14": {"class_type": "QwenImage21PromptEnhancerT8",
               "inputs": {"prompt": "", "seed": 1}},
        "4": {"class_type": "TextEncodeQwenImage21",
              "inputs": {"prompt": ["14", 0], "negative_prompt": "NEG",
                         "clip": ["2", 0]}},
        "6": {"class_type": "KSampler",
              "inputs": {"seed": 5, "steps": 40, "cfg": 3,
                         "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1, "model": ["1", 0],
                         "positive": ["4", 0], "negative": ["4", 0],
                         "latent_image": ["5", 0]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 704, "height": 1024, "batch_size": 1}},
    }
# --- 1. positive / negative 구분 ---------------------------------------

def test_negative_only_node_is_never_positive():
    """negative 에만 연결된 노드가 positive 로 잡히면 안 된다."""
    specs = infer_parameters(_ernie_workflow())
    # positive 프롬프트가 링크라 정답 후보가 없다 -> 없는 게 맞다
    assert "positive" not in specs


def test_no_guessed_prompt_when_positive_is_computed():
    """없는데 지어내지 않는다. defaults() 에 positive 가 없어야 한다."""
    defaults = _load(_ernie_workflow()).defaults()
    assert "positive" not in defaults
    assert "Avoid blurry, low-quality" not in defaults.values()


def test_positive_picked_over_earlier_negative_node():
    """두 노드가 모두 후보여도 positive 로 연결된 쪽을 고른다."""
    specs = infer_parameters(_z_anime_workflow())
    assert specs["positive"].node == "20"
    assert _load(_z_anime_workflow()).defaults()["positive"] == "anime girl"


def test_same_node_on_both_slots_still_yields_prompt():
    """회귀: 한 노드가 양쪽에 연결돼도 프롬프트를 잡는다.

    기존 인핸서 워크플로는 TextEncode(4) 가 positive/negative 양쪽에 연결되고,
    실제 문자열 입력은 인핸서(14) 에 있다. 여기까지 막으면 안 된다.
    """
    specs = infer_parameters(_enhancer_workflow())
    assert specs["positive"].node == "14"
    assert specs["positive"].input == "prompt"
    assert specs["seed"].node == "6"


# --- 2. 링크된 상수 해석 ------------------------------------------------

def test_size_read_through_primitive_link():
    """PrimitiveInt 로 연결된 width/height 를 읽는다."""
    defaults = _load(_ernie_workflow()).defaults()
    assert defaults["width"] == 1024
    assert defaults["height"] == 1536


def test_primitive_link_becomes_editable_parameter():
    """링크라도 상수 노드면 조작 가능한 파라미터로 잡는다."""
    specs = infer_parameters(_ernie_workflow())
    assert specs["width"].node == "123:109"
    assert specs["height"].node == "123:109"


def test_apply_keeps_original_link():
    """apply() 는 링크를 덮어쓰지 않으므로 원본 연결이 남는다."""
    wf = _load(_ernie_workflow())
    result = wf.apply({"width": 2048})
    assert result["123:109"]["inputs"]["width"] == ["123:110", 0]


def test_literal_size_still_works():
    """링크가 아니면 기존처럼 그대로 읽는다."""
    defaults = _load(_z_anime_workflow()).defaults()
    assert (defaults["width"], defaults["height"]) == (1024, 1536)


# --- 3. resolve_constant 자체 -------------------------------------------

def test_computed_value_is_not_guessed():
    """PreviewAny 같은 계산 노드를 따라가 값을 추정하지 않는다."""
    prompt = {
        "9": {"class_type": "EmptyLatentImage",
              "inputs": {"width": ["w", 0], "height": ["w", 0]}},
        "w": {"class_type": "PreviewAny", "inputs": {"source": ["s", 0]}},
        "s": {"class_type": "KSampler", "inputs": {"steps": 4}},
    }
    assert resolve_constant(prompt, ["w", 0]) is None
    assert "width" not in _load(prompt).defaults()


def test_resolve_constant_follows_chain():
    prompt = {"a": {"class_type": "PrimitiveInt", "inputs": {"value": 5}},
              "b": {"class_type": "PrimitiveInt", "inputs": {"value": ["a", 0]}}}
    assert resolve_constant(prompt, ["b", 0]) == 5


def test_resolve_constant_rejects_non_constant():
    prompt = {"a": {"class_type": "TextEncodeQwenImage21",
                    "inputs": {"prompt": "x"}}}
    assert resolve_constant(prompt, ["a", 0]) is None


def test_resolve_constant_rejects_missing_node():
    assert resolve_constant({}, ["nope", 0]) is None


def test_resolve_constant_stops_at_depth_limit():
    """순환 링크에서도 끝나야 한다."""
    prompt = {"a": {"class_type": "PrimitiveInt", "inputs": {"value": ["b", 0]}},
              "b": {"class_type": "PrimitiveInt", "inputs": {"value": ["a", 0]}}}
    assert resolve_constant(prompt, ["a", 0], depth=2) is None


def test_resolve_constant_needs_two_element_link():
    assert resolve_constant({}, ["only"]) is None
    assert resolve_constant({}, ["a", 0, 1]) is None


def _load(prompt: dict) -> Workflow:
    return Workflow(path=None, name="t", description="", output_node="",
                    prompt=prompt, parameters=infer_parameters(prompt))