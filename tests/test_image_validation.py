"""Image Adapter / Dry Run / Model Validation 테스트 (v0.1 §17~§18, §27~§28)."""
from pathlib import Path

import pytest

from app.engine.image.pipeline import ImagePipelineManager
from app.engine.validation.dry_run import ModelValidator


@pytest.mark.parametrize("arch,supported", [
    ("sd15", True), ("sd21", True), ("sdxl", True),
    ("sd3", True), ("flux", True), ("unknown", False),
])
def test_pipeline_supported_architectures(engine, arch, supported):
    manager = engine.image
    assert manager.can_handle(arch) is supported


def test_sd3_adapter_registered(engine):
    """§18의 SD3Adapter가 등록되어 있다."""
    from app.engine.image.adapters import SD3Adapter

    assert engine.image._ADAPTERS["sd3"] is SD3Adapter
    assert SD3Adapter.supports_negative_prompt is False
    assert engine.image.estimate_memory("sd3") > 0


def test_all_adapters_share_interface(engine):
    """어떤 어댑터도 공통 인터페이스를 깨뜨리지 않는다 (§46.15)."""
    required = ("load", "generate", "unload", "estimate_memory")
    for adapter_cls in engine.image._ADAPTERS.values():
        for method in required:
            assert hasattr(adapter_cls, method), f"{adapter_cls.__name__}.{method}"


def test_pipeline_estimates_memory(engine):
    for arch in ("sd15", "sdxl", "flux"):
        assert engine.image.estimate_memory(arch) > 0


def test_pipeline_rejects_unsupported(engine, tmp_path):
    with pytest.raises(RuntimeError, match="지원하지 않는"):
        engine.image.load(tmp_path / "x.safetensors", "unknown")


def test_vram_check_returns_status(engine):
    ok, message = engine.image.check_vram("sdxl")
    assert isinstance(ok, bool)
    assert message


def test_negative_prompt_support_per_adapter(engine):
    """Flux는 negative prompt를 지원하지 않는다 (v0.1 §16)."""
    from app.engine.image.adapters import FluxAdapter, SDXLAdapter

    assert FluxAdapter.supports_negative_prompt is False
    assert SDXLAdapter.supports_negative_prompt is True


def test_dry_run_without_model_reports_error(engine, tmp_path):
    """모델 파일이 없으면 오류를 보고한다 (v0.1 §27)."""
    result = engine.dry_runner.run(tmp_path / "missing.safetensors", None)
    assert result.ready is False
    assert result.errors


def test_dry_run_detects_architecture(engine, tmp_path):
    model = tmp_path / "sdxl_base.safetensors"
    model.write_bytes(b"\0" * 1024)
    result = engine.dry_runner.run(model, None, 1024, 1024, 30, 7.0, -1)
    assert result.architecture == "sdxl"
    assert result.prompt_style in ("sentence", "tag")


def test_model_validator_rejects_small_file(tmp_path):
    """손상/빈 파일을 거부한다 (v0.1 §36)."""
    validator = ModelValidator()
    small = tmp_path / "tiny.gguf"
    small.write_bytes(b"GGUF")
    result = validator.validate_model(small)
    assert result.valid is False


def test_model_validator_detects_corrupted_gguf(tmp_path):
    """GGUF 마직크가 틀리면 손상으로 판정한다."""
    validator = ModelValidator()
    path = tmp_path / "broken.gguf"
    path.write_bytes(b"XXXX" + b"\0" * (20 * 1024 * 1024))
    result = validator.validate_model(path)
    assert result.valid is False
    assert any("GGUF" in e for e in result.errors)


def test_model_validator_missing_file(tmp_path):
    validator = ModelValidator()
    result = validator.validate_model(tmp_path / "nope.gguf")
    assert result.valid is False


def test_model_validator_accepts_valid_gguf_header(tmp_path):
    validator = ModelValidator()
    path = tmp_path / "ok.gguf"
    path.write_bytes(b"GGUF" + b"\0" * (20 * 1024 * 1024))
    result = validator.validate_model(path)
    assert result.valid is True
    assert result.model_type == "llm_gguf"