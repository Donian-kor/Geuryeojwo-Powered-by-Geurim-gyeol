"""pytest 공통 설정 (v0.1 §36 테스트 계획)."""
import shutil
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
def engine(project_root, tmp_path_factory):
    """초기화된 GeurimGyeolEngine 픽스처.

    테스트가 설정을 변경해도 원본 app_config.json이 바뀌지 않도록
    설정 파일을 복사한 임시 루트를 사용한다.
    """
    from app.engine import GeurimGyeolEngine

    sandbox = tmp_path_factory.mktemp("engine_root")
    (sandbox / "config").mkdir()
    for config_file in (project_root / "config").glob("*.json"):
        shutil.copy2(config_file, sandbox / "config" / config_file.name)

    eng = GeurimGyeolEngine(sandbox)
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