"""인퇰서 자동 주입 연동 확인 (임시 스크립트).

실행 중인 ComfyUI 에서 object_info 를 읽어, 인퇰서 노드가 없는
워크플로에 주입했을 때 '필수 입력이 전부 채워지는지' 를 검사한다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.comfy.client import SystemInfo  # noqa: E402
from app.engine.comfy_engine import (  # noqa: E402
    GeurimGyeolEngine, _enhancer_model, _find_enhancer_node, injection_target,
    injection_block_reason,
)

# SDXL 처럼 인퇰서 없는 워크플로 (CLIPTextEncode.text 하나만 문자열)
SDXL_WORKFLOW = {
    "4": {"class_type": "CLIPTextEncode", "inputs": {
        "text": "고양이", "clip": ["2", 0]}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024}},
    "6": {"class_type": "KSampler", "inputs": {
        "seed": 1, "steps": 20, "cfg": 7.0, "model": ["3", 0],
        "positive": ["4", 0], "negative": ["4", 0], "latent_image": ["5", 0],
        "sampler_name": "euler", "scheduler": "normal", "denoise": 1}},
    "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["8", 0]}},
    "8": {"class_type": "VAELoader", "inputs": {"vae_name": "v.safetensors"}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["7", 0]}},
    "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sdxl.safetensors"}},
    "3": {"class_type": "EmptyModel", "inputs": {}},
}

# Flux 처럼 인코더가 2 개인 워크플로 (주입하면 안 되는 사례)
FLUX_WORKFLOW = {
    "4": {"class_type": "CLIPTextEncodeFlux", "inputs": {
        "clip_l": "고양이", "t5xxl": "고양이", "width": 1024, "height": 1024,
        "clip": ["2", 0]}},
    "6": {"class_type": "KSampler", "inputs": {
        "seed": 1, "steps": 20, "cfg": 7.0, "positive": ["4", 0],
        "latent_image": ["5", 0]}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["6", 0]}},
}


def build_engine(*workflows: dict) -> GeurimGyeolEngine:
    tmp = Path(tempfile.mkdtemp()) / "root"
    (tmp / "workflows").mkdir(parents=True)
    for name in ("config", "outputs", "sessions"):
        (tmp / name).mkdir(exist_ok=True)
    for index, wf in enumerate(workflows):
        (tmp / "workflows" / f"wf{index}.json").write_text(
            json.dumps({"name": f"wf{index}", "prompt": wf}), encoding="utf-8"
        )
    eng = GeurimGyeolEngine(tmp)
    eng.refresh_workflows()
    eng.system_info = SystemInfo(online=True, error="")
    return eng


def check_required_inputs(node_class: str, inputs: dict) -> list[str]:
    """ComfyUI 규칙대로 필수 입력이 전부 채워졌는지 검사한다."""
    info = json.load(urllib.request.urlopen(
        f"http://127.0.0.1:8188/object_info/{node_class}", timeout=20
    ))
    required = info[node_class]["input"]["required"]
    return [name for name in required if name not in inputs]


def main() -> int:
    print("=" * 66)
    print("1) SDXL 워크플로 (인핸서 없음, text 입력 하나) → 자동 주입되어야 함")
    print("=" * 66)
    eng = build_engine(SDXL_WORKFLOW)
    eng.select_workflow("wf0")
    wf = eng.active_workflow
    print("  붙일 자리:", injection_target(wf))
    request = eng.build_request(prompt="바다 위 증기선")
    _, payload = eng._payload(request)

    injected = _find_enhancer_node(payload)
    print("  주입된 인함서 노드:", injected)
    print("  텍스트 인코더가 받은 것:", payload["4"]["inputs"]["text"])
    print("  인함서 prompt 입력:", repr(payload[injected]["inputs"]["prompt"]))
    print("  기록될 llm_model:", repr(_enhancer_model(payload)))
    missing = check_required_inputs(payload[injected]["class_type"],
                                   payload[injected]["inputs"])
    print("  비어 있는 필수 입력:", missing or "없음")

    ok_inject = (
        injected is not None
        and payload["4"]["inputs"]["text"] == [injected, 0]
        and payload[injected]["inputs"]["prompt"] == "바다 위 증기선"
        and not missing
    )

    print()
    print("=" * 66)
    print("2) Flux 워크플로 (인코더 2개) → 주입되면 안 됨")
    print("=" * 66)
    eng2 = build_engine(FLUX_WORKFLOW)
    eng2.select_workflow("wf0")
    wf2 = eng2.active_workflow
    print("  붙일 자리:", injection_target(wf2))
    _, payload2 = eng2._payload(eng2.build_request(prompt="고양이"))
    print("  주입된 인함서 노드:", _find_enhancer_node(payload2))
    ok_refuse = _find_enhancer_node(payload2) is None
    print("  (사유)", injection_block_reason(wf2))

    print()
    print("=" * 66)
    print("3) 스위치를 끄면 원본 프롬프트가 그대로 전달됨")
    print("=" * 66)
    request3 = eng.build_request(prompt="고양이", enhance_prompt=False)
    _, payload3 = eng._payload(request3)
    print("  텍스트 인코더 text:", payload3["4"]["inputs"]["text"])
    print("  인함서 노드:", _find_enhancer_node(payload3))
    ok_off = (
        payload3["4"]["inputs"]["text"] == "고양이"
        and _find_enhancer_node(payload3) is None
    )

    print()
    print("결과:", "통과" if (ok_inject and ok_refuse and ok_off) else "실패")
    return 0 if (ok_inject and ok_refuse and ok_off) else 1


if __name__ == "__main__":
    raise SystemExit(main())