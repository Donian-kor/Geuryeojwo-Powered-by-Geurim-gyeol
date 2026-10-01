"""pytest 공통 설정 (v0.1 §36 테스트 계획)."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def project_root() -> Path:
    """프로젝트 루트 경로."""
    return ROOT


@pytest.fixture(scope="session")
def engine(project_root):
    """초기화된 GeurimGyeolEngine 픽스처."""
    from app.engine import GeurimGyeolEngine

    eng = GeurimGyeolEngine(project_root)
    eng.initialize()
    yield eng
    eng.shutdown()


@pytest.fixture
def tmp_outputs(tmp_path):
    """출력/세션 임시 디렉토리."""
    outputs = tmp_path / "outputs"
    sessions = tmp_path / "sessions"
    outputs.mkdir()
    sessions.mkdir()
    return outputs, sessions