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