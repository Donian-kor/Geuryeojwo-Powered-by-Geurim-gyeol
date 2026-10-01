from __future__ import annotations
import gc

class MemoryManager:
    """Releases Python objects and accelerator caches between model stages."""
    def cleanup(self) -> None:
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

    def snapshot(self) -> dict:
        data = {}
        try:
            import torch
            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info()
                data.update(vram_free_gb=round(free/1024**3, 2), vram_total_gb=round(total/1024**3, 2))
        except Exception:
            pass
        return data
