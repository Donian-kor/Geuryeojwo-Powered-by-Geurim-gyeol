"""Hardware 감지 테스트 (v0.1 §36 Hardware Test)."""
import pytest

from app.engine.hardware.detector import detect_hardware


def test_detect_hardware_returns_valid_info():
    """감지 결과가 HardwareInfo 구조를 가진다 (v0.1 §7)."""
    hw = detect_hardware()
    assert hw.device in ("cuda", "mps", "cpu")
    assert hw.backend in ("CUDA", "MPS", "CPU")
    assert hw.dtype in ("float16", "float32")
    assert hw.name


def test_gpu_fields_populated_for_cuda():
    """CUDA 환경이면 GPU 정보가 채워진다 (v0.1 §7)."""
    hw = detect_hardware()
    if hw.device == "cuda":
        assert hw.vram_gb and hw.vram_gb > 0
        assert hw.capability and hw.capability.startswith("sm_")
        assert hw.cuda_version
        assert hw.is_gpu is True
        assert hw.is_cpu_fallback is False


def test_cpu_fallback_uses_float32():
    """CPU 폴백은 float32를 사용한다 (v0.1 §7)."""
    hw = detect_hardware()
    if hw.device == "cpu":
        assert hw.dtype == "float32"
        assert hw.vram_gb is None
        assert hw.is_cpu_fallback is True
        assert hw.is_gpu is False


def test_cpu_fallback_explains_cause():
    """GPU 미사용 시 사유를 알려준다 (v0.1 §28)."""
    hw = detect_hardware()
    if hw.device == "cpu":
        assert hw.warning, "CPU 폴백 사유가 설명되어야 한다"
        assert "torch" in hw.warning.lower()


def test_vram_reported_for_accelerator():
    """가속기가 있으면 VRAM 크기가 보고된다 (v0.1 §7)."""
    hw = detect_hardware()
    if hw.device == "cuda":
        assert hw.vram_gb and hw.vram_gb > 0


def test_detect_hardware_is_deterministic():
    """반복 호출 시 동일한 결과를 반환한다."""
    assert detect_hardware() == detect_hardware()