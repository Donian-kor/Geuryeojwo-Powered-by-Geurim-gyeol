from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass


@dataclass
class GenerationResult:
    image: object
    seed: int


class ImageModelAdapter(ABC):
    """AI Engine 내 이미지 모델 Adapter의 추상 베이스.

    Application Core는 모델 내부 구조를 알 필요 없이
    이 인터페이스만 통해 모델을 관리한다 (v0.1 §44.6).
    """

    architecture: str = "unknown"
    supports_negative_prompt: bool = True

    def __init__(self, hardware, logger):
        self.hardware = hardware
        self.logger = logger
        self.pipe = None
        self.loaded_path: Path | None = None

    @abstractmethod
    def load(self, model_path: Path) -> None:
        """모델을 메모리에 로드한다."""

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
        """이미지를 생성한다."""
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
            negative_prompt=negative or None,
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

    def unload(self) -> None:
        """모델을 언로드하고 메모리를 정리한다."""
        self.pipe = None
        self.loaded_path = None

    def estimate_memory(self) -> float:
        """예상 VRAM 사용량 (GB). 서브클래스에서 오버라이드 가능."""
        return 0.0
