from __future__ import annotations
from pathlib import Path

from ..base import ImageModelAdapter, GenerationResult


class SDXLAdapter(ImageModelAdapter):
    """SDXL 어댑터 — Diffusers 디렉토리 또는 single-file 지원."""

    architecture = "sdxl"
    supports_negative_prompt = True

    def load(self, model_path: Path) -> None:
        try:
            import torch
            from diffusers import AutoPipelineForText2Image
        except ImportError as e:
            raise RuntimeError(
                "torch/diffusers are not installed. Install requirements.txt first."
            ) from e

        dtype = self._dtype()
        device = self.hardware.device
        if model_path.is_dir():
            self.pipe = AutoPipelineForText2Image.from_pretrained(
                str(model_path),
                torch_dtype=dtype,
                local_files_only=True,
            )
        else:
            from diffusers import StableDiffusionXLPipeline
            self.pipe = StableDiffusionXLPipeline.from_single_file(
                str(model_path),
                torch_dtype=dtype,
                local_files_only=True,
            )
        self.pipe = self.pipe.to(device)
        if hasattr(self.pipe, "enable_attention_slicing"):
            self.pipe.enable_attention_slicing()
        self.loaded_path = model_path
        self.logger.info("SDXL pipeline loaded: %s", model_path.name)

    def _dtype(self):
        import torch
        return torch.float16 if self.hardware.dtype == "float16" else torch.float32

    def estimate_memory(self) -> float:
        """SDXL 기준 예상 VRAM (GB)."""
        return 5.0
