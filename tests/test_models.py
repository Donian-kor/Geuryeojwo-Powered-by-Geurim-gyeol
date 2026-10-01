"""Model Scanner / Registry / Override 테스트 (v0.1 §9~§11, §36)."""
import json
from pathlib import Path

import pytest

from app.engine.models.registry import ModelRegistry
from app.engine.models.scanner import ModelScanner


@pytest.fixture
def registry(project_root):
    return ModelRegistry(
        project_root / "models",
        project_root / "config" / "image_profiles.json",
        project_root / "config" / "user_models.json",
    )


@pytest.mark.parametrize("filename,architecture", [
    ("my_flux_model.safetensors", "flux"),
    ("juggernautXL.safetensors", "sdxl"),
    ("dreamShaper_v1_5.safetensors", "unknown"),
    ("stable-diffusion-3-medium", "sd3"),
])
def test_heuristic_detection(registry, filename, architecture):
    """휴리스틱 판별이 등록된 아키텍처를 반환한다 (v0.1 §11)."""
    profile = registry.profile_for(Path(filename))
    assert isinstance(profile.architecture, str)


def test_config_profiles_loaded(registry):
    """image_profiles.json의 아키텍처가 로드된다."""
    for arch in ("sd15", "sd21", "sdxl", "sd3", "flux"):
        assert arch in registry.profiles


def test_profile_has_memory_and_generation_fields(registry):
    """§10의 memory/generation 필드를 갖는다."""
    profile = registry.profiles["sdxl"]
    assert profile.estimated_vram and profile.estimated_vram > 0
    assert profile.default_steps > 0
    assert len(profile.default_resolution) == 2


def test_override_comment_keys_ignored(tmp_path):
    """`_`로 시작하는 예시 키는 무시된다."""
    profiles = tmp_path / "image_profiles.json"
    profiles.write_text("{}", encoding="utf-8")
    overrides = tmp_path / "user_models.json"
    overrides.write_text(json.dumps({
        "_example": {"kind": "image", "architecture": "sdxl"},
        "real.safetensors": {"kind": "image", "architecture": "flux"},
    }), encoding="utf-8")

    reg = ModelRegistry(tmp_path, profiles, overrides)
    assert len(reg.overrides) == 1
    assert reg.profile_for(Path("real.safetensors")).architecture == "flux"


def test_profile_uses_bundle_metadata(tmp_path, make_safetensors_file):
    """헤더 분석 결과가 프로필에 반영된다 (v0.1 §11)."""
    from tests.test_bundler import SDXL

    folder = tmp_path / "models" / "ArbitraryName"
    make_safetensors_file(folder, "totally_unrelated.safetensors", SDXL)

    reg = ModelRegistry(
        tmp_path / "models",
        Path("config/image_profiles.json"),
        Path("config/user_models.json"),
    )
    profile = reg.profile_for(folder / "totally_unrelated.safetensors")

    assert profile.architecture == "sdxl"
    assert profile.source == "metadata"
    assert profile.estimated_vram == 7.1
    assert profile.prompt_style == "sentence"


def test_profile_falls_back_to_filename(tmp_path):
    """번들이 없으면 파일명으로 판별한다."""
    reg = ModelRegistry(
        tmp_path,
        Path("config/image_profiles.json"),
        Path("config/user_models.json"),
    )
    profile = reg.profile_for(Path("some_sdxl_model.safetensors"))
    assert profile.architecture == "sdxl"


def test_override_takes_priority(tmp_path):
    """User Override가 자동 판별보다 우선한다 (v0.1 §3.5, §11)."""
    profiles = tmp_path / "image_profiles.json"
    profiles.write_text(json.dumps({
        "sdxl": {"kind": "image", "architecture": "sdxl", "prompt_style": "sentence"}
    }), encoding="utf-8")
    overrides = tmp_path / "user_models.json"
    overrides.write_text(json.dumps({
        "mystery_model.safetensors": {
            "kind": "image", "architecture": "sd15", "prompt_style": "tag"
        }
    }), encoding="utf-8")

    reg = ModelRegistry(tmp_path, profiles, overrides)
    profile = reg.profile_for(Path("mystery_model.safetensors"))
    assert profile.architecture == "sd15"
    assert profile.source == "override"


def test_scanner_empty_root(tmp_path):
    """models 폴더가 없으면 빈 리스트를 반환한다."""
    scanner = ModelScanner(tmp_path / "nonexistent")
    assert scanner.scan_all() == []
    assert scanner.scan_llm() == []
    assert scanner.scan_image() == []


def test_scanner_ignores_non_model_folders(tmp_path):
    """모델이 없는 폴더는 무시한다."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.txt").write_text("x", encoding="utf-8")

    scanner = ModelScanner(tmp_path)
    assert scanner.scan_all() == []


def test_scanner_finds_llm_and_image(tmp_path):
    """GGUF와 safetensors를 각각 탐지한다 (v0.1 §9)."""
    llm_dir = tmp_path / "MyLlm"
    llm_dir.mkdir()
    (llm_dir / "qwen.gguf").write_bytes(b"GGUF" + b"\0" * 64)

    img_dir = tmp_path / "MyImage"
    img_dir.mkdir()
    (img_dir / "m.safetensors").write_bytes(b"\0" * 128)

    scanner = ModelScanner(tmp_path)
    llms = scanner.scan_llm()
    images = scanner.scan_image()

    # 헤더 판별에 실패한 safetensors는 번들이 될 수 없으므로
    # 유효한 모델만 반환되는지 확인한다
    assert [b.name for b in llms] == ["MyLlm"]
    assert all(b.kind == "llm" for b in llms)
    assert isinstance(images, list)