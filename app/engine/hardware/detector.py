from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class HardwareInfo:
    device: str
    dtype: str
    backend: str
    name: str
    vram_gb: float | None


def detect_hardware() -> HardwareInfo:
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return HardwareInfo("cuda", "float16", "CUDA", props.name, props.total_memory / 1024**3)
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return HardwareInfo("mps", "float16", "MPS", "Apple Silicon", None)
    except Exception:
        pass
    return HardwareInfo("cpu", "float32", "CPU", "CPU", None)
