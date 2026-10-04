"""pytest 공통 설정 (v0.2).

네이티브 추론 모듈이 제거되었으므로 torch/픽스처 의존은 모두 걷어냈다.
남은 테스트는 순수 파일 I/O(출력·세션 저장)와 GUI 위젯 검증을 다룬다.
"""
import os
import sys
from pathlib import Path

import pytest

# GUI 테스트를 서버 없는 환경에서도 돌리기 위해 offscreen 을 기본으로 쓴다.
# 창을 실제로 그리지 않고 레이아웃·위젯 상태만 확인한다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_root(tmp_path, monkeypatch):
    """GUI 테스트가 실제 config/ 를 읽고 쓰게 하지 않는다.

    회귀 근거: MainWindow 는 ROOT 로부터 config/ 와 workflows/ 를 읽는다.
    모델 선택은 config/model_choices.json 에 저장되므로, ROOT 가 실제
    프로젝트 루트면 테스트가 사용자의 모델 선택을 지운다. (테스트용
    워크플로 이름이 그대로 저장되어 실제로도 지워진다)
    설정 파일과 워크플로를 복사해 두면 테스트는 실제와 같은 화면을 보면서
    쓰기는 tmp 로만 한다.
    """
    import shutil

    import app.gui.main_window as mw

    root = tmp_path / "gui_root"
    (root / "config").mkdir(parents=True, exist_ok=True)
    for name in ("comfyui.json", "theme_config.json"):
        source = ROOT / "config" / name
        if source.exists():
            (root / "config" / name).write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8"
            )
    shutil.copytree(ROOT / "workflows", root / "workflows", dirs_exist_ok=True)
    monkeypatch.setattr(mw, "ROOT", root)
    return root


@pytest.fixture(autouse=True)
def no_real_gpu_reader(monkeypatch):
    """GUI 테스트가 실제 nvidia-smi 를 띄우지 않게 한다.

    회귀 근거: MainWindow.__init__ 이 창을 만들 때마다 GpuUsageReader 를
    만들어 nvidia-smi 프로세스와 읽기 스레드를 띄운다. 테스트는 창을
    19 곳에서 만드는데, 닫히지 않은 창이 남으면 스레드가 파이프를 읽은
    채로 살아 있다. 스위트 끝에 프로그램이 종료되며 그것이
    'access violation' 으로 죽었다. (gpu_usage.py 의 for line in proc.stdout)

    단위 테스트가 실제 하드웨어에 의존해서는 안 된다. 상태 표시만 보면 되는
    곳에 GPU 프로세스가 필요하지 않다. GpuUsageReader 자체는
    tests/test_gpu_usage.py 가 가짜 프로세스로 따로 검증한다.

    읽히면 '지원 안 함' 으로 표시되므로 상태 표시 테스트에 영향이 없다.
    """
    class _StubGpuUsage:
        started = False
        available = False

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def percent(self):
            return None

        def vram(self):
            return (None, None)

        def vram_gb(self):
            return (None, None)

    monkeypatch.setattr(
        "app.gui.main_window.GpuUsageReader", _StubGpuUsage, raising=False
    )


@pytest.fixture(autouse=True)
def no_real_node_definitions(monkeypatch):
    """GUI 테스트가 실제 ComfyUI 에 접속하지 않게 한다.

    회귀 근거: 커스텀 노드의 선택형 칸을 찾으려면 노드 정의(/object_info,
    2.4MB)가 필요하다. 이러지 않으면 창을 만드는 테스트마다 서버 응답을
    기다려 느려지고, ComfyUI 가 켜져 있는지에 따라 결과가 달라진다.

    노드 정의만 '아무것도 없는 서버' 로 흉내낸다. 서버가 꺼졌을 때와 같은
    경로라 판단 보류로 넘어간다. (enhancer_status 를 막는 것과 같은 이유다)
    다른 경로는 전부 실패시키되, 각 조회 메서드가 예외를 받아 처리하는
    경로여서 테스트 목적에는 지장이 없다.
    """
    from app.comfy.client import ComfyClient, ComfyUIError

    class _EmptyResponse:
        def json(self):
            return {}

    async def _fake_get(self, path, *args, **kwargs):
        if str(path).startswith("/object_info"):
            return _EmptyResponse()
        raise ComfyUIError(f"테스트에서는 서버를 쓰지 않는다: {path}")

    monkeypatch.setattr(ComfyClient, "_get", _fake_get)


@pytest.fixture(scope="session")
def project_root() -> Path:
    """프로젝트 루트 경로."""
    return ROOT


@pytest.fixture
def sandbox_root(tmp_path: Path) -> Path:
    """엔진이 쓸 임시 루트 (config/workflows/outputs/sessions)."""
    root = tmp_path / "root"
    for name in ("config", "workflows", "outputs", "sessions"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def tmp_outputs(tmp_path: Path):
    """출력/세션 임시 디렉토리."""
    outputs = tmp_path / "outputs"
    sessions = tmp_path / "sessions"
    outputs.mkdir()
    sessions.mkdir()
    return outputs, sessions