"""ComfyUI 기반 엔진 v0.2 테스트.

네트워크에 의존하지 않는다.
ComfyClient 를 가짜로 대체해 워크플로 로드 → 값 주입 → 결과 저장까지
GUI 와 동일한 코드 경로를 검증한다.
"""
import asyncio
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.engine.comfy_engine import GeurimGyeolEngine
from app.comfy.client import SystemInfo


def _png_bytes(size=(64, 64), color=(200, 30, 30)) -> bytes:
    """테스트용 PNG 바이트."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def workflow_dir(tmp_path: Path) -> Path:
    """엔진 루트의 workflows/ 폴더.

    parameters 맵이 없는 워크플로를 넣어
    자동 인식 경로를 검증한다.
    """
    root = tmp_path / "root"
    wf_dir = root / "workflows"
    wf_dir.mkdir(parents=True)
    for name in ("config", "outputs", "sessions"):
        (root / name).mkdir(parents=True, exist_ok=True)

    prompt = {
        "5": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": 704, "height": 1024}},
        "6": {"class_type": "KSampler", "inputs": {
            "seed": 1, "steps": 40, "cfg": 3.0,
            "sampler_name": "euler", "scheduler": "simple",
        }},
        "14": {"class_type": "TextEncodeQwenImageEdit", "inputs": {"prompt": "PROMPT"}},
        "4": {"class_type": "TextEncodeQwenImageEdit",
              "inputs": {"negative_prompt": "NEG"}},
        "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": "test"}},
    }
    (wf_dir / "test-wf.json").write_text(
        json.dumps({"name": "테스트 워크플로", "prompt": prompt}), encoding="utf-8"
    )
    return wf_dir


@pytest.fixture
def engine(workflow_dir: Path, monkeypatch):
    """오프라인 엔진 — 네트워크를 결코 건드리지 않는다.

    generate() 는 오프라인이면 상태를 다시 조회하므로
    get_system_info 까지 막아야 실제 서버에 붙지 않는다.
    """

    async def _offline(self):
        raise AssertionError("테스트가 네트워크를 호출했습니다")

    monkeypatch.setattr(
        "app.comfy.client.ComfyClient.get_system_info", _offline, raising=True
    )
    monkeypatch.setattr(
        "app.comfy.client.ComfyClient.run", _offline, raising=True
    )

    eng = GeurimGyeolEngine(workflow_dir.parent)
    eng.refresh_workflows()
    eng.system_info = SystemInfo(online=False, error="테스트 중 (오프라인)")
    return eng


@pytest.fixture
def fake_comfy(monkeypatch):
    """ComfyUI 응답을 대체한다. online=True 로 고정."""
    state = {"images": [], "run_error": None}

    async def fake_get_system_info(self):
        return SystemInfo(
            online=True, comfyui_version="0.3", device_name="GPU",
            vram_total_gb=8.0, vram_free_gb=4.0,
        )

    async def fake_run(self, payload, on_progress=None, on_stage=None, timeout=None):
        if state["run_error"]:
            raise state["run_error"]
        if on_progress:
            on_progress(5, "제출 완료")
            on_progress(100, "완료")
        return state["images"]

    async def fake_get_image(self, filename, subfolder="", **kw):
        return _png_bytes()

    monkeypatch.setattr(
        "app.comfy.client.ComfyClient.get_system_info", fake_get_system_info
    )
    monkeypatch.setattr("app.comfy.client.ComfyClient.run", fake_run)
    monkeypatch.setattr("app.comfy.client.ComfyClient.get_image", fake_get_image)
    return state


# --- 워크플로 로드 ----------------------------------------------------


def test_parameters_are_inferred_when_missing(engine):
    """parameters 맵이 없어도 파라미터를 자동으로 인식한다."""
    wf = engine.active_workflow
    assert wf is not None, "워크플로가 로드되어야 한다"
    assert wf.name == "테스트 워크플로"
    assert set(wf.parameters) >= {
        "positive", "negative", "width", "height", "steps", "cfg", "seed"
    }


def test_output_node_is_guessed(engine):
    """SaveImage 노드가 출력 노드로 선택된다."""
    assert engine.active_workflow.output_node == "8"


def test_select_workflow_by_name(engine):
    """이름으로 워크플로를 선택할 수 있다."""
    assert engine.select_workflow("테스트 워크플로") is engine.active_workflow
    assert engine.select_workflow("없는 워크플로") is None


def test_refresh_survives_missing_workflow_dir(tmp_path: Path):
    """workflows/ 가 없어도 예외 없이 빈 목록을 반환한다."""
    eng = GeurimGyeolEngine(tmp_path)
    assert eng.refresh_workflows() == []
    assert eng.active_workflow is None


def test_invalid_workflow_json_is_skipped(engine, tmp_path: Path):
    """형식이 잘못된 워크플로는 건너뛰고 나머지를 로드한다."""
    (engine.workflow_dir / "broken.json").write_text("{", encoding="utf-8")
    loaded = engine.refresh_workflows()
    assert len(loaded) == 1, "정상 워크플로만 로드돼야 한다"


# --- 값 주입 ---------------------------------------------------------


def test_payload_injects_request_values(engine):
    """GUI 입력값이 올바른 노드에 주입된다."""
    req = engine.build_request(
        prompt="고양이", negative_prompt="흐릿", width=768, height=512,
        steps=8, cfg=5.5, seed=1234,
    )
    _, payload = engine._payload(req)

    assert payload["14"]["inputs"]["prompt"] == "고양이"
    assert payload["4"]["inputs"]["negative_prompt"] == "흐릿"
    assert payload["5"]["inputs"]["width"] == 768
    assert payload["5"]["inputs"]["height"] == 512
    assert payload["6"]["inputs"]["steps"] == 8
    assert payload["6"]["inputs"]["cfg"] == 5.5
    assert payload["6"]["inputs"]["seed"] == 1234


def test_payload_keeps_workflow_default_when_seed_is_minus_one(engine):
    """seed=-1 이면 워크플로 기본 seed 를 그대로 쓴다."""
    req = engine.build_request(prompt="x", seed=-1)
    _, payload = engine._payload(req)
    assert payload["6"]["inputs"]["seed"] == 1


def test_payload_injects_extra_values(engine):
    """extra 로 넘긴 값이 워크플로 입력에 반영된다.

    infer_parameters 는 파라미터 키를 ComfyUI 입력 이름으로 만든다
    (sampler_name, scheduler 등). 키 이름을 정확히 맞춰야 한다.
    """
    req = engine.build_request(
        prompt="고양이", extra={"sampler_name": "dpmpp_2m"}
    )
    _, payload = engine._payload(req)
    assert payload["6"]["inputs"]["sampler_name"] == "dpmpp_2m"


def test_payload_ignores_extra_key_not_in_workflow(engine):
    """워크플로에 없는 extra 키는 조용히 무시된다."""
    req = engine.build_request(prompt="고양이", extra={"없는_키": 123})
    _, payload = engine._payload(req)
    assert "없는_키" not in payload["6"]["inputs"]


def test_build_request_without_workflow_raises(tmp_path: Path):
    """워크플로가 없으면 명확한 예외를 낸다."""
    eng = GeurimGyeolEngine(tmp_path)
    with pytest.raises(RuntimeError, match="워크플로"):
        eng.build_request(prompt="x")


# --- 생성 ------------------------------------------------------------


def test_generate_fails_when_offline(engine):
    """ComfyUI 오프라인이면 이미지 없이 원인을 설명한다."""
    result = engine.generate(engine.build_request(prompt="고양이"))
    assert result.success is False
    assert result.image_path is None
    assert "ComfyUI" in result.error


def test_generate_saves_image_and_session(engine, fake_comfy):
    """성공하면 outputs/ 와 sessions/ 에 저장된다."""
    fake_comfy["images"] = [{"filename": "test_00001_.png", "subfolder": ""}]

    progress: list[tuple[int, str]] = []
    req = engine.build_request(
        prompt="고양이", width=64, height=64, steps=4, seed=77
    )
    result = engine.generate(req, on_progress=lambda p, m: progress.append((p, m)))

    assert result.success is True, result.error
    assert result.image_path.exists(), "outputs/ 에 이미지가 저장돼야 한다"
    assert result.image_path.suffix == ".png"
    assert result.metadata["seed"] == 77
    assert result.metadata["prompt"] == "고양이"
    assert result.metadata["model"] == "테스트 워크플로"
    assert result.metadata["width"] == 64

    # 진행률 콜백이 호출된다
    assert progress, "진행률 콜백이 호출돼야 한다"
    assert progress[-1][0] == 100

    # 세션에도 기록된다
    sessions = engine.sessions.list_sessions()
    assert len(sessions) == 1, "sessions/ 에 기록돼야 한다"
    assert (sessions[0] / "001.png").exists()


def test_generate_reports_empty_result(engine, fake_comfy):
    """ComfyUI 가 빈 목록을 주면 실패로 처리한다."""
    fake_comfy["images"] = []
    result = engine.generate(engine.build_request(prompt="x"))
    assert result.success is False
    assert "이미지" in result.error


def test_generate_surfaces_client_error(engine, fake_comfy):
    """ComfyUI 오류를 사용자에게 그대로 전달한다."""
    from app.comfy.client import ComfyUIError

    fake_comfy["run_error"] = ComfyUIError("노드를 찾을 수 없습니다")
    result = engine.generate(engine.build_request(prompt="x"))
    assert result.success is False
    assert "노드를 찾을 수 없습니다" in result.error


def test_generate_records_session_metadata(engine, fake_comfy):
    """세션에 프롬프트와 워크플로명이 기록된다."""
    import json as _json

    fake_comfy["images"] = [{"filename": "a.png", "subfolder": ""}]
    engine.generate(engine.build_request(prompt="고양이", seed=5))

    session = engine.sessions.list_sessions()[0]
    data = _json.loads((session / "session.json").read_text(encoding="utf-8"))
    assert data["original_prompt"] == "고양이"
    assert data["image_model"] == "테스트 워크플로"
    assert data["seed"] == 5


# --- 이벤트 루프 재사용 (회귀 방지) ----------------------------------


def test_repeated_calls_work_across_event_loops():
    """asyncio.run 을 반복 호출해도 클라이언트가 재사용 가능해야 한다.

    회귀 방지: httpx 클라이언트가 닫힌 루프에 묶여 있으면
    두 번째 호출부터 "Event loop is closed" 로 실패한다.
    """
    from app.comfy.client import ComfyClient

    client = ComfyClient()
    first = client._ensure_http()
    asyncio.run(client.close())

    async def _touch():
        return client._ensure_http()

    second = asyncio.run(_touch())
    assert second is not first, "루프가 바뀌면 새 클라이언트가 만들어져야 한다"
    assert not second.is_closed