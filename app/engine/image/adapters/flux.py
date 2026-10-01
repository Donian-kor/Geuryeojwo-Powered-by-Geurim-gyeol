from __future__ import annotations
from pathlib import Path

from ..base import ImageModelAdapter, GenerationResult


class FluxAdapter(ImageModelAdapter):
    """Flux.1-dev / Flux.1-schnell 어댑터.

    Diffusers의 `FluxPipeline`을 사용하여 이미지를 생성한다.
    SD 1.5/2.1/XL과 달리 Transformer 아키텍처 기반이므로
    다른 메모리 특성과 파라미터를 가진다.
    """

    architecture = "flux"
    supports_negative_prompt = False

    def load(self, model_path: Path) -> None:
        try:
            import torch
            from diffusers import FluxPipeline
        except ImportError as e:
            raise RuntimeError(
                "torch/diffusers are not installed. Install requirements.txt first."
            ) from e

        dtype = self._dtype()
        device = self.hardware.device

        if model_path.is_dir():
            self.pipe = FluxPipeline.from_pretrained(
                str(model_path),
                torch_dtype=dtype,
                local_files_only=True,
            )
        else:
            self.pipe = FluxPipeline.from_single_file(
                str(model_path),
                torch_dtype=dtype,
                local_files_only=True,
            )

        self.pipe = self.pipe.to(device)
        if hasattr(self.pipe, "enable_attention_slicing"):
            self.pipe.enable_attention_slicing()

        self.loaded_path = model_path
        self.logger.info("Flux pipeline loaded: %s", model_path.name)

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
        """Flux는 negative prompt를 지원하지 않으므로 무시한다."""
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
        """Flux.1 기준 예상 VRAM (GB)."""
        return 9.0
