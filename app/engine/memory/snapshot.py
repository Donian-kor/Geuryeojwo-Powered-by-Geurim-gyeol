from __future__ import annotations

import gc
from dataclasses import dataclass


@dataclass
class MemorySnapshot:
    """GPU/CPU 메모리 스냅샷 (v0.1 §8.3).

    생성 단계별로 before/after VRAM, RAM 사용량을 기록한다.
    """
    stage: str = ""
    vram_free_gb: float | None = None
    vram_total_gb: float | None = None
    vram_reserved_gb: float | None = None
    vram_allocated_gb: float | None = None
    ram_free_gb: float | None = None
    ram_total_gb: float | None = None

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "vram": {
                "free_gb": self.vram_free_gb,
                "total_gb": self.vram_total_gb,
                "reserved_gb": self.vram_reserved_gb,
                "allocated_gb": self.vram_allocated_gb,
            },
            "ram": {
                "free_gb": self.ram_free_gb,
                "total_gb": self.ram_total_gb,
            },
        }


class MemorySnapshotter:
    """Memory 스냅샷 취득기 (v0.1 §8.3).

    VRAM/RAM을 측정하여 MemorySnapshot을 생성한다.
    """

    def __init__(self, logger=None):
        self._logger = logger
        self._snapshots: list[MemorySnapshot] = []

    def take_snapshot(self, stage: str = "") -> MemorySnapshot:
        """현재 메모리 상태를 스냅샷으로 기록한다."""
        snap = MemorySnapshot(stage=stage)
        try:
            import torch
            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info()
                snap.vram_free_gb = round(free / 1024**3, 2)
                snap.vram_total_gb = round(total / 1024**3, 2)
                snap.vram_reserved_gb = round(
                    torch.cuda.memory_reserved() / 1024**3, 2
                )
                snap.vram_allocated_gb = round(
                    torch.cuda.memory_allocated() / 1024**3, 2
                )
        except Exception:
            pass
        try:
            import psutil
            vm = psutil.virtual_memory()
            snap.ram_free_gb = round(vm.available / 1024**3, 2)
            snap.ram_total_gb = round(vm.total / 1024**3, 2)
        except ImportError:
            pass
        except Exception:
            pass

        self._snapshots.append(snap)
        if self._logger:
            self._logger.info(
                "Memory snapshot [%s]: VRAM free=%.1fGB total=%.1fGB | "
                "RAM free=%.1fGB total=%.1fGB",
                stage, snap.vram_free_gb or 0, snap.vram_total_gb or 0,
                snap.ram_free_gb or 0, snap.ram_total_gb or 0,
            )
        return snap

    def snapshots(self) -> list[MemorySnapshot]:
        """기록된 모든 스냅샷 반환."""
        return list(self._snapshots)

    def verify_available_vram(self, required_gb: float, margin_gb: float = 0.5) -> bool:
        """OOM Protection (v0.1 §8.4): check if required VRAM is available."""
        snap = self.take_snapshot("vram_check")
        if snap.vram_free_gb is None:
            return True
        return snap.vram_free_gb >= required_gb + margin_gb
