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

from app.comfy.workflow import (
    Workflow, _distance_to_sampler, _downstream_index, infer_parameters,
    resolve_constant,
)


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
    # 네거티브 문장은 negative 칸에만 있어야 한다. positive 로 새지 않는다.
    assert "Avoid blurry, low-quality" not in defaults.get("positive", "")


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


# --- 4. 로더 고르기 ----------------------------------------------------

def _sampler_wf(extra_nodes: dict, chain: list[str]) -> dict:
    """KSampler(9) 로 이어지는 워크플로를 만든다. chain 은 로더 번호 목록."""
    nodes: dict = {}
    previous = None
    for number in chain:
        nodes[number] = {
            "class_type": "LoraLoader",
            "inputs": {"lora_name": f"{number}.safetensors",
                       "model": [previous, 0] if previous else ["1", 0]},
        }
        previous = number
    nodes["1"] = {"class_type": "UNETLoader",
                  "inputs": {"unet_name": "u.safetensors"}}
    nodes["9"] = {"class_type": "KSampler",
                  "inputs": {"seed": 1, "steps": 8, "cfg": 1.0,
                             "model": [previous, 0], "positive": ["30", 0]}}
    nodes["30"] = {"class_type": "CLIPTextEncode",
                   "inputs": {"text": "고양이", "clip": ["10", 0]}}
    nodes["40"] = {"class_type": "VAEDecode",
                   "inputs": {"samples": ["9", 0], "vae": ["1", 0]}}
    nodes["50"] = {"class_type": "SaveImage", "inputs": {"images": ["40", 0]}}
    nodes["10"] = {"class_type": "CLIPLoader",
                   "inputs": {"clip_name": "clip.safetensors", "type": "qwen_image"}}
    nodes.update(extra_nodes)
    return nodes


def test_downstream_index_points_to_consumers():
    prompt = {"a": {"class_type": "X", "inputs": {"in": ["b", 0]}},
              "b": {"class_type": "Y", "inputs": {}}}
    assert _downstream_index(prompt)["b"] == ["a"]


def test_distance_walks_toward_sampler():
    """회귀: 예전엔 입구를 따라 올라가서 항상 99 였다.

    후보에서 샘플러로 '내려가야' 거리가 줄어든다.
    """
    prompt = _sampler_wf({}, ["5", "6", "7"])
    forward = _downstream_index(prompt)
    samplers = {"9"}
    assert _distance_to_sampler("7", forward, samplers) == 1
    assert _distance_to_sampler("6", forward, samplers) == 2
    assert _distance_to_sampler("5", forward, samplers) == 3


def test_unreachable_node_has_max_distance():
    prompt = _sampler_wf({"99": {"class_type": "LoraLoader",
                                 "inputs": {"lora_name": "orphan.safetensors"}}},
                         ["5"])
    forward = _downstream_index(prompt)
    assert _distance_to_sampler("99", forward, {"9"}) == 99


def test_every_lora_in_the_chain_gets_a_row():
    """LoRA 는 이어 붙일 수 있다. 1번이 UNET 에 먼저 붙은 것.

    회귀: 예전에는 '실제로 쓰는 것 하나' 만 골랐다. (샘플러에 가장 가까운
    쪽을 고르는 규칙) 그래서 첫 번째 LoRA 를 고를 방법이 없었다.
    """
    specs = infer_parameters(_sampler_wf({}, ["5", "6", "7"]))
    assert specs["lora"].node == "5", "먼저 붙은 것이 1번"
    assert specs["lora2"].node == "6"
    assert specs["lora3"].node == "7"


def test_lora_out_of_the_chain_goes_last():
    """체인에 끼어 있지 않은 LoRA 는 맨 뒤로 밀어낸다."""
    stray = {"99": {"class_type": "LoraLoader",
                    "inputs": {"lora_name": "99.safetensors",
                               "model": ["1", 0]}}}
    specs = infer_parameters(_sampler_wf(stray, ["5", "6", "7"]))
    assert specs["lora"].node == "5", "실제로 쓰이는 것부터 앞에 온다"
    assert specs["lora3"].node == "7"
    assert specs["lora4"].node == "99", "쓰이지 않는 LoRA 는 끝에 놓인다"


def test_orphan_loader_loses_to_used_one():
    """인핸서 전용 로더(어디에도 안 연결)는 밀려나야 한다."""
    prompt = _sampler_wf({"20": {"class_type": "CLIPLoader",
                                 "inputs": {"clip_name": "enhancer.safetensors",
                                            "type": "flux2"}}}, [])
    specs = infer_parameters(prompt)
    assert specs["clip"].node == "10", "본용 CLIP 이 밀려났다"


def test_single_loader_is_kept_as_is():
    specs = infer_parameters(_sampler_wf({}, []))
    assert specs["clip"].node == "10"
    assert specs["unet"].node == "1"


def test_empty_model_name_loses_to_filled_one():
    """이름이 빈 로더는 고를 것이 없다. 값이 있는 쪽을 고른다."""
    prompt = _sampler_wf({"20": {"class_type": "CLIPLoader",
                                 "inputs": {"clip_name": "", "type": "flux2"}}}, [])
    specs = infer_parameters(prompt)
    assert specs["clip"].node == "10"


def test_all_empty_still_exposes_the_slot():
    """전부 비었어도 칸은 남긴다. 없으면 고를 곳이 사라진다."""
    prompt = _sampler_wf({}, [])
    prompt["10"]["inputs"]["clip_name"] = ""
    specs = infer_parameters(prompt)
    assert "clip" in specs


def test_model_slot_labels_unchanged():
    specs = infer_parameters(_sampler_wf({}, []))
    assert specs["unet"].label == "확산 모델"
    assert specs["clip"].label == "텍스트 인코더"
    assert specs["unet"].kind == "model:diffusion_models"


# --- 5. 폴더를 노드 종류로 구분 ---------------------------------------

def _two_model_name_workflow() -> dict:
    """model_name 을 서로 다른 폴더로 쓰는 노드가 함께 있는 워크플로."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "realvisxl.safetensors"}},
        "2": {"class_type": "UpscaleModelLoader",
              "inputs": {"model_name": "4x-UltraSharp.pth"}},
        "3": {"class_type": "SAMLoader",
              "inputs": {"model_name": "sam_vit_b.pth"}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "고양이", "clip": ["1", 1]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "6": {"class_type": "KSampler",
              "inputs": {"seed": 1, "steps": 20, "cfg": 7.0,
                         "sampler_name": "euler", "scheduler": "normal",
                         "denoise": 1, "model": ["1", 0],
                         "positive": ["4", 0], "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecode",
              "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0]}},
        "9": {"class_type": "UpscaleImage",
              "inputs": {"upscale_model": ["2", 0], "image": ["8", 0]}},
    }


def test_same_input_name_resolves_by_node_class():
    """회귀: model_name 은 노드에 따라 폴더가 다르다.

    이름만 보고 하나를 고르면 업스케일 칸에 SAM 모델이 뜨거나 그 반대다.
    """
    specs = infer_parameters(_two_model_name_workflow())
    assert specs["upscale_model"].kind == "model:upscale_models"
    assert specs["sam_model"].kind == "model:sam"
    assert specs["upscale_model"].node == "2"
    assert specs["sam_model"].node == "3"


def test_ambiguous_input_name_is_never_guessed():
    """아무 규칙에도 없으면 만들지 않는다. 추측해서 틀린 폴더를 더 낫다."""
    prompt = {"1": {"class_type": "ImageEncodeUtennx",
                    "inputs": {"model_name": "whatever.pth"}}}
    specs = infer_parameters(prompt)
    assert not any(str(v.kind).startswith("model:") for v in specs.values())


def _load(prompt: dict) -> Workflow:
    return Workflow(path=None, name="t", description="", output_node="",
                    prompt=prompt, parameters=infer_parameters(prompt))


def test_negative_only_node_is_exposed_as_negative():
    """회귀: negative 에만 연결된 노드를 버렸다.

    positive 로 잘못 잡히지 않도록 후보에서 뺐는데, 그 뒤를 다시
    negative 칸으로 되돌리지 않았다. 그래서 문자열 프롬프트가 두 개
    있는 워크플로는 네거티브를 고칠 방법이 없었다.
    (Z-Anime: 20 이 positive, 100 이 negative 인데 100 이 사라졌다)
    """
    specs = infer_parameters(_z_anime_workflow())
    assert specs["positive"].node == "20"
    assert specs["negative"].node == "100", "네거티브 칸이 없다"
    assert specs["negative"].input == "text"
    assert specs["negative"].label == "네거티브 프롬프트"


def test_negative_is_not_invented_without_a_negative_input():
    """negative 로 연결된 곳이 없으면 칸도 만들지 않는다."""
    prompt = {
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "고양이", "clip": ["1", 0]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "6": {"class_type": "KSampler",
              "inputs": {"steps": 10, "cfg": 7.0, "sampler_name": "euler",
                         "scheduler": "normal", "denoise": 1, "model": ["1", 0],
                         "positive": ["2", 0], "latent_image": ["5", 0]}},
    }
    specs = infer_parameters(prompt)
    assert specs["positive"].node == "2"
    assert "negative" not in specs, "네거티브가 없는데 지어냈다"


def test_negative_value_lands_on_its_own_node():
    specs = infer_parameters(_z_anime_workflow())
    workflow = _load(_z_anime_workflow())
    negative = specs["negative"]
    payload = workflow.apply({"negative": "새 네거티브", "positive": "새 프롬프트"})
    assert payload[negative.node]["inputs"][negative.input] == "새 네거티브"
    assert payload[specs["positive"].node]["inputs"]["text"] == "새 프롬프트"
    # 원본은 바뀌지 않는다
    assert workflow.prompt[negative.node]["inputs"][negative.input] == "Avoid blurry"
