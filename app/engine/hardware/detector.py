from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareInfo:
    """감지된 하드웨어 정보 (v0.1 §7)."""

    device: str
    dtype: str
    backend: str
    name: str
    vram_gb: float | None
    capability: str | None = None
    cuda_version: str | None = None
    warning: str | None = None

    @property
    def is_gpu(self) -> bool:
        """GPU 가속이 가능한지 여부."""
        return self.device in ("cuda", "mps")

    @property
    def is_cpu_fallback(self) -> bool:
        """GPU 없이 CPU 폴백으로 동작 중인지 여부."""
        return self.device == "cpu"


def _describe_cuda_failure() -> str | None:
    """CUDA가 있는데 torch가 못 쓰는 경우 원인을 설명한다 (v0.1 §28)."""
    try:
        import torch

        if torch.cuda.is_available():
            return None
        if not hasattr(torch, "version") or torch.version.cuda is None:
            return (
                "CPU 전용 torch가 설치되어 있습니다. GPU를 사용하려면 CUDA 빌드로 "
                "재설치해야 합니다:\n"
                "  pip install torch --index-url https://download.pytorch.org/whl/cu130"
            )
        return (
            "CUDA 빌드 torch가 설치되어 있으나 GPU를 인식하지 못했습니다. "
            "그래픽 드라이버 버전과 CUDA 버전 호환을 확인하세요."
        )
    except Exception:
        return None


def detect_hardware() -> HardwareInfo:
    """하드웨어를 감지한다 (v0.1 §7).

    우선순위: CUDA → MPS → CPU 폴백.
    CPU 폴백 시 float32를 사용해 메모리를 절약한다.
    """
    try:
        import torch

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            capability = f"sm_{props.major}{props.minor}"
            return HardwareInfo(
                device="cuda",
                dtype="float16",
                backend="CUDA",
                name=props.name,
                vram_gb=props.total_memory / 1024**3,
                capability=capability,
                cuda_version=torch.version.cuda,
            )

        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return HardwareInfo(
                device="mps",
                dtype="float16",
                backend="MPS",
                name="Apple Silicon",
                vram_gb=None,
            )
    except Exception as exc:
        return HardwareInfo(
            device="cpu",
            dtype="float32",
            backend="CPU",
            name="CPU",
            vram_gb=None,
            warning=f"하드웨어 감지 중 오류: {exc}",
        )

    return HardwareInfo(
        device="cpu",
        dtype="float32",
        backend="CPU",
        name="CPU",
        vram_gb=None,
        warning=_describe_cuda_failure(),
    )
