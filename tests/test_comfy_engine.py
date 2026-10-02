"""ComfyUI 기반 엔진 v0.2 테스트.

네트워크에 의존하지 않는다.
ComfyClient 를 가짜로 대체해 워크플로 로드 → 값 주입 → 결과 저장까지
GUI 와 동일한 코드 경로를 검증한다.
"""
import asyncio
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from app.engine.comfy_engine import GeurimGyeolEngine, _is_enhancer
from app.comfy.client import ComfyClient, SystemInfo
from app.comfy.config import ComfyUIConfig
from app.comfy.workflow import infer_parameters


# --- 목록 조회와 캐시 -------------------------------------------------
# 회귀 근거: /object_info 전체 응답이 노드 1000종을 넘어 2.4MB 다.
# 가져오기 창에서 파일을 몇 개 열 때마다 다시 받으면 낭비가 커서
# 짧은 시간 동안은 재사용한다. 방금 노드를 설치했을 수 있어 TTL 은 짧다.


class _StubClient:
    """목록 조회만 흉내내는 ComfyClient 대체."""

    def __init__(self, clip=None, nodes=None, fail=False):
        self.clip = ["qwen_image", "flux2"] if clip is None else clip
        self.nodes = {"KSampler": {}, "SaveImage": {}} if nodes is None else nodes
        self.fail = fail
        self.calls = {"clip": 0, "nodes": 0}

    async def get_clip_types(self):
        self.calls["clip"] += 1
        if self.fail:
            raise RuntimeError("서버 꺼짐")
        return list(self.clip)

    async def get_object_info(self, node_class=None):
        self.calls["nodes"] += 1
        if self.fail:
            raise RuntimeError("서버 꺼짐")
        return dict(self.nodes)


def _engine(tmp_path, stub) -> GeurimGyeolEngine:
    engine = GeurimGyeolEngine(tmp_path)
    engine.client = stub
    return engine


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.mark.parametrize("spec,expected", [
    ([["qwen_image", "flux2"], {}], ["qwen_image", "flux2"]),   # 신버전
    (["COMBO", {"options": ["lumina2"]}], ["lumina2"]),          # T8 팩 형태
    (["STRING", {}], []),                                         # 자유 입력
    (None, []),
])
def test_get_clip_types_handles_definition_shapes(spec, expected, monkeypatch):
    """ComfyUI 의 입력 정의 형태가 두 가지다. 둘 다 읽어야 한다."""
    payload = {"CLIPLoader": {"input": {"required": {"type": spec}}}}
    client = ComfyClient(ComfyUIConfig())

    async def fake_get(path, timeout=30):
        return _FakeResponse(payload)

    monkeypatch.setattr(client, "_get", fake_get)
    assert asyncio.run(client.get_clip_types()) == expected


def test_get_clip_types_reads_only_one_node(monkeypatch):
    """전체(/object_info)가 아니라 CLIPLoader 하나만 조회해야 한다."""
    seen = []
    client = ComfyClient(ComfyUIConfig())

    async def fake_get(path, timeout=30):
        seen.append(path)
        return _FakeResponse(
            {"CLIPLoader": {"input": {"required": {"type": [["a"], {}]}}}}
        )

    monkeypatch.setattr(client, "_get", fake_get)
    asyncio.run(client.get_clip_types())
    assert seen == ["/object_info/CLIPLoader"]


def test_clip_types_are_cached(tmp_path):
    stub = _StubClient()
    engine = _engine(tmp_path, stub)
    first = engine.clip_types()
    second = engine.clip_types()
    assert first == second == ["qwen_image", "flux2"]
    assert stub.calls["clip"] == 1, "캐시가 통하지 않았다"


def test_clip_types_cache_expires(tmp_path):
    stub = _StubClient()
    engine = _engine(tmp_path, stub)
    engine.clip_types()
    engine._clip_types_at = 0.0        # 유효 시간 경과
    engine.clip_types()
    assert stub.calls["clip"] == 2


def test_clip_types_returns_fresh_list(tmp_path):
    """호출자가 바꿔도 캐시가 오염되지 않게 새 리스트를 준다."""
    stub = _StubClient()
    engine = _engine(tmp_path, stub)
    result = engine.clip_types()
    result.append("없는 타입")
    assert "없는 타입" not in engine.clip_types()


def test_clip_types_failure_returns_empty(tmp_path):
    """조회 실패는 빈 목록. 모르는 걸 정상이라고 말하지 않는다."""
    engine = _engine(tmp_path, _StubClient(fail=True))
    assert engine.clip_types() == []


def test_node_types_are_cached(tmp_path):
    stub = _StubClient()
    engine = _engine(tmp_path, stub)
    assert engine.node_types() == {"KSampler", "SaveImage"}
    engine.node_types()
    assert stub.calls["nodes"] == 1, "2.4MB 를 매번 다시 받았다"


def test_node_types_cache_expires(tmp_path):
    stub = _StubClient()
    engine = _engine(tmp_path, stub)
    engine.node_types()
    engine._node_types_at = 0.0
    engine.node_types()
    assert stub.calls["nodes"] == 2


def test_node_types_failure_does_not_poison_cache(tmp_path):
    """실패하면 빈 집합(판단 보류). 예전 성공값을 지우지 않는다."""
    stub = _StubClient()
    engine = _engine(tmp_path, stub)
    assert engine.node_types() == {"KSampler", "SaveImage"}
    stub.fail = True
    engine._node_types_at = 0.0
    assert engine.node_types() == set()


def _png_bytes(size=(64, 64), color=(200, 30, 30)) -> bytes:
    """테스트용 PNG 바이트."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


# --- 인핸서 / LoRA 인식 회귀 테스트 ------------------------------
# 근거: 인핸서 노드(QwenImage21PromptEnhancerT8)에는 이름에 TextEncode 가
# 없고, 인핸서에도 seed 가 있어 KSampler 와 구분해야 한다.

_ENHANCER_WORKFLOW = {
    "1": {"class_type": "UNETLoader",
          "inputs": {"unet_name": "u.safetensors", "weight_dtype": "default"}},
    "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "c.safetensors"}},
    "3": {"class_type": "VAELoader", "inputs": {"vae_name": "v.safetensors"}},
    "4": {"class_type": "TextEncodeQwenImage21", "inputs": {
        "prompt": ["14", 0], "negative_prompt": "NEG", "resolution": 1024,
        "clip": ["2", 0]}},
    "5": {"class_type": "EmptyLatentImage",
          "inputs": {"width": 704, "height": 1024, "batch_size": 1}},
    "6": {"class_type": "KSampler", "inputs": {
        "seed": 137011622967013, "steps": 40, "cfg": 3,
        "sampler_name": "euler", "scheduler": "simple", "denoise": 1,
        "model": ["16", 0], "positive": ["4", 0],
        "negative": ["4", 1], "latent_image": ["5", 0]}},
    "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
    "8": {"class_type": "SaveImage",
          "inputs": {"filename_prefix": "p", "images": ["7", 0]}},
    "14": {"class_type": "QwenImage21PromptEnhancerT8", "inputs": {
        "prompt": "", "input_mode": "텍스트-이미지", "max_output_chars": 0,
        "wh_ratio": "9:16", "seed": 607952190216878,
        "local_model": "pe.gguf"}},
    "15": {"class_type": "T8ShowText", "inputs": {"text": ["14", 0]}},
    "16": {"class_type": "LoraLoaderModelOnly", "inputs": {
        "lora_name": "l.safetensors", "strength_model": 1, "model": ["1", 0]}},
}


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
def enhancer_engine(tmp_path: Path, monkeypatch):
    """인핸서 + LoRA 워크플로를 가진 엔진.

    workflow_dir 픽스처를 재사용하지 않는다 — 기존 테스트가
    '워크플로가 하나뿐' 이라고 전제하기 때문이다.
    """

    async def _offline(self):
        raise AssertionError("테스트가 네트워크를 호출했습니다")

    monkeypatch.setattr(
        "app.comfy.client.ComfyClient.get_system_info", _offline, raising=True
    )
    monkeypatch.setattr("app.comfy.client.ComfyClient.run", _offline, raising=True)

    root = tmp_path / "enhancer_root"
    wf_dir = root / "workflows"
    wf_dir.mkdir(parents=True)
    for name in ("config", "outputs", "sessions"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (wf_dir / "enhancer-wf.json").write_text(
        json.dumps({"name": "인핸서 워크플로", "prompt": _ENHANCER_WORKFLOW}),
        encoding="utf-8",
    )

    eng = GeurimGyeolEngine(root)
    eng.refresh_workflows()
    eng.select_workflow("enhancer-wf")
    eng.system_info = SystemInfo(online=False, error="테스트 중 (오프라인)")
    return eng


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
    state = {"images": [], "run_error": None, "history": {}}

    async def fake_get_system_info(self):
        return SystemInfo(
            online=True, comfyui_version="0.3", device_name="GPU",
            vram_total_gb=8.0, vram_free_gb=4.0,
        )

    async def fake_run(
        self, payload, on_progress=None, on_stage=None, timeout=None,
        run_details=False,
    ):
        if state["run_error"]:
            raise state["run_error"]
        if on_progress:
            on_progress(5, "제출 완료")
            on_progress(100, "완료")
        if run_details:
            return state["images"], state["history"], "p-test"
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
def test_prompt_targets_enhancer_node_not_linked_node():
    """프롬프트는 인핸서(문자열 입력)에 들어가야 한다.

    회귀 근거: TextEncode(4)의 prompt 는 ["14", 0] 링크라 값을 넣어도
    효과가 없고, 인핸서(14)의 문자열 prompt 여야 LLM 이 받는다.
    """
    specs = infer_parameters(_ENHANCER_WORKFLOW)
    assert "positive" in specs
    positive = specs["positive"]
    assert positive.node == "14"
    assert positive.input == "prompt"
    # TextEncode(4) 의 prompt 는 ["14", 0] 링크라 값을 넣어도 효과가 없다
    assert isinstance(_ENHANCER_WORKFLOW["4"]["inputs"]["prompt"], list)


def test_seed_comes_from_ksampler_not_enhancer():
    """seed 는 KSampler 것만 조작 대상이다.

    회귀 근거: 인핸서(14)에도 seed 가 있어 잘못 잡으면 재현성이 깨진다.
    """
    specs = infer_parameters(_ENHANCER_WORKFLOW)
    assert specs["seed"].node == "6"
    for sampler_input in ("steps", "cfg", "denoise",
                          "sampler_name", "scheduler"):
        assert specs[sampler_input].node == "6", sampler_input


def _select_enhancer(engine) -> None:
    """인핸서 워크플로를 이름으로 선택한다 (파일 나열 순서 의존 제거)."""
    engine.select_workflow("enhancer-wf")


def test_extract_text_outputs_reads_enhancer_result():
    """history 에서 인핸서 노드의 텍스트 출력을 읽는다 (B4).

    실측 구조: GET /history/{id} → {prompt_id: {outputs: {노드id: {...}}}}
    T8ShowText 는 {"text": "다듬어진 프롬프트"} 를 남긴다.
    """
    from app.comfy.client import extract_text_outputs

    history = {
        "p-1": {"outputs": {
            "8": {"images": [{"filename": "a.png"}]},
            "14": {"text": ["고양이 한 마리가 나무 테이블에 앉아 있고, "
                            "햇살이 비스듬히 들어온다, 고양이, 4k"]},
        }}
    }
    texts = extract_text_outputs(history, "p-1")
    assert texts["14"].startswith("고양이 한 마리가")
    assert "8" not in texts, "이미지 노드는 텍스트 출력이 아니다"


def test_metadata_records_original_and_enhanced_prompt_separately(tmp_path):
    """원본 프롬프트와 최종 프롬프트가 구분되어 저장된다 (§12 시드 재현성).

    회귀: 둘 다 원문이라 기록된 값으로 같은 그림을 다시 만들 수 없었다.
    """
    import json as _json

    from app.engine.output.manager import OutputMetadata

    meta = OutputMetadata(
        seed=42, model="wf", prompt="최종 다듬어진 프롬프트",
        original_prompt="고양이", negative_prompt="", width=8, height=8,
        steps=4, cfg=4.0,
    )
    data = meta.to_dict()
    assert data["prompt"] == "최종 다듬어진 프롬프트"
    assert data["original_prompt"] == "고양이"

    roundtrip = OutputMetadata.from_dict(_json.loads(_json.dumps(data, ensure_ascii=False)))
    assert roundtrip.prompt == "최종 다듬어진 프롬프트"
    assert roundtrip.original_prompt == "고양이"


def test_bypass_removes_enhancer_node_and_all_references(enhancer_engine):
    """인핸서 OFF 시 노드 14 가 payload 에서 사라지고 참조도 모두 끊긴다.

    회귀: TextEncode(4) 의 링크만 풀면 T8ShowText(15) 가 ["14", 0] 을
    계속 참조해 ComfyUI 가 LLM 을 실행한다.
    """
    engine = enhancer_engine
    request = engine.build_request(
        prompt="고양이", negative_prompt="흐릿",
        width=640, height=480, steps=8, cfg=4.0, seed=7,
        enhance_prompt=False,
    )
    _, payload = engine._payload(request)

    assert "14" not in payload, "인핸서 노드가 payload 에 남아 있다"

    # 어떤 노드도 인핸서를 참조하지 않아야 한다 (dangling link 금지)
    for node_id, node in payload.items():
        for input_name, value in (node.get("inputs") or {}).items():
            if isinstance(value, list) and len(value) == 2:
                assert value[0] != "14", (
                    f"노드 {node_id}.{input_name} 이 제거된 인핸서를 참조한다"
                )

    # TextEncode 는 원본 프롬프트를 직접 받아야 한다
    assert payload["4"]["inputs"]["prompt"] == "고양이"


def test_bypass_does_not_accumulate_state_in_workflow(enhancer_engine):
    """생성할 때마다 워크플로 객체에 상태가 쌓이지 않는다.

    회귀: wf.meta.setdefault(...).append(...) 는 wf 가 재사용되므로
    3회 실행 → ['14','14','14'] 이 남았다.
    """
    engine = enhancer_engine
    request = engine.build_request(
        prompt="p", width=64, height=64, steps=4, cfg=4.0, seed=1,
        enhance_prompt=False,
    )
    for _ in range(3):
        _, payload = engine._payload(request)
        assert "14" not in payload

    assert engine.active_workflow.meta == {}, (
        f"우회 사실이 워크플로에 누적된다: {engine.active_workflow.meta}"
    )


def test_system_info_describe_survives_missing_vram_free():
    """vram_total_gb 은 있고 vram_free_gb 이 None 이어도 예외가 나지 않는다.

    회귀: `f"{self.vram_used_gb:.1f}"` 로 None 을 포맷하면
    TypeError: unsupported format string passed to 'NoneType'
    """
    from app.comfy.client import SystemInfo

    info = SystemInfo(
        online=True,
        comfyui_version="0.3.40",
        device_name="NVIDIA GeForce RTX 5080",
        vram_total_gb=16.0,
        vram_free_gb=None,
    )
    assert info.vram_used_gb is None, "free 가 없으면 used 도 None 이어야 한다"
    assert "VRAM 없음" in info.describe()

    info.vram_free_gb = 8.0
    assert "8.0/16.0GB" in info.describe()


def test_vram_labels_handle_partial_system_stats():
    """상태 표시가 free 누락 상태에서도 문자열을 만든다 (GUI 스레드 1초 타이머)."""
    from app.comfy.client import SystemInfo

    # GUI 를 띄우지 않고 상태 표시가 쓰는 포맷 경로만 확인한다.
    info = SystemInfo(online=True, vram_total_gb=24.0, vram_free_gb=None)
    used = info.vram_used_gb
    text = (
        f"VRAM: {used:.1f}/{info.vram_total_gb:.1f}GB"
        if used is not None
        else "VRAM: -"
    )
    assert text == "VRAM: -"


def test_enhancer_is_detected_and_bypass_rewires_prompt(enhancer_engine):
    """인핸서 스위치를 끄면 TextEncode 에 원본 프롬프트가 직접 들어간다."""
    assert _is_enhancer("QwenImage21PromptEnhancerT8")
    assert not _is_enhancer("TextEncodeQwenImage21")

    engine = enhancer_engine
    request = engine.build_request(
        prompt="고양이", negative_prompt="흐릿",
        width=640, height=480, steps=8, cfg=4.0, seed=999,
        enhance_prompt=True,
    )
    _, on = engine._payload(request)
    assert on["14"]["inputs"]["prompt"] == "고양이"
    assert on["4"]["inputs"]["prompt"] == ["14", 0]

    request.enhance_prompt = False
    _, off = engine._payload(request)
    assert off["4"]["inputs"]["prompt"] == "고양이", "우회하면 링크가 풀려야 한다"


def test_llm_model_is_recorded_when_enhancer_runs(enhancer_engine, fake_comfy):
    """인핸서가 돌았으면 LLM 모델명이 메타데이터와 세션에 기록된다.

    회귀 근거: SessionMetadata(llm_model=None) 이 하드코딩되어 있어서
    실제로 LLM 이 프롬프트를 번역·확장해도 기록은 항상 null 이었다.
    그래서 화면에 LLM: N/A 로만 떴다.
    """
    import json as _json

    engine = enhancer_engine
    engine.system_info = SystemInfo(online=True, error="")
    fake_comfy["images"] = [{"filename": "a.png", "subfolder": ""}]

    request = engine.build_request(
        prompt="고양이", width=64, height=64, steps=4, cfg=4.0, seed=1,
        enhance_prompt=True,
    )
    result = engine.generate(request)

    assert result.success is True, result.error
    assert result.metadata["llm_model"] == "pe.gguf", (
        f"인핸서 모델명이 기록돼야 한다: {result.metadata['llm_model']!r}"
    )

    session_dir = engine.sessions.list_sessions()[0]
    session = _json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    assert session["llm_model"] == "pe.gguf"

    output_json = sorted(engine.outputs.outputs_root.rglob("*.json"))
    out = _json.loads(output_json[0].read_text(encoding="utf-8"))
    assert out["llm_model"] == "pe.gguf"


def test_llm_model_is_none_when_enhancer_is_bypassed(enhancer_engine, fake_comfy):
    """인핸서를 껐으면 LLM 모델명은 None 이다 (LLM 이 안 돌았으므로).

    회귀 방지: 인핸서 노드를 payload 에서 지웠는데도 워크플로 기본값을
    그대로 읽어 "돌았지만 안 쓰였다" 는 잘못된 기록을 남길 수 있다.
    """
    engine = enhancer_engine
    engine.system_info = SystemInfo(online=True, error="")
    fake_comfy["images"] = [{"filename": "a.png", "subfolder": ""}]

    request = engine.build_request(
        prompt="고양이", width=64, height=64, steps=4, cfg=4.0, seed=1,
        enhance_prompt=False,
    )
    result = engine.generate(request)

    assert result.success is True, result.error
    assert result.metadata["llm_model"] is None


def test_enhancer_model_prefers_filled_input_in_priority_order():
    """인핸서 모델명은 채워진 입력 중 우선순위 순으로 고른다.

    회귀 근거: api_mode 가 워크플로마다 다른 한국어 문자열이라
    어느 모델을 썼는지 알려줄 수 없다. 값이 있는 첫 항목을 쓴다.
    """
    from app.engine.comfy_engine import _enhancer_model

    payload = {"14": {"class_type": "QwenImage21PromptEnhancerT8", "inputs": {
        "custom_model": "", "local_model": "pe.gguf",
        "ai_workshop_model": "gemini-3.5-flash",
    }}}
    assert _enhancer_model(payload) == "pe.gguf"

    payload["14"]["inputs"]["custom_model"] = "my-model"
    assert _enhancer_model(payload) == "my-model"

    # 인핸서 노드가 없으면 (스위치를 꺼서 제거된 경우) None
    assert _enhancer_model({"6": {"class_type": "KSampler", "inputs": {}}}) is None


def test_lora_strength_is_injectable_as_float(enhancer_engine):
    """LoRA 강도(float)가 워크플로에 그대로 주입된다."""
    engine = enhancer_engine
    request = engine.build_request(
        prompt="p", width=640, height=480, steps=8, cfg=4.0, seed=1,
        extra={"strength_model": 0.65},
    )
    _, payload = engine._payload(request)
    value = payload["16"]["inputs"]["strength_model"]
    assert value == pytest.approx(0.65)


def test_model_selectors_are_inferred_for_all_loaders():
    """모델 선택 드롭다운용 파라미터가 로더 노드에서 인식된다."""
    specs = infer_parameters(_ENHANCER_WORKFLOW)
    assert specs["unet"].kind == "model:diffusion_models"
    assert specs["clip"].kind == "model:text_encoders"
    assert specs["vae"].kind == "model:vae"
    assert specs["lora"].kind == "model:loras"


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


def test_shutdown_stops_launched_process(tmp_path: Path):
    """shutdown() 이 띄운 프로세스를 종료한다.

    회귀 방지: 창을 닫으면 ComfyUI 도 같이 내려가야 한다.
    """
    import subprocess

    eng = GeurimGyeolEngine(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    eng._launched_process = proc
    try:
        eng.shutdown()
        assert proc.poll() is not None, "프로세스가 종료되어야 한다"
        assert eng._launched_process is None
    finally:
        if proc.poll() is None:
            proc.kill()


def test_shutdown_force_kills_unresponsive_process(tmp_path: Path):
    """정상 종료가 안 되는 프로세스는 강제로 끝낸다 (VRAM 회수 보장).

    회귀 방지: terminate 로 죽지 않아도 프로세스가 남으면
    VRAM 이 그대로 점유된다.
    """
    import subprocess

    eng = GeurimGyeolEngine(tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    eng._launched_process = proc

    killed = {"n": 0}
    real_kill = proc.kill

    # terminate 는 무력화하고, wait 는 계속 타임아웃시키며,
    # kill 만 실제로 프로세스를 죽이도록 한다
    def _always_timeout(timeout=None):
        raise TimeoutError("종료되지 않음")

    def _real_kill():
        killed["n"] += 1
        real_kill()

    proc.terminate = lambda: None
    proc.wait = _always_timeout
    proc.kill = _real_kill
    eng.system_info.online = False

    try:
        eng.shutdown()
        assert killed["n"] == 1, "강제 종료(kill)가 호출되어야 한다"
        proc.wait = proc.wait  # 복구
        deadline = 10
        while proc.poll() is None and deadline > 0:
            import time as _t
            _t.sleep(0.2)
            deadline -= 1
        assert proc.poll() is not None, "프로세스가 없어야 한다"
    finally:
        if proc.poll() is None:
            real_kill()


def test_shutdown_without_process_is_noop(tmp_path: Path):
    """띄운 프로세스가 없으면 아무 일도 하지 않는다."""
    GeurimGyeolEngine(tmp_path).shutdown()


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