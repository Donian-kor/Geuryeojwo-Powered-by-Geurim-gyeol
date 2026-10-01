from __future__ import annotations
from pathlib import Path

from ..base import ImageModelAdapter, GenerationResult


class SD3Adapter(ImageModelAdapter):
    """Stable Diffusion 3 어댑터 (v0.1 §18).

    MMDiT 아키텍처 기반 모델로 Diffusers 디렉토리 형태를 사용한다.
    Negative prompt를 지원하지 않으며, cfg 대신 guidance_scale 대신
    true guidance(내부 고정)를 사용한다.
    """

    architecture = "sd3"
    supports_negative_prompt = False

    def load(self, model_path: Path) -> None:
        try:
            import torch
            from diffusers import StableDiffusion3Pipeline
        except ImportError as e:
            raise RuntimeError(
                "torch/diffusers are not installed. Install requirements.txt first."
            ) from e

        dtype = self._dtype()
        device = self.hardware.device
        self.pipe = StableDiffusion3Pipeline.from_pretrained(
            str(model_path),
            torch_dtype=dtype,
            local_files_only=True,
        )
        self.pipe = self.pipe.to(device)
        if hasattr(self.pipe, "enable_attention_slicing"):
            self.pipe.enable_attention_slicing()
        self.loaded_path = model_path
        self.logger.info("SD3 pipeline loaded: %s", model_path.name)

    def _dtype(self):
        import torch
        return torch.float16 if self.hardware.dtype == "float16" else torch.float32

    def generate(
        self,
        prompt: str,
        negative: str,
        width: int,
        height: int,
        steps: int,
        cfg: float,
        seed: int,
        progress=None,
    ) -> GenerationResult:
        """SD3는 negative prompt를 지원하지 않으므로 무시한다."""
        if self.pipe is None:
            raise RuntimeError("Image model is not loaded")
        import torch
        generator = torch.Generator(
            device=self.hardware.device if self.hardware.device != "mps" else "cpu"
        )
        if seed < 0:
            seed = int(torch.randint(0, 2**31 - 1, (1,), generator=generator).item())
        else:
            generator.manual_seed(seed)

        kwargs = dict(
            prompt=prompt,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=cfg,
            generator=generator,
        )
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

        return GenerationResult(image=result.images[0], seed=seed)

    def estimate_memory(self) -> float:
        """SD3 medium 기준 예상 VRAM (GB)."""
        return 9.5