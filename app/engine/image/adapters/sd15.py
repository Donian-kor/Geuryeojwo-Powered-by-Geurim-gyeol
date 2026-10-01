from __future__ import annotations
from pathlib import Path

from ..base import ImageModelAdapter, GenerationResult


class SD15Adapter(ImageModelAdapter):
    """SD 1.5 / 2.1 single-file checkpoint 어댑터."""

    architecture = "sd15"
    supports_negative_prompt = True

    def load(self, model_path: Path, offload_mode=None) -> None:
        try:
            import torch
            from diffusers import StableDiffusionPipeline
        except ImportError as e:
            raise RuntimeError(
                "torch/diffusers are not installed. Install requirements.txt first."
            ) from e

        dtype = self._dtype()
        self.pipe = StableDiffusionPipeline.from_single_file(
            str(model_path),
            torch_dtype=dtype,
            local_files_only=True,
        )
        self._place_on_device(offload_mode)
        self.loaded_path = model_path
        self.logger.info("SD15 pipeline loaded: %s", model_path.name)

    def _dtype(self):
        import torch
        return torch.float16 if self.hardware.dtype == "float16" else torch.float32

    def estimate_memory(self) -> float:
        """SD1.5/checkpoint 기준 예상 VRAM (GB)."""
        return 2.5
