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
            if not isinstance(value, list):
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
    """워크플로 폴더의 JSON 목록."""
    if not directory.exists():
        return []
    return sorted(p for p in directory.glob("*.json") if p.is_file())


# 자동 추출 대상 파라미터와 위젯 종류
_KIND_MAP = {
    "seed": "int", "steps": "int", "width": "int", "height": "int",
    "batch_size": "int", "resolution": "int", "max_output_chars": "int",
    "cfg": "float", "denoise": "float", "guidance": "float",
    "strength_model": "float", "strength_clip": "float",
    "sampler_name": "combo", "scheduler": "combo",
}
_MODEL_INPUTS = ("unet_name", "ckpt_name", "clip_name", "vae_name", "lora_name")
_MODEL_FOLDERS = {
    "unet_name": "diffusion_models", "ckpt_name": "checkpoints",
    "clip_name": "text_encoders", "vae_name": "vae", "lora_name": "loras",
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
            # 연결(링크) 값과 모델 파일 선택은 제외
            if isinstance(value, list) or input_name in _MODEL_INPUTS:
                continue
            # 프롬프트는 위에서 처리
            if input_name in _TEXT_INPUTS:
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
    for node_id, node in prompt.items():
        for input_name, value in (node.get("inputs") or {}).items():
            if isinstance(value, list) or input_name not in _MODEL_INPUTS:
                continue
            key, label = {
                "lora_name": ("lora", "LoRA"),
                "unet_name": ("unet", "확산 모델"),
                "ckpt_name": ("checkpoint", "체크포인트"),
                "clip_name": ("clip", "텍스트 인코더"),
                "vae_name": ("vae", "VAE"),
            }[input_name]
            specs[key] = ParameterSpec(
                key, node_id, input_name, label,
                f"model:{_MODEL_FOLDERS[input_name]}",
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


def _pick_prompt_candidate(
    prompt: dict,
    candidates: list[tuple[str, str]],
    sampler_nodes: set[str],
) -> ParameterSpec:
    """프롬프트 입력 후보 중 사용할 것을 고른다.

    KSampler 쪽으로 직접 연결된 후보가 가장 확실하다.
    예: 인핸서(14) -> TextEncode(4) -> KSampler(6) 구조라면 '14' 를 고른다.
    """
    def distance_to_sampler(node_id: str, limit: int = 8) -> int:
        """KSampler 로 향하는 최단 경로 길이."""
        seen: set[str] = set()
        stack = [(node_id, 0)]
        while stack:
            cur, depth = stack.pop()
            if cur in seen or depth > limit:
                continue
            seen.add(cur)
            if cur in sampler_nodes and cur != node_id:
                return depth
            for nxt in _upstream(cur, prompt):
                stack.append((nxt, depth + 1))
        return 99

    node_id, input_name = min(
        candidates, key=lambda c: distance_to_sampler(c[0])
    )
    return ParameterSpec("positive", node_id, input_name, "프롬프트", "text")