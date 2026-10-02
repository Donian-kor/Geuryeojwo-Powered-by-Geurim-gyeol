"""ComfyUI API 형식 워크플로 관리 (v0.2 §5).

워크플로는 JSON 파일로 저장하며, parameters 맵을 통해
GUI 위젯과 워크플로 노드를 코드 수정 없이 연결한다.

구조 (v0.2 §5.1):
    {
      "name": "표시 이름",
      "description": "설명",
      "output_node": "8",
      "prompt": { ...ComfyUI API 형식... },
      "parameters": {
        "파라미터명": {"node": "6", "input": "steps"},
        ...
      }
    }
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParameterSpec:
    """GUI 파라미터 하나가 워크플로의 어느 노드/입력에 대응하는지."""

    name: str
    node: str
    input: str
    label: str | None = None
    kind: str = "text"  # text | int | float | combo
    choices: list[str] = field(default_factory=list)
    default: Any = None

    @property
    def display_label(self) -> str:
        return self.label or self.name


@dataclass
class Workflow:
    """로드된 워크플로."""

    path: Path
    name: str
    description: str
    output_node: str
    prompt: dict
    parameters: dict[str, ParameterSpec]
    meta: dict = field(default_factory=dict)

    def apply(self, values: dict[str, Any]) -> dict:
        """값을 주입한 ComfyUI API 형식 워크플로를 만든다.

        워크플로를 복사해 수정하므로 원본은 변하지 않는다.
        """
        result = copy.deepcopy(self.prompt)
        for key, value in values.items():
            spec = self.parameters.get(key)
            if spec is None or value is None:
                continue
            node = result.get(spec.node)
            if node is None:
                continue
            inputs = node.setdefault("inputs", {})
            if isinstance(inputs.get(spec.input), list):
                continue  # 링크로 연결된 값은 덮어쓰지 않는다
            inputs[spec.input] = value
        return result

    def defaults(self) -> dict[str, Any]:
        """각 파라미터의 현재 워크플로 값을 읽는다."""
        result: dict[str, Any] = {}
        for key, spec in self.parameters.items():
            if spec.default is not None:
                result[key] = spec.default
                continue
            node = self.prompt.get(spec.node) or {}
            value = (node.get("inputs") or {}).get(spec.input)
            if isinstance(value, list):
                # 상수 노드로 연결된 경우 그 값을 대신 읽는다.
                # 계산값이면 임의로 추정하지 않고 아예 넣지 않는다.
                value = resolve_constant(self.prompt, value)
                if value is None:
                    continue
            result[key] = value
        return result

    def describe(self) -> str:
        return f"{self.name} — {self.description}" if self.description else self.name


# GUI 위젯 키 -> ComfyUI 입력 이름
WIDGET_KEY_TO_INPUT = {
    "unet": "unet_name", "checkpoint": "ckpt_name", "clip": "clip_name",
    "vae": "vae_name", "lora": "lora_name",
    "sampler": "sampler_name", "scheduler": "scheduler",
}


def input_of(widget_key: str) -> str:
    """GUI 위젯 키에 대응하는 ComfyUI 입력 이름을 돌려준다."""
    return WIDGET_KEY_TO_INPUT.get(widget_key, widget_key)


def model_folder(params: dict, key: str) -> str:
    """이 모델 키가 쓰는 ComfyUI 폴더 이름. 모르면 빈 문자열."""
    spec = params.get(key)
    if spec is None or ":" not in spec.kind:
        return ""
    return spec.kind.split(":", 1)[1]


def installed_models(options: dict, params: dict, key: str) -> list[str]:
    """ComfyUI 가 보고한 폴더별 목록에서 이 키의 설치된 파일만 꺼낸다.

    options: {"diffusion_models": [...], "loras": [...], ...}
             (None 이면 목록을 못 받은 상태로 본다)
    """
    folder = model_folder(params, key)
    if not folder:
        return []
    return list((options or {}).get(folder) or [])


def missing_models(
    options: dict,
    params: dict,
    selections: dict[str, str],
) -> list[tuple[str, str]]:
    """선택된 값 중 ComfyUI 에 설치되지 않은 모델을 찾는다.

    대체해 버리면 사용자는 자신이 무엇을 생성했는지 알 수 없게 된다.
    그래서 여기서는 판정만 하고 GUI 가 표시와 차단 을 맡는다.

    Args:
        selections: {위젯 키: 선택된 텍스트}
            빈 값과 "(사용 안 함)" 같은 표시용 값은 무시한다.

    Returns:
        [(위젯 키, 파일명), ...]
    """
    found: list[tuple[str, str]] = []
    for key, text in (selections or {}).items():
        if not text or text.startswith("("):
            continue
        installed = installed_models(options, params, key)
        # 목록을 못 받은 상태면 판정할 수 없다 (때로 없다고 보지 않는다)
        if installed and text not in installed:
            found.append((key, text))
    return found


def collect_extra(
    params: dict,
    selections: dict[str, str],
    lora_key: str | None = None,
    lora_strength: float | None = None,
) -> dict[str, Any]:
    """위젯에서 고른 값을 워크플로 파라미터 키로 바꿔 만든다.

    키 이름은 워크플로마다 다르다 ("sampler" 또는 "sampler_name").
    그래서 ComfyUI 입력 이름을 거쳐 spec.input 로 조회한다.
    비활성 항목은 보내지 않는다 — 그래야 워크플로 기본값이 유지된다.

    Args:
        params: 워크플로의 parameters 맵
        selections: {위젯 키: 선택된 텍스트}
        lora_key: LoRA 강도를 넣을 파라미터 키
        lora_strength: LoRA 강도 (0.00~1.50)

    Returns:
        {파라미터 키: 값}
    """
    by_input = {spec.input: key for key, spec in params.items()}
    extra: dict[str, Any] = {}
    for widget_key, text in (selections or {}).items():
        if not text or text.startswith("("):
            continue
        key = by_input.get(input_of(widget_key))
        if key:
            extra[key] = text
    if lora_key and lora_strength is not None:
        extra[lora_key] = round(lora_strength, 2)
    return extra


def _parse_parameters(raw: dict) -> dict[str, ParameterSpec]:
    """parameters 맵을 ParameterSpec 로 변환."""
    specs: dict[str, ParameterSpec] = {}
    for key, config in (raw or {}).items():
        if not isinstance(config, dict):
            continue
        specs[key] = ParameterSpec(
            name=key,
            node=str(config.get("node", "")),
            input=config.get("input", ""),
            label=config.get("label"),
            kind=config.get("kind", "text"),
            choices=list(config.get("choices", []) or []),
            default=config.get("default"),
        )
    return specs


def load_workflow(path: Path) -> Workflow | None:
    """워크플로 JSON 파일을 읽는다.

    prompt 키가 없으면 문서 전체를 워크플로로 본다
    (ComfyUI에서 그대로 내보낸 형식도 읽히도록).
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"워크플로 파싱 실패 ({path.name}): {exc}") from exc

    prompt = data.get("prompt", data)
    if not isinstance(prompt, dict) or not prompt:
        raise ValueError(f"워크플로 노드가 없습니다 ({path.name})")

    reserved = ("prompt", "name", "description", "output_node", "parameters")
    meta = {k: v for k, v in data.items() if k not in reserved}

    return Workflow(
        path=path,
        name=data.get("name", path.stem),
        description=data.get("description", ""),
        output_node=str(data.get("output_node", "")),
        prompt=prompt,
        parameters=_parse_parameters(data.get("parameters", {})),
        meta=meta,
    )


def list_workflows(directory: Path) -> list[Path]:
    """워크플로 폴더의 JSON 목록.

    사용자가 가져온 워크플로는 profiles/ 아래에 따로 둔다.
    우리가 배포한 것과 한 폴더에 섞이면 나중에 원래 상태로 되돌리기 어렵다.
    """
    if not directory.exists():
        return []
    found = [p for p in directory.glob("*.json") if p.is_file()]
    profiles = directory / "profiles"
    if profiles.is_dir():
        found += [p for p in profiles.glob("*.json") if p.is_file()]
    return sorted(found)


# Windows 파일 이름에 쓸 수 없는 문자.
_UNSAFE_CHARS = '<>:"/\\|?*'


def safe_stem(text: str) -> str:
    """이름을 파일 이름에 쓸 수 있게 바꾼다.

    Returns:
        str: 파일 이름 조각. 비어 있으면 "workflow".
    """
    cleaned = "".join(
        "_" if ch in _UNSAFE_CHARS else ch for ch in str(text)
    ).strip().strip(".")
    return cleaned[:60] or "workflow"


def save_profile(workflow_dir: Path, name: str, description: str,
                 prompt: dict, output_node: str = "") -> Path:
    """사용자가 가져온 워크플로를 profiles/ 아래에 저장한다.

    우리가 배포한 워크플로와 섞지 않는다. 섞이면 지울 때 헷갈리고
    원래 상태로 되돌리기 어렵다.

    이름을 바꿔 가면 GComboBox 항목의 이름이 달라져 드롭다운에서
    찾기 어려워지므로, 표시 이름(name)과 파일 이름(stem)을 분리한다.

    Returns:
        Path: 저장된 파일 경로.
    """
    target_dir = workflow_dir / "profiles"
    target_dir.mkdir(parents=True, exist_ok=True)

    # 배포본과 이름이 겹치지 않게 한다. 드롭다운이 파일 이름으로 찾기 때문이다.
    taken = {p.stem for p in list_workflows(workflow_dir)}
    stem = safe_stem(name)
    candidate = stem
    index = 2
    while candidate in taken:
        candidate = f"{stem}-{index}"
        index += 1
    target = target_dir / f"{candidate}.json"

    target.write_text(
        json.dumps({
            "name": name,
            "description": description,
            "output_node": output_node,
            "prompt": prompt,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


# 자동 추출 대상 파라미터와 위젯 종류
_KIND_MAP = {
    "seed": "int", "steps": "int", "width": "int", "height": "int",
    "batch_size": "int", "resolution": "int", "max_output_chars": "int",
    "cfg": "float", "denoise": "float", "guidance": "float",
    "strength_model": "float", "strength_clip": "float",
    "sampler_name": "combo", "scheduler": "combo",
}
# ComfyUI 0.38.1 의 모든 모델 선택 입력 이름 -> 폴더 (object_info 전수 조사).
# clip_name 은 1개(CLIPLoader), clip_name1~4 는 2~4개(Flux/SD3/Hunyuan/…).
# 폭이 넓은 모델일수록 CLIP 이 여러 개다.
_MODEL_FOLDERS = {
    "ckpt_name": "checkpoints",       # CheckpointLoader, ImageOnlyCheckpointLoader …
    "unet_name": "diffusion_models",  # UNETLoader, UnetLoaderGGUF
    "clip_name": "text_encoders",     # CLIPLoader, CLIPLoaderGGUF
    "clip_name1": "text_encoders",    # Dual/Triple/Quadruple CLIPLoader
    "clip_name2": "text_encoders",
    "clip_name3": "text_encoders",
    "clip_name4": "text_encoders",
    "text_encoder": "text_encoders",  # LTXAVTextEncoderLoader
    "vae_name": "vae",
    "lora_name": "loras",             # LoraLoader, LoraLoaderModelOnly …
    "existing_lora": "loras",         # Lora Manager 계열
    "config_name": "configs",         # CheckpointLoader
}
_MODEL_INPUTS = tuple(_MODEL_FOLDERS)
# 폴더를 '입력 이름' 만으로 정할 수 없는 경우. 노드 종류로 구분한다.
#
# model_name 하나를 서로 다른 노드가 서로 다른 폴더로 쓴다.
#   UpscaleModelLoader.model_name -> models/upscale_models/  (4x-UltraSharp 같은 업스케일러)
#   SAMLoader.model_name         -> models/sam/             (sam_vit 같은 세그먼트 모델)
# 이름만 보고 고르면 엉뚱한 목록이 나온다. (업스케일 칸에 SAM 모델이 뜬다)
# 여기에도 없으면 애초에 다루지 않는다. 추측해서 틀린 값을 보여주는 게 낫다.
_MODEL_FOLDERS_BY_NODE = {
    "UpscaleModelLoader": ("model_name", "upscale_models"),
    "SAMLoader": ("model_name", "sam"),
    "SAMLoaderCombined": ("model_name", "sam"),
    # 프롬프트 인핸서(T8 팩) — Diffusion 모델이 아니라 로컬 LLM(GGUF) 다.
    # 노드가 설치된 목록을 직접 주므로 폴더 경로를 우리가 따로 알 필요는 없다.
    # (노드 코드의 MODEL_SUBDIRECTORY = "LLM")
    "QwenImage21PromptEnhancerT8": ("local_model", "LLM"),
    "MiniMaxH3PromptEnhancerT8": ("local_model", "LLM"),
    "Seedance20PromptEnhancerT8": ("local_model", "LLM"),
}
# 노드 종류 -> (파라미터 키, 화면 라벨)
_NODE_LABELS = {
    "UpscaleModelLoader": ("upscale_model", "업스케일 모델"),
    "SAMLoader": ("sam_model", "SAM 모델"),
    "SAMLoaderCombined": ("sam_model", "SAM 모델"),
    "QwenImage21PromptEnhancerT8": ("local_model", "인핸서 모델 (로컬 GGUF)"),
    "MiniMaxH3PromptEnhancerT8": ("local_model", "인핸서 모델 (로컬 GGUF)"),
    "Seedance20PromptEnhancerT8": ("local_model", "인핸서 모델 (로컬 GGUF)"),
}
# 파라미터 키 -> (키, 화면 라벨)
_MODEL_LABELS = {
    "ckpt_name": ("checkpoint", "체크포인트"),
    "unet_name": ("unet", "확산 모델"),
    "clip_name": ("clip", "텍스트 인코더"),
    "clip_name1": ("clip1", "텍스트 인코더 1"),
    "clip_name2": ("clip2", "텍스트 인코더 2"),
    "clip_name3": ("clip3", "텍스트 인코더 3"),
    "clip_name4": ("clip4", "텍스트 인코더 4"),
    "text_encoder": ("text_encoder", "텍스트 인코더"),
    "vae_name": ("vae", "VAE"),
    "lora_name": ("lora", "LoRA"),
    "existing_lora": ("existing_lora", "기존 LoRA"),
    "config_name": ("config", "설정 파일"),
}

# 프롬프트를 실제로 "받아" 다음 노드로 넘기는 노드.
# 이름이 TextEncode 로 시작하지 않아도 (인핸서 등) 후보가 된다.
# class_type 보다 '링크가 아닌 문자열 값을 가진 prompt/text 입력' 이 더 확실한 기준이다.
_TEXT_INPUTS = ("prompt", "text", "positive")
# 샘플러 노드: seed/steps/cfg 는 여기서만 조작한다.
_SAMPLER_NODES = ("KSampler", "Sampler", "KSamplerAdvanced")
_SAMPLER_INPUTS = (
    "seed", "steps", "cfg", "denoise", "sampler_name", "scheduler",
)

# 링크를 따라가도 값을 그대로 읽을 수 있는 '상수 노드'.
# 사용자가 숫자/문자열을 직접 넣은 노드로, 계산된 값이 아니다.
_CONSTANT_NODES = frozenset((
    "PrimitiveInt", "PrimitiveFloat", "PrimitiveString",
    "PrimitiveStringMultiline", "Int", "Float", "String",
))
# 상수 노드가 값을 담는 입력 이름.
_CONSTANT_INPUTS = ("value", "string", "text")


def infer_parameters(prompt: dict) -> dict[str, ParameterSpec]:
    """parameters 맵이 없는 워크플로에서 조작할 파라미터를 찾는다.

    class_type 이름만 믿지 않고 데이터 흐름을 따라간다.
    (예: 인핸서 노드는 이름에 TextEncode 가 없어도 프롬프트를 받는다)

    Returns:
        dict[str, ParameterSpec]: 파라미터 이름 -> 정의
    """
    # 1) 프롬프트 입력 후보 모으기
    #    값이 링크(["14", 0] 형태)면 앞 노드에서 온 것이므로 후보가 아니다.
    #    GUI 프롬프트를 넣을 곳은 '문자열 값'을 실제로 가진 입력이다.
    prompt_candidates: list[tuple[str, str]] = []
    for node_id, node in prompt.items():
        inputs = node.get("inputs") or {}
        for input_name in _TEXT_INPUTS:
            if input_name not in inputs:
                continue
            if not isinstance(inputs[input_name], list):
                prompt_candidates.append((node_id, input_name))
            break

    # 2) 실제로 쓰이는 샘플러 노드 찾기
    sampler_nodes = _find_sampler_nodes(prompt)

    # 2-1) 샘플러 negative 에 '만' 연결된 노드는 프롬프트 후보에서 뺀다.
    #      positive 프롬프트가 인핸서 체인처럼 링크로 들어오면 후보가 남아 있지
    #      않은데, 그럴 때 네거티브 노드가 positive 로 잘못 잡혔다.
    #      (ERNIE 워크플로: 74 는 positive 로만, 75 는 negative 로만 연결됨)
    only_negative = (
        _sampler_sources(prompt, sampler_nodes, "negative")
        - _sampler_sources(prompt, sampler_nodes, "positive")
    )
    if only_negative:
        prompt_candidates = [
            c for c in prompt_candidates if c[0] not in only_negative
        ]

    specs: dict[str, ParameterSpec] = {}

    # 3) 프롬프트: KSampler positive 로 흘러들어가는 쪽을 우선
    if prompt_candidates:
        specs["positive"] = _pick_prompt_candidate(
            prompt, prompt_candidates, sampler_nodes
        )

    # 4) 나머지 파라미터
    for node_id, node in prompt.items():
        inputs = node.get("inputs") or {}
        is_sampler = node_id in sampler_nodes

        for input_name, value in inputs.items():
            # 모델 파일 선택은 5단계에서 따로 다룬다
            if input_name in _MODEL_INPUTS:
                continue
            # 프롬프트는 위에서 처리
            if input_name in _TEXT_INPUTS:
                continue
            # 연결(링크) 값은 건너뛴다. 단, 상수 노드로 이어진 경우
            # 그 값을 그대로 읽을 수 있으므로 조작 대상으로 남긴다.
            # (예: PrimitiveInt(123:110) -> EmptyLatentImage.width)
            if isinstance(value, list):
                if resolve_constant(prompt, value) is None:
                    continue
            if input_name == "negative_prompt":
                specs["negative"] = ParameterSpec(
                    "negative", node_id, input_name, "네거티브 프롬프트", "text"
                )
                continue
            if input_name not in _KIND_MAP:
                continue
            # seed/steps/cfg 는 샘플러 노드의 것만 조작한다
            # (인핸서에도 seed 가 있어 구분해야 한다)
            if input_name in _SAMPLER_INPUTS and not is_sampler:
                continue

            specs[input_name] = ParameterSpec(
                input_name, node_id, input_name, None, _KIND_MAP[input_name]
            )

    # 5) 모델 선택도 GUI 로 노출
    #    같은 종류 로더가 여럿이면 실제로 쓰이는 것을 고른다. (B18)
    for input_name in _MODEL_INPUTS:
        values = {
            node_id: (node.get("inputs") or {}).get(input_name)
            for node_id, node in prompt.items()
            if input_name in (node.get("inputs") or {})
        }
        # 링크로 물린 값은 고를 수 없다.
        candidates = [
            nid for nid, v in values.items() if not isinstance(v, list)
        ]
        if not candidates:
            continue
        # 이름이 비어 있는 로더는 고를 것이 없다. 값이 있는 것이 있으면 밀어낸다.
        filled = [nid for nid in candidates if values[nid]]
        candidates = filled or candidates
        node_id = _pick_loader(candidates, prompt, sampler_nodes)
        key, label = _MODEL_LABELS[input_name]
        specs[key] = ParameterSpec(
            key, node_id, input_name, label,
            f"model:{_MODEL_FOLDERS[input_name]}",
        )

    # 5-2) 입력 이름만으로는 폴더를 알 수 없는 경우 (노드 종류로 구분)
    for node_class, (input_name, folder) in _MODEL_FOLDERS_BY_NODE.items():
        key, label = _NODE_LABELS[node_class]
        candidates = [
            node_id for node_id, node in prompt.items()
            if node.get("class_type") == node_class
            and not isinstance((node.get("inputs") or {}).get(input_name), list)
            and (node.get("inputs") or {}).get(input_name)
        ]
        if not candidates:
            continue
        node_id = _pick_loader(candidates, prompt, sampler_nodes)
        specs[key] = ParameterSpec(
            key, node_id, input_name, label, f"model:{folder}"
        )
    return specs


def _upstream(node_id: str, prompt: dict) -> list[str]:
    """node_id 의 입력으로 연결된(값만 읽어오는) 노드 목록."""
    result = []
    for value in (prompt.get(node_id, {}).get("inputs") or {}).values():
        if (isinstance(value, list) and len(value) == 2
                and isinstance(value[0], str) and value[0] in prompt):
            result.append(value[0])
    return result


def _sampler_sources(prompt: dict, sampler_nodes: set[str], name: str) -> set[str]:
    """샘플러의 name 입력에 직접 연결된 노드 ID 집합."""
    result: set[str] = set()
    for node_id in sampler_nodes:
        value = ((prompt.get(node_id) or {}).get("inputs") or {}).get(name)
        if (isinstance(value, list) and len(value) == 2
                and isinstance(value[0], str) and value[0] in prompt):
            result.add(value[0])
    return result


def resolve_constant(prompt: dict, value: Any, depth: int = 4) -> Any:
    """링크(["12", 0] 형태)를 따라가 상수 노드가 담은 값을 읽는다.

    ERNIE 워크플로는 크기를 PrimitiveInt 로 빼내 둔다.
    (EmptyLatentImage.width = ["123:110", 0]) 링크를 그냥 건너뛰면
    해상도를 전혀 못 읽는다. 반대로 아무 값이나 추정하면 안 되므로
    '사용자가 직접 넣은 상수 노드' 에 연결된 경우에만 읽는다.
    나머지(계산된 값)는 None 을 돌려 호출자가 건너뛴다.
    """
    for _ in range(depth):
        if not isinstance(value, list) or len(value) != 2:
            return None
        node = prompt.get(value[0])
        if not isinstance(node, dict):
            return None
        if node.get("class_type") not in _CONSTANT_NODES:
            return None
        inputs = node.get("inputs") or {}
        for name in _CONSTANT_INPUTS:
            if name not in inputs:
                continue
            inner = inputs[name]
            if not isinstance(inner, list):
                return inner
            # 상수 노드끼리 연결돼 있으면 그 노드를 계속 따라간다.
            value = inner
            break
        else:
            return None
    return None


def _find_sampler_nodes(prompt: dict) -> set[str]:
    """실제로 쓰이는 샘플러 노드를 찾는다.

    이름이 KSampler 계열인지와, 출력이 SaveImage 쪽으로 흘러가는지를
    함께 확인해 쓰이지 않는 샘플러(예: 워크플로에 묵혀 있는 노드)를 배제한다.
    """
    by_class = {
        nid for nid, node in prompt.items()
        if any(node.get("class_type", "").startswith(p) for p in _SAMPLER_NODES)
    }
    if not by_class:
        return by_class

    sinks = {
        nid for nid, node in prompt.items()
        if node.get("class_type", "") in ("SaveImage", "PreviewImage")
    }
    if not sinks:
        return by_class

    # SaveImage 에서 거슬러 올라가 만나는 샘플러를 찾는다.
    found: set[str] = set()
    stack = list(sinks)
    seen: set[str] = set()
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        stack.extend(_upstream(nid, prompt))
        if nid in by_class:
            found.add(nid)
    return found or by_class


def _downstream_index(prompt: dict) -> dict[str, list[str]]:
    """노드 ID -> 그 노드의 출력을 받는 노드 목록.

    API 형식에는 '입력'만 적혀 있어서 반대 방향을 만들어야 한다.
    _upstream( SaveImage ) 로 샘플러를 찾는 것과는 반대 방향이다.
    """
    result: dict[str, list[str]] = {}
    for node_id, node in (prompt or {}).items():
        for value in (node.get("inputs") or {}).values():
            if (isinstance(value, list) and len(value) == 2
                    and isinstance(value[0], str) and value[0] != node_id):
                result.setdefault(value[0], []).append(node_id)
    return result


def _distance_to_sampler(node_id: str, forward: dict[str, list[str]],
                         sampler_nodes: set[str], limit: int = 8) -> int:
    """후보에서 샘플러까지 내려가는 최단 경로 길이. 닿지 않으면 99.

    회귀 근거: 예전에는 _upstream( 후보 ) 로 입구를 따라 올라갔다.
    후보에서 입구를 따라가면 샘플러로 갈 수 없어 늘 99 가 났고,
    '실제로 쓰이는 노드'를 고르는 기능이 사실은 동작하지 않았다.
    후보가 하나뿐인 워크플로에서만 문제가 드러나지 않았다.

    예: LoRA 체인 1 -> 5 -> 6 -> 7 -> KSampler(9) 에서 7 의 거리는 1,
    5 는 3 이다. 끝에 붙은 LoRA 가 실제로 쓰이는 것이다.
    """
    seen = {node_id}
    stack = [(node_id, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth > limit:
            continue
        if cur in sampler_nodes and cur != node_id:
            return depth
        for nxt in forward.get(cur, ()):
            if nxt in seen:
                continue
            seen.add(nxt)
            stack.append((nxt, depth + 1))
    return 99


def _pick_prompt_candidate(
    prompt: dict,
    candidates: list[tuple[str, str]],
    sampler_nodes: set[str],
) -> ParameterSpec:
    """프롬프트 입력 후보 중 사용할 것을 고른다.

    KSampler 쪽으로 직접 연결된 후보가 가장 확실하다.
    예: 인핸서(14) -> TextEncode(4) -> KSampler(6) 구조라면 '14' 를 고른다.
    """
    forward = _downstream_index(prompt)
    node_id, input_name = min(
        candidates,
        key=lambda c: _distance_to_sampler(c[0], forward, sampler_nodes),
    )
    return ParameterSpec("positive", node_id, input_name, "프롬프트", "text")


def _pick_loader(candidates: list[str], prompt: dict,
                 sampler_nodes: set[str]) -> str:
    """같은 종류 로더가 여럿이면 실제로 쓰이는 것을 고른다.

    회귀 근거: CLIP 로더를 specs["clip"] 에 덮어쓰면서 '나중 노드가 승' 이었다.
    CLIP 로더가 둘이면(본용 + 인핸서용) 인핸서가 남으면
    실제로 그림을 만드는 본용 CLIP 을 고를 수단이 사라졌다.

    실제로 쓰이는 로더는 샘플러로 흘러 들어간다. 거리가 가까운 순으로 고르고,
    아무 데도 연결 안 된 로더는 99 로 밀려 끝에 선다.
    """
    if len(candidates) == 1:
        return candidates[0]
    forward = _downstream_index(prompt)
    return min(
        candidates,
        key=lambda nid: _distance_to_sampler(nid, forward, sampler_nodes),
    )