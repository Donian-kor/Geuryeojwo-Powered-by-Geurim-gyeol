"""엔진 facade 및 외부 의존성 제거 검증 (v0.1 §44.8, §3.1, §43)."""
import ast
from pathlib import Path

import pytest


def test_engine_facade_methods(engine):
    """§44.8의 Engine 메서드가 모두 존재한다."""
    for method in (
        "initialize", "analyze_hardware", "scan_models", "resolve_model_profile",
        "enhance_prompt", "unload_llm", "cleanup_memory", "load_image_model",
        "generate_image", "unload_image_model", "shutdown",
    ):
        assert hasattr(engine, method), f"GeurimGyeolEngine.{method} 누락"


def test_analyze_hardware_returns_info(engine):
    hw = engine.analyze_hardware()
    assert hw.device in ("cuda", "mps", "cpu")


def test_resolve_model_profile(engine, tmp_path):
    profile = engine.resolve_model_profile(tmp_path / "sdxl_base.safetensors")
    assert profile.architecture == "sdxl"


def test_enhance_prompt_without_llm(engine):
    """LLM 없이도 프롬프트를 반환한다."""
    positive, negative = engine.enhance_prompt("a rainy tokyo alley")
    assert "rainy tokyo alley" in positive


def test_no_external_dependency_imports(project_root):
    """v0.2 §3: 외부 런타임 의존 = ComfyUI.

    - 허용: httpx / websockets (ComfyUI API 클라이언트)
    - 금지: 외부 AI 서버를 직접 호출하는 클라이언트
      (requests, websocket-client, aiohttp, lmstudio 등).
      ComfyUI를 거치지 않고 다른 서버로 직접 나가지 않아야 한다.
    """
    allowed = {"httpx", "websockets", "urllib"}
    forbidden = {
        "requests", "websocket", "aiohttp", "lmstudio", "lm_studio",
        "openai", "anthropic", "replicate", "fal_client",
    }
    offenders = []
    for py_file in (project_root / "app").rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                if top in allowed:
                    continue
                if top in forbidden:
                    offenders.append(f"{py_file.name}: {name}")
    assert not offenders, f"ComfyUI 외 외부 의존성 발견: {offenders}"


def test_comfy_client_is_the_only_inference_path(project_root):
    """모델 실행 경로는 ComfyUI 클라이언트 하나뿐이다 (v0.2 §3).

    네이티브 추론 라이브러리(torch, diffusers, transformers)를 직접
    import 하면 ComfyUI를 우회해 GPU를 직접 점유하게 되므로 금지한다.
    """
    forbidden = {"torch", "diffusers", "transformers", "safetensors"}
    comfy_dir = (project_root / "app" / "comfy")
    offenders = []
    for py_file in comfy_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden:
                        offenders.append(f"{py_file.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in forbidden:
                    offenders.append(f"{py_file.name}: from {node.module}")
    assert not offenders, f"ComfyUI 모듈에 네이티브 의존성 발견: {offenders}"


def test_requirements_have_no_external_servers(project_root):
    """requirements.txt에 외부 AI 서버 관련 패키지가 없다."""
    content = (project_root / "requirements.txt").read_text(encoding="utf-8").lower()
    for banned in ("requests", "websocket-client", "markdown"):
        assert banned not in content


def test_core_modules_exist(project_root):
    """계획서의 핵심 모듈이 모두 존재한다."""
    expected = [
        "app/engine/engine.py",
        "app/engine/hardware/detector.py",
        "app/engine/llm/llama_cpp.py",
        "app/engine/prompt/engine.py",
        "app/engine/models/registry.py",
        "app/engine/models/scanner.py",
        "app/engine/memory/manager.py",
        "app/engine/image/pipeline.py",
        "app/engine/image/adapters/sd15.py",
        "app/engine/image/adapters/sdxl.py",
        "app/engine/image/adapters/sd3.py",
        "app/engine/image/adapters/flux.py",
        "app/engine/generation/controller.py",
        "app/engine/generation/task_runner.py",
        "app/engine/session/manager.py",
        "app/engine/output/manager.py",
        "app/engine/error/handler.py",
        "app/engine/validation/dry_run.py",
        "app/engine/logging/manager.py",
    ]
    missing = [p for p in expected if not (project_root / p).exists()]
    assert not missing, f"누락된 모듈: {missing}"


def test_config_files_exist(project_root):
    """설정 파일이 존재한다 (§3.4 Configuration Driven)."""
    for name in (
        "image_profiles.json", "prompt_profiles.json",
        "negative_dictionary.json", "llm_profiles.json", "user_models.json",
    ):
        assert (project_root / "config" / name).exists(), name