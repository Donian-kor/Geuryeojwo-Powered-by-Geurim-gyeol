"""Memory 관리 테스트 (v0.1 §36 Memory Test, §8)."""
import pytest

from app.engine.memory.manager import MemoryManager
from app.engine.memory.snapshot import MemorySnapshotter
from app.engine.memory.cleanup import MemoryCleanup


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