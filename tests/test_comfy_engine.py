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
from app.comfy.config import ComfyUIConfig


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


def test_metadata_records_actual_sampler(engine, fake_comfy):
    """메타데이터의 sampler/scheduler 가 기본값이 아니라 실제 값이다.

    회귀 방지: OutputMetadata 의 기본 sampler 는 "euler_a" 라서,
    실제 전송값을 기록하지 않으면 어떤 samplers 를 골라도 이 값이 남는다.
    """
    fake_comfy["images"] = [{"filename": "a.png", "subfolder": ""}]
    req = engine.build_request(
        prompt="x",
        extra={"sampler_name": "dpmpp_2m", "scheduler": "karras"},
    )
    result = engine.generate(req)
    assert result.success is True, result.error
    assert result.metadata["sampler"] == "dpmpp_2m"
    assert result.metadata["scheduler"] == "karras"


def test_metadata_reads_applied_payload_not_request(engine, fake_comfy):
    """메타데이터는 요청값이 아니라 전송된 payload 기준이다."""
    fake_comfy["images"] = [{"filename": "a.png", "subfolder": ""}]
    req = engine.build_request(prompt="고양이", width=256, height=384, steps=7)
    result = engine.generate(req)
    assert result.metadata["prompt"] == "고양이"
    assert result.metadata["width"] == 256
    assert result.metadata["height"] == 384
    assert result.metadata["steps"] == 7


def test_session_metadata_matches_output(engine, fake_comfy):
    """세션 기록과 출력 메타데이터의 값이 일치한다."""
    import json as _json

    fake_comfy["images"] = [{"filename": "a.png", "subfolder": ""}]
    engine.generate(
        engine.build_request(prompt="강아지", extra={"sampler_name": "heun"})
    )

    output_json = sorted(engine.outputs.outputs_root.rglob("*.json"))
    out = _json.loads(output_json[0].read_text(encoding="utf-8"))
    session = _json.loads(
        (engine.sessions.list_sessions()[0] / "session.json").read_text(
            encoding="utf-8"
        )
    )
    assert out["sampler"] == "heun"
    assert session["sampler"] == "heun"
    assert session["original_prompt"] == "강아지"


def test_session_metadata_roundtrip_preserves_sampler(engine, fake_comfy):
    """세션을 다시 읽어도 sampler/scheduler 가 유지된다.

    회귀 방지: 재생성 기능이 이 값으로 드롭다운을 되돌린다.
    """
    import json as _json

    fake_comfy["images"] = [{"filename": "a.png", "subfolder": ""}]
    engine.generate(
        engine.build_request(prompt="x", extra={"sampler_name": "lms"})
    )

    session_dir = engine.sessions.list_sessions()[0]
    data = _json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    assert data["sampler"] == "lms"
    assert data["image_model"] == "테스트 워크플로"


def test_session_records_workflow_name_not_path(engine, fake_comfy):
    """세션에는 워크플로 이름이 기록된다 (모델 경로가 아니다).

    재생성이 이 이름으로 드롭다운을 찾으므로 이름이어야 한다.
    """
    import json as _json

    fake_comfy["images"] = [{"filename": "a.png", "subfolder": ""}]
    engine.generate(engine.build_request(prompt="x"))

    session_dir = engine.sessions.list_sessions()[0]
    data = _json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    assert data["image_model"] == engine.active_workflow.name
    assert not data["image_model"].endswith(".json")


# --- 파라미터 키와 입력 이름의 불일치 (회귀 방지) ---------------------


def test_sampler_key_may_differ_from_comfy_input_name(engine):
    """parameters 키가 ComfyUI 입력 이름과 달라도 주입돼야 한다.

    회귀 방지: 워크플로는 "sampler" 로 정의하지만 KSampler 입력은
    "sampler_name" 이다. 키 이름으로 조회하면 조용히 실패한다.
    """
    params = engine.active_workflow.parameters
    assert "sampler_name" in params, "자동 추론이 sampler_name 을 찾아야 한다"

    by_input = {spec.input: key for key, spec in params.items()}
    assert by_input["sampler_name"] == "sampler_name"
    assert by_input["scheduler"] == "scheduler"


def test_explicit_sampler_key_resolves_via_input_name(workflow_dir: Path):
    """사용자가 "sampler" 로 정의해도 입력 이름으로 찾아서 주입한다."""
    import json as _json

    path = workflow_dir / "test-wf.json"
    data = _json.loads(path.read_text(encoding="utf-8"))
    data["parameters"] = {
        "sampler": {"node": "6", "input": "sampler_name", "kind": "combo"},
        "scheduler": {"node": "6", "input": "scheduler", "kind": "combo"},
    }
    path.write_text(_json.dumps(data), encoding="utf-8")

    eng = GeurimGyeolEngine(workflow_dir.parent)
    eng.refresh_workflows()
    req = eng.build_request(
        prompt="x", extra={"sampler": "dpmpp_2m", "scheduler": "karras"}
    )
    _, payload = eng._payload(req)

    assert payload["6"]["inputs"]["sampler_name"] == "dpmpp_2m"
    assert payload["6"]["inputs"]["scheduler"] == "karras"


# --- ComfyUI 자동 실행 ------------------------------------------------


def test_launch_argv_adds_api_and_port():
    """launch_command 에 --api 와 --port 가 자동으로 붙는다."""
    cfg = ComfyUIConfig(launch_command="python main.py", port=8188)
    argv = cfg.build_launch_argv()
    assert argv[:2] == ["python", "main.py"]
    assert "--api" in argv
    assert argv[argv.index("--port") + 1] == "8188"


def test_launch_argv_keeps_explicit_flags():
    """이미 --api 와 --port 가 있으면 중복해서 붙이지 않는다."""
    cfg = ComfyUIConfig(
        launch_command="python main.py --api --port 9999", port=8188
    )
    argv = cfg.build_launch_argv()
    assert argv.count("--api") == 1
    assert argv.count("--port") == 1
    assert argv[argv.index("--port") + 1] == "9999"


def test_launch_argv_handles_path_with_spaces():
    """공백이 포함된 경로를 깨뜨리지 않는다 (따옴표로 감싼 경우)."""
    cfg = ComfyUIConfig(
        launch_command='"C:\\Program Files\\ComfyUI\\python.exe" main.py'
    )
    argv = cfg.build_launch_argv()
    assert argv[0] == "C:\\Program Files\\ComfyUI\\python.exe"
    assert argv[1] == "main.py"


def test_launch_argv_empty_when_not_configured():
    """launch_command 가 비어 있으면 실행할 것이 없다."""
    assert ComfyUIConfig(launch_command="").build_launch_argv() == []
    assert ComfyUIConfig(launch_command="   ").build_launch_argv() == []


def test_launch_returns_none_without_command():
    """실행 명령이 없으면 None 을 돌려주고 예외를 내지 않는다."""
    assert ComfyUIConfig(launch_command="").launch() is None


def test_launch_returns_none_on_bad_working_dir():
    """launch_working_dir 가 없으면 실행하지 않는다."""
    cfg = ComfyUIConfig(
        launch_command="python main.py",
        launch_working_dir="C:\\없는\\폴더",
    )
    assert cfg.launch() is None


def test_refresh_status_launches_when_configured(workflow_dir, monkeypatch):
    """오프라인 + auto_launch 면 실행을 시도하고 성공 시 온라인이 된다."""
    from app.comfy.config import ComfyUIConfig

    eng = GeurimGyeolEngine(workflow_dir.parent)
    eng.config = ComfyUIConfig(
        auto_launch=True, launch_command="python main.py", launch_wait_seconds=5
    )

    launched = []

    class FakeProc:
        pid = 4242
        returncode = None

        def poll(self):
            return None

        def terminate(self):
            pass

    def fake_launch(self, logger=None):
        launched.append(True)
        return FakeProc()

    monkeypatch.setattr(
        "app.comfy.config.ComfyUIConfig.launch", fake_launch, raising=True
    )

    calls = {"n": 0}

    async def fake_info(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("offline")
        return SystemInfo(online=True, vram_total_gb=8.0, vram_free_gb=4.0)

    monkeypatch.setattr(
        "app.comfy.client.ComfyClient.get_system_info", fake_info
    )

    info = eng.refresh_status()
    assert info.online is True
    assert launched, "launch 가 호출되어야 한다"
    eng.stop_launched()


def test_refresh_status_does_not_launch_when_disabled(
    workflow_dir, monkeypatch
):
    """auto_launch 가 꺼져 있으면 아무것도 실행하지 않는다."""
    eng = GeurimGyeolEngine(workflow_dir.parent)
    eng.config.auto_launch = False

    async def offline(self):
        raise RuntimeError("offline")

    monkeypatch.setattr(
        "app.comfy.client.ComfyClient.get_system_info", offline, raising=True
    )

    def never(self, logger=None):
        raise AssertionError("실행되면 안 됩니다")

    monkeypatch.setattr(
        "app.comfy.config.ComfyUIConfig.launch", never, raising=True
    )

    info = eng.refresh_status()
    assert info.online is False


def test_refresh_status_can_skip_launch(workflow_dir, monkeypatch):
    """allow_launch=False 면 조회만 하고 실행하지 않는다."""
    eng = GeurimGyeolEngine(workflow_dir.parent)
    eng.config.auto_launch = True

    def never(self, logger=None):
        raise AssertionError("실행되면 안 됩니다")

    monkeypatch.setattr(
        "app.comfy.config.ComfyUIConfig.launch", never, raising=True
    )

    async def offline(self):
        raise RuntimeError("offline")

    monkeypatch.setattr(
        "app.comfy.client.ComfyClient.get_system_info", offline, raising=True
    )

    assert eng.refresh_status(allow_launch=False).online is False


def test_stop_launched_only_stops_own_process(workflow_dir):
    """사용자가 직접 실행한 ComfyUI 는 건드리지 않는다."""
    eng = GeurimGyeolEngine(workflow_dir.parent)
    eng.stop_launched()  # 실행한 적 없으면 아무 일도 일어나지 않아야 한다

    class FakeProc:
        pid = 1
        terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    proc = FakeProc()
    eng._launched_process = proc
    eng.stop_launched()
    assert proc.terminated is True
    assert eng._launched_process is None


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