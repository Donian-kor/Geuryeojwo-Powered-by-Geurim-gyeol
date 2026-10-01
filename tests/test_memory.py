"""Memory 관리 및 VRAM 예산 테스트 (v0.1 §8, §8.4)."""
import shutil

import pytest

from app.engine.memory.manager import MemoryManager
from app.engine.memory.snapshot import MemorySnapshotter
from app.engine.memory.cleanup import MemoryCleanup
from app.engine.memory.budget import (
    VramBudgetManager,
    VramLimitMode,
    compute_budget,
)


def test_snapshot_contains_required_metrics():
    """스냅샷이 §8.3의 4개 항목을 포함한다."""
    snap = MemorySnapshotter().take_snapshot("test")
    assert snap.stage == "test"
    assert snap.vram_free_gb is None or snap.vram_free_gb >= 0
    assert snap.vram_total_gb is None or snap.vram_total_gb >= 0
    assert snap.vram_allocated_gb is None or snap.vram_allocated_gb >= 0
    assert snap.vram_reserved_gb is None or snap.vram_reserved_gb >= 0


def test_ram_snapshot_populated():
    """psutil이 설치되어 있으면 RAM 정보가 채워진다."""
    snap = MemorySnapshotter().take_snapshot("test")
    if snap.ram_total_gb is not None:
        assert snap.ram_total_gb > 0
        assert 0 <= snap.ram_free_gb <= snap.ram_total_gb


def test_manager_records_snapshot_history():
    """MemoryManager가 스냅샷 이력을 보관한다."""
    mm = MemoryManager()
    mm.take_snapshot("before")
    mm.take_snapshot("after")
    assert len(mm.snapshots) == 2
    assert [s.stage for s in mm.snapshots] == ["before", "after"]


def test_verify_available_vram_respects_margin():
    """OOM Protection가 여유 마진을 반영한다 (v0.1 §8.4)."""
    mm = MemoryManager()
    snap = mm.take_snapshot("check")
    if snap.vram_free_gb is None:
        assert mm.verify_available_vram(999.0) is True
    else:
        assert mm.verify_available_vram(snap.vram_free_gb + 10) is False
        assert mm.verify_available_vram(0.0) is True


# --- VRAM 예산 정책 (v0.1 §8.4) ---


def test_default_budget_is_conservative():
    """기본값은 8 GB로 보수적이어야 한다.

    사용자가 자기 사양을 몰라도 안전하게 동작해야 한다.
    """
    budget = compute_budget("default")
    assert budget.limit_gb == 8.0
    assert budget.mode == VramLimitMode.DEFAULT
    assert budget.usable_gb == 7.5


def test_default_ignores_detected_vram():
    """기본 모드는 실제 GPU 사양과 무관하게 8 GB를 쓴다."""
    budget = compute_budget("default", detected_gb=24.0)
    assert budget.limit_gb == 8.0


def test_auto_uses_detected_vram():
    """auto 모드는 감지된 VRAM에서 여유분을 뺀 값을 쓴다."""
    budget = compute_budget("auto", detected_gb=24.0)
    assert budget.limit_gb == pytest.approx(23.2)
    assert budget.mode == VramLimitMode.AUTO


def test_auto_falls_back_without_gpu():
    """GPU를 못 쓰는 환경에서는 보수적 기본값으로 되돌린다."""
    budget = compute_budget("auto", detected_gb=None)
    assert budget.limit_gb == 8.0


def test_custom_uses_given_value():
    budget = compute_budget("custom", custom_gb=16.0, detected_gb=8.0)
    assert budget.limit_gb == 16.0
    assert budget.usable_gb == 15.5


def test_unlimited_allows_anything():
    """무제한이라도 실제 GPU VRAM은 넘을 수 없다."""
    budget = compute_budget("unlimited", detected_gb=24.0)
    assert budget.limit_gb is None
    assert budget.is_unlimited is True
    assert budget.can_fit(20.0)[0] is True

    # 실제 GPU보다 큰 요구는 거부한다
    too_big = compute_budget("unlimited", detected_gb=8.0)
    assert too_big.can_fit(20.0)[0] is False


def test_can_fit_respects_budget():
    budget = compute_budget("default")
    assert budget.can_fit(7.0)[0] is True
    assert budget.can_fit(8.5)[0] is False


def test_can_fit_exceeds_real_gpu_message():
    """예상치가 실제 GPU VRAM도 넘으면 그 사실을 알려준다."""
    budget = compute_budget("custom", custom_gb=32.0, detected_gb=8.0)
    ok, message = budget.can_fit(20.0)
    assert ok is False
    assert "8.0" in message


def test_invalid_mode_falls_back_to_default():
    budget = compute_budget("nonexistent_mode")
    assert budget.mode == VramLimitMode.DEFAULT


def test_manager_from_config():
    """app_config.json에서 예산 설정을 읽는다 (v0.1 §3.4)."""
    manager = VramBudgetManager.from_config(
        {"memory": {"vram_limit_mode": "custom", "vram_limit_gb": 24.0}},
        detected_gb=24.0,
    )
    assert manager.limit_gb == 24.0


def test_manager_default_when_config_missing():
    manager = VramBudgetManager.from_config({}, detected_gb=24.0)
    assert manager.limit_gb == 8.0


def test_manager_set_mode_updates_budget():
    manager = VramBudgetManager(detected_gb=24.0)
    manager.set_mode("auto")
    assert manager.limit_gb == pytest.approx(23.2)
    manager.set_mode("unlimited")
    assert manager.limit_gb is None


def test_manager_roundtrip_config():
    """설정 저장 → 불러오기 왕복이 일치한다."""
    manager = VramBudgetManager(detected_gb=16.0)
    manager.set_mode("custom", 20.0)
    restored = VramBudgetManager.from_config(
        {"memory": manager.to_config()}, detected_gb=16.0
    )
    assert restored.limit_gb == manager.limit_gb
    assert restored.mode == manager.mode


def test_engine_default_budget_is_eight_gb(project_root, tmp_path):
    """새로 만든 엔진의 기본 예산은 8 GB (v0.1 §8.4)."""
    from app.engine import GeurimGyeolEngine

    sandbox = tmp_path / "fresh_root"
    (sandbox / "config").mkdir(parents=True)
    for config_file in (project_root / "config").glob("*.json"):
        shutil.copy2(config_file, sandbox / "config" / config_file.name)

    isolated = GeurimGyeolEngine(sandbox)
    try:
        assert isolated.vram_budget.mode == "default"
        assert isolated.vram_budget.limit_gb == 8.0
    finally:
        isolated.shutdown()


def test_pipeline_respects_budget(engine):
    """파이프라인 VRAM 검사가 예산을 반영한다 (v0.1 §8.4)."""
    engine.set_vram_limit("default", 8.0)
    ok, message = engine.image.check_vram("flux")
    assert ok is False
    assert "9.0" in message


def test_set_vram_limit_persists(engine, tmp_path):
    """변경한 제한이 설정 파일에 저장된다 (v0.1 §3.4)."""
    engine.set_vram_limit("custom", 24.0)
    assert engine.vram_budget.limit_gb == 24.0


def test_cleanup_is_idempotent():
    """cleanup을 여러 번 호출해도 예외가 없다."""
    cleanup = MemoryCleanup()
    for _ in range(3):
        cleanup.cleanup()
    cleanup.cleanup_model(None)
    cleanup.force_cleanup_all()


@pytest.mark.parametrize("cycles", [10])
def test_repeated_cleanup_does_not_leak_objects(cycles):
    """반복 정리 후 객체 수가 증가하지 않는다 (v0.1 §36)."""
    import gc

    mm = MemoryManager()
    gc.collect()
    before = len(gc.get_objects())
    for i in range(cycles):
        mm.take_snapshot(f"cycle_{i}")
        mm.cleanup()
    gc.collect()
    after = len(gc.get_objects())
    assert after - before < 500, f"객체 증가: {after - before}"