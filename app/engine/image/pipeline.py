from __future__ import annotations
from pathlib import Path
from typing import Callable

class NativeImageEngine:
    """Native Diffusers adapter. The process owns the pipeline; no external server."""
    def __init__(self, hardware, memory, logger):
        self.hardware = hardware
        self.memory = memory
        self.logger = logger
        self.pipe = None
        self.loaded_path = None

    def _dtype(self):
        try:
            import torch
            return torch.float16 if self.hardware.dtype == "float16" else torch.float32
        except Exception:
            return None

    def load(self, model_path: Path, architecture: str):
        try:
            import torch
            from diffusers import AutoPipelineForText2Image, StableDiffusionPipeline
        except ImportError as e:
            raise RuntimeError("torch/diffusers are not installed. Install requirements.txt first.") from e
        dtype = self._dtype()
        device = self.hardware.device
        self.memory.cleanup()
        if model_path.is_dir():
            self.pipe = AutoPipelineForText2Image.from_pretrained(str(model_path), torch_dtype=dtype, local_files_only=True)
        elif architecture in {"sd15", "sd21", "sdxl"}:
            self.pipe = StableDiffusionPipeline.from_single_file(str(model_path), torch_dtype=dtype, local_files_only=True)
        else:
            raise RuntimeError(f"No v0.1 native single-file loader is registered for architecture: {architecture}. Use a Diffusers directory or add an adapter.")
        self.pipe = self.pipe.to(device)
        if hasattr(self.pipe, "enable_attention_slicing"):
            self.pipe.enable_attention_slicing()
        self.loaded_path = model_path

    def generate(self, prompt: str, negative: str, width: int, height: int, steps: int, cfg: float, seed: int, progress: Callable[[int], None] | None = None):
        if self.pipe is None:
            raise RuntimeError("Image model is not loaded")
        import torch
        generator = torch.Generator(device=self.hardware.device if self.hardware.device != "mps" else "cpu")
        if seed < 0:
            seed = int(torch.randint(0, 2**31 - 1, (1,), generator=generator).item())
        else:
            generator.manual_seed(seed)
        kwargs = dict(prompt=prompt, negative_prompt=negative or None, width=width, height=height, num_inference_steps=steps, guidance_scale=cfg, generator=generator)
        if progress:
            def cb(pipe, step, timestep, callback_kwargs):
                progress(int((step + 1) / max(steps, 1) * 100))
                return callback_kwargs
            try:
                result = self.pipe(callback_on_step_end=cb, **kwargs)
            except TypeError:
                result = self.pipe(**kwargs)
        else:
            result = self.pipe(**kwargs)
        return result.images[0], seed

    def unload(self):
        self.pipe = None
        self.loaded_path = None
        self.memory.cleanup()
