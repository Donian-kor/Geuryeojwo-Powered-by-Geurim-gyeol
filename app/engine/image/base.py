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
        self.offload_mode = None
        self._offload_applied = False

    @abstractmethod
    def load(self, model_path: Path, offload_mode=None) -> None:
        """모델을 메모리에 로드한다.

        Args:
            model_path: 모델 파일 또는 디렉토리
            offload_mode: OffloadMode. None 또는 NONE이면 VRAM 전체 사용.
        """

    def _place_on_device(self, offload_mode=None) -> str:
        """파이프라인을 메모리에 배치하고 적용된 방식을 문자열로 반환한다.

        offload를 쓸 때는 `.to(device)`를 호출하면 안 된다.
        두 가지를 같이 쓰면 diffusers가 오류를 낸다 (v0.1 §8.2).
        """
        from ..memory.strategy import OffloadMode

        device = self.hardware.device
        mode = offload_mode or OffloadMode.NONE
        self.offload_mode = mode

        if mode == OffloadMode.NONE:
            self.pipe = self.pipe.to(device)
            self._enable_attention_slicing()
            self._offload_applied = False
            return "vram_full"

        # offload 계열은 .to(device)를 호출하면 안 된다
        method = {
            OffloadMode.MODEL_CPU: "enable_model_cpu_offload",
            OffloadMode.GROUP: "enable_group_offload",
            OffloadMode.SEQUENTIAL: "enable_sequential_cpu_offload",
        }.get(mode)

        if not method or not hasattr(self.pipe, method):
            # 지원하지 않으면 VRAM 전체 로드로 되돌린다
            self.logger.warning(
                "%s 미지원 — VRAM 전체 로드로 대체합니다", mode.value
            )
            self.pipe = self.pipe.to(device)
            self._enable_attention_slicing()
            self.offload_mode = OffloadMode.NONE
            self._offload_applied = False
            return "vram_full_fallback"

        try:
            getattr(self.pipe, method)()
            self._offload_applied = True
            self.logger.info("메모리 절약: %s 적용 (%s)", mode.value, self.pipe.__class__.__name__)
            return mode.value
        except Exception as exc:
            self.logger.warning("%s 적용 실패 (%s) — VRAM 전체 로드", mode.value, exc)
            self.pipe = self.pipe.to(device)
            self._enable_attention_slicing()
            self.offload_mode = OffloadMode.NONE
            self._offload_applied = False
            return "vram_full_fallback"

    def _enable_attention_slicing(self) -> None:
        """Attention slicing을 켠다 (VRAM 절감)."""
        if hasattr(self.pipe, "enable_attention_slicing"):
            self.pipe.enable_attention_slicing()

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
        if self.pipe is not None and self._offload_applied:
            # offload 훅을 제거해야 가중치가 RAM에서 해제된다
            for method in ("disable_model_cpu_offload", "disable_group_offload"):
                if hasattr(self.pipe, method):
                    try:
                        getattr(self.pipe, method)()
                    except Exception:
                        pass
                    break
        self.pipe = None
        self.loaded_path = None
        self.offload_mode = None
        self._offload_applied = False

    def estimate_memory(self) -> float:
        """예상 VRAM 사용량 (GB). 서브클래스에서 오버라이드 가능."""
        return 0.0
