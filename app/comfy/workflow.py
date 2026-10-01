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


def infer_parameters(prompt: dict) -> dict[str, ParameterSpec]:
    """parameters 맵이 없는 워크플로에서 조작할 파라미터를 찾는다."""
    specs: dict[str, ParameterSpec] = {}
    for node_id, node in prompt.items():
        inputs = node.get("inputs") or {}
        class_type = node.get("class_type", "")

        for input_name, value in inputs.items():
            if isinstance(value, list) or input_name in _MODEL_INPUTS:
                continue
            if input_name == "prompt" and class_type.startswith(("TextEncode", "CLIPText")):
                specs["positive"] = ParameterSpec(
                    "positive", node_id, input_name, "프롬프트", "text"
                )
            elif input_name == "negative_prompt":
                specs["negative"] = ParameterSpec(
                    "negative", node_id, input_name, "네거티브 프롬프트", "text"
                )
            elif input_name in _KIND_MAP:
                specs[input_name] = ParameterSpec(
                    input_name, node_id, input_name, None, _KIND_MAP[input_name]
                )
    return specs