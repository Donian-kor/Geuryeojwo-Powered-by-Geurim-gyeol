from __future__ import annotations

import gc


class MemoryCleanup:
    """Memory cleanup 유틸리티 (v0.1 §8, §8.3).

    책임:
    - Garbage Collection
    - CUDA Cache Cleanup
    - MPS Cache Cleanup
    - 모델 간 메모리 정리 (LLM → Image Model 전환)
    """

    def __init__(self, logger=None):
        self._logger = logger

    def cleanup(self) -> None:
        """Python GC와 가속기 캐시를 정리한다."""
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            if hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
                torch.mps.empty_cache()
        except Exception:
            pass

    def cleanup_model(self, model) -> None:
        """특정 모델 객체 메모리 해제."""
        if model is None:
            return
        try:
            if hasattr(model, "unload"):
                model.unload()
            elif hasattr(model, "pipe"):
                model.pipe = None
        except Exception:
            pass
        try:
            del model
        except Exception:
            pass
        self.cleanup()

    def force_cleanup_all(self) -> None:
        """강제로 모든 캐시와 가비지를 정리한다."""
        if self._logger:
            self._logger.info("Force cleanup: GC + CUDA + MPS")
        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
                torch.cuda.synchronize()
        except Exception:
            pass

        try:
            if hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
                torch.mps.empty_cache()
        except Exception:
            pass

        if self._logger:
            self._logger.debug("Force cleanup completed")
