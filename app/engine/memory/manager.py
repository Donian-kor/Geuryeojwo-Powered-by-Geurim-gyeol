from __future__ import annotations

from .snapshot import MemorySnapshot
from .cleanup import MemoryCleanup
from .snapshot import MemorySnapshotter as _Snapshotter


class MemoryManager:
    """Memory management (v0.1 §8).

    책임 (v.01 §44.5):
    - VRAM/RAM Monitoring
    - LLM → Image Model 전환 (메모리 정리)
    - Garbage Collection
    - CUDA Cache Cleanup
    - Memory Snapshot (before/after 기록)
    - OOM Protection (§8.4)
    """

    def __init__(self, logger=None):
        self._logger = logger
        self._cleanup = MemoryCleanup(logger)
        self._snapshotter = _Snapshotter(logger)
        self._snapshots: list[MemorySnapshot] = []

    def take_snapshot(self, stage: str = "") -> MemorySnapshot:
        """현재 메모리 상태를 스냅샷으로 기록한다 (v.01 §8.3)."""
        snap = self._snapshotter.take_snapshot(stage)
        self._snapshots.append(snap)
        return snap

    @property
    def snapshots(self) -> list[MemorySnapshot]:
        """기록된 모든 스냅샷 반환."""
        return list(self._snapshots)

    def cleanup(self) -> None:
        """메모리 정리 (GC + CUDA/MPS 캐시 삭제)."""
        self._cleanup.cleanup()

    def force_cleanup_all(self) -> None:
        """강제로 모든 캐시를 정리한다."""
        self._cleanup.force_cleanup_all()

    def cleanup_model(self, model) -> None:
        """특정 모델 객체 메모리 해제."""
        self._cleanup.cleanup_model(model)

    def snapshot(self) -> dict:
        """Legacy snapshot interface — returns current VRAM info as dict."""
        snap = self.take_snapshot("current")
        data = {}
        if snap.vram_free_gb is not None:
            data["vram_free_gb"] = snap.vram_free_gb
        if snap.vram_total_gb is not None:
            data["vram_total_gb"] = snap.vram_total_gb
        return data

    def verify_available_vram(self, required_gb: float, margin_gb: float = 0.5) -> bool:
        """OOM Protection (v.01 §8.4): check if required VRAM is available."""
        snap = self.take_snapshot("vram_check")
        if snap.vram_free_gb is None:
            return True
        return snap.vram_free_gb >= required_gb + margin_gb
