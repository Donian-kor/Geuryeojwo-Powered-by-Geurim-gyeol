"""메모리 전략 테스트 (v0.1 §8.2, §8.4).

VRAM이 부족할 때 시스템 RAM으로 넘기는 전략이 올바르게 결정되는지 검증한다.
"""
import inspect

import pytest

from app.engine.memory.strategy import (
    MemoryTier,
    OffloadMode,
    current_ram_available_gb,
    decide_strategy,
)


def _decide(**kwargs):
    defaults = dict(
        required_vram_gb=9.0,
        vram_budget_gb=8.0,
        vram_detected_gb=8.0,
        ram_available_gb=32.0,
    )
    defaults.update(kwargs)
    return decide_strategy(**defaults)


def test_enough_vram_uses_full():
    """VRAM이 충분하면 전체를 VRAM에 올린다."""
    s = _decide(required_vram_gb=5.0, vram_budget_gb=8.0)
    assert s.tier == MemoryTier.FULL
    assert s.offload == OffloadMode.NONE
    assert s.uses_offload is False
    assert s.speed_hint == "최고 속도"


def test_vram_overflow_falls_back_to_ram():
    """VRAM 초과 시 시스템 RAM으로 넘긴다 (ComfyUI SHARED 방식)."""
    s = _decide(required_vram_gb=9.0, vram_budget_gb=8.0, ram_available_gb=32.0)
    assert s.tier == MemoryTier.OFFLOAD
    assert s.offload == OffloadMode.MODEL_CPU
    assert s.uses_offload is True
    assert "시스템 RAM" in s.reason


def test_default_offload_is_model_cpu():
    """기본 offload는 model_cpu_offload다 (Q2=C 요구사항)."""
    s = _decide()
    assert s.offload == OffloadMode.MODEL_CPU


def test_group_offload_supported():
    """group offload도 선택할 수 있다."""
    s = _decide(preferred_offload=OffloadMode.GROUP)
    assert s.offload == OffloadMode.GROUP
    assert "10%" in s.speed_hint


def test_sequential_offload_supported():
    s = _decide(preferred_offload=OffloadMode.SEQUENTIAL)
    assert s.offload == OffloadMode.SEQUENTIAL
    assert "매우 느림" in s.speed_hint


def test_ram_insufficient_reduces_resolution():
    """해상도를 낮춰야만 가능한 경우 TIER_REDUCED로 판정한다.

    20GB 모델을 16GB VRAM 예산 / 15GB RAM 환경에 올리는 경우:
      - offload만으로 RAM 필요: 20 × 1.5 × 0.5 + 2 = 17.0 GB > 15 GB  → 불가
      - 해상도 75%: 15 × 1.5 × 0.5 + 2 = 13.25 GB ≤ 15 GB           → 가능
    """
    s = _decide(
        required_vram_gb=20.0,
        vram_budget_gb=16.0,
        vram_detected_gb=16.0,
        ram_available_gb=15.0,
        width=1024,
        height=1024,
        steps=30,
    )
    assert s.tier == MemoryTier.REDUCED
    assert s.suggested_width is not None
    assert s.suggested_width < 1024
    assert s.suggested_steps < 30


def test_reduced_resolution_is_multiple_of_eight():
    """제안 해상도는 latent 격자에 맞춰 8의 배수여야 한다."""
    s = _decide(
        required_vram_gb=20.0, vram_budget_gb=16.0,
        vram_detected_gb=16.0, ram_available_gb=15.0, width=1024, height=1024,
    )
    assert s.suggested_width % 8 == 0
    assert s.suggested_height % 8 == 0


def test_reduced_suggests_lower_resolution_string():
    s = _decide(
        required_vram_gb=20.0, vram_budget_gb=16.0,
        vram_detected_gb=16.0, ram_available_gb=15.0, width=1024, height=1024,
    )
    assert s.suggested_resolution == f"{s.suggested_width}x{s.suggested_height}"


def test_both_insufficient_is_impossible():
    """VRAM과 RAM이 모두 부족하면 불가능으로 판정한다."""
    s = _decide(
        required_vram_gb=40.0,
        vram_budget_gb=4.0,
        vram_detected_gb=4.0,
        ram_available_gb=6.0,
    )
    assert s.tier == MemoryTier.IMPOSSIBLE
    assert s.uses_offload is False


def test_no_gpu_means_no_offload():
    """GPU가 없으면 offload 없이 CPU 모드로 간다."""
    s = _decide(vram_detected_gb=None, required_vram_gb=50.0)
    assert s.tier == MemoryTier.FULL
    assert s.offload == OffloadMode.NONE
    assert "CPU" in s.reason


def test_unlimited_budget_still_needs_offload():
    """무제한 예산이어도 물리 VRAM을 넘으면 offload가 적용된다."""
    s = _decide(required_vram_gb=20.0, vram_budget_gb=None, vram_detected_gb=8.0)
    assert s.tier == MemoryTier.OFFLOAD
    assert s.uses_offload is True


def test_detected_vram_used_when_no_budget():
    """예산이 없으면 물리 VRAM을 기준으로 판단한다."""
    s = _decide(required_vram_gb=7.0, vram_budget_gb=None, vram_detected_gb=8.0)
    assert s.tier == MemoryTier.FULL
    s2 = _decide(required_vram_gb=9.0, vram_budget_gb=None, vram_detected_gb=8.0)
    assert s2.tier == MemoryTier.OFFLOAD


def test_ram_measured_automatically():
    """ram_available_gb=None이면 실측한다 (Q3 요구사항)."""
    s = decide_strategy(
        required_vram_gb=9.0,
        vram_budget_gb=8.0,
        vram_detected_gb=8.0,
        ram_available_gb=None,
    )
    assert s.ram_available_gb is not None
    assert s.ram_available_gb > 0


def test_current_ram_available_gb():
    """실측 RAM 조회가 동작한다."""
    ram = current_ram_available_gb()
    assert ram is not None
    assert ram > 0


def test_strategy_records_required_values():
    """진단 정보가 결과에 담긴다."""
    s = _decide(required_vram_gb=9.0)
    assert s.required_vram_gb == 9.0
    assert s.required_ram_gb > 9.0  # 오버헤드 포함
    assert s.vram_detected_gb == 8.0
    assert s.ram_available_gb == 32.0


def test_strategy_to_dict():
    s = _decide()
    data = s.to_dict()
    assert data["tier"] == "offload"
    assert data["offload"] == "model_cpu"
    assert "reason" in data


def test_pipeline_plan_strategy(engine):
    """파이프라인이 전략을 결정해 반환한다."""
    strategy = engine.image.plan_strategy("sd15")
    assert strategy.tier in (MemoryTier.FULL, MemoryTier.OFFLOAD, MemoryTier.REDUCED)
    assert isinstance(strategy.describe(), str)


def test_pipeline_plan_strategy_uses_ram(engine, monkeypatch):
    """VRAM을 넘는 모델은 offload 전략으로 넘어간다 (§8.2).

    감지 VRAM보다 큰 추정치를 가진 아키텍처는 자동 offload된다.

    주의: decide_strategy 는 ram_available_gb 가 None 이면 psutil 로
    실제 시스템 RAM 을 조회한다. 그 값은 실행 순간의 가용 메모리에 따라
    달라지므로 (다른 프로그램 사용량, 캐시 상태 등) 결과가 흔들린다.
    그래서 필요한 RAM 을 확실히 확보된 값으로 고정해
    'offload 로 충분하다'는 분기를 검증한다.
    """
    from app.engine.memory.strategy import MemoryTier, OffloadMode

    monkeypatch.setattr(
        "app.engine.memory.strategy.current_ram_available_gb", lambda: 32.0
    )

    strategy = engine.image.plan_strategy("sd3")  # 추정 9.5GB > 감지 7.9GB
    assert strategy.tier == MemoryTier.OFFLOAD
    assert strategy.offload == OffloadMode.MODEL_CPU
    assert strategy.uses_offload is True
    assert "시스템 RAM" in strategy.describe()


def test_adapters_accept_offload_parameter():
    """모든 어댑터가 offload 인자를 받는다 (공통 인터페이스, §46.15)."""
    from app.engine.image.adapters import SD15Adapter, SDXLAdapter, SD3Adapter, FluxAdapter

    for cls in (SD15Adapter, SDXLAdapter, SD3Adapter, FluxAdapter):
        params = inspect.signature(cls.load).parameters
        assert "offload_mode" in params, f"{cls.__name__}.load에 offload_mode 없음"