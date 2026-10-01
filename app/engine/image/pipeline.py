from __future__ import annotations
from pathlib import Path
from typing import Callable

from .base import ImageModelAdapter, GenerationResult
from .adapters import SD15Adapter, SDXLAdapter, SD3Adapter, FluxAdapter


class ImagePipelineManager:
    """Native Diffusers pipeline manager with Adapter selection (v0.1 §17).

    The process owns the pipeline; no external server.
    Selects the correct ImageModelAdapter based on architecture.
    """

    _ADAPTERS: dict[str, type[ImageModelAdapter]] = {
        "sd15": SD15Adapter,
        "sd21": SD15Adapter,
        "sdxl": SDXLAdapter,
        "sd3": SD3Adapter,
        "flux": FluxAdapter,
    }

    def __init__(self, hardware, memory, logger, budget=None):
        self.hardware = hardware
        self.memory = memory
        self.logger = logger
        self.budget = budget
        self._adapter: ImageModelAdapter | None = None
        self._current_arch: str | None = None
        self.strategy = None
        self.reduced_settings: dict | None = None

    def supported_architectures(self) -> list[str]:
        return list(self._ADAPTERS.keys())

    def can_handle(self, architecture: str) -> bool:
        return architecture in self._ADAPTERS

    def estimate_memory(self, architecture: str) -> float:
        """예상 VRAM (GB) for the given architecture."""
        adapter_cls = self._ADAPTERS.get(architecture)
        if adapter_cls is None:
            return 0.0
        return adapter_cls(self.hardware, self.logger).estimate_memory()

    def check_vram(self, architecture: str) -> tuple[bool, str]:
        """OOM Protection (v0.1 §8.4).

        예산 정책(기본 8GB / 자동 감지 / 사용자 지정 / 제한 없음)을 적용하고,
        실제로 남은 VRAM도 함께 고려한다.
        """
        est = self.estimate_memory(architecture)
        if not est:
            return True, "예상 VRAM 정보 없음 — 계속 진행"

        # 1) 예산 정책 검사
        if self.budget is not None:
            ok, message = self.budget.can_fit(est)
            if not ok:
                return False, message
            policy_message = message
        else:
            policy_message = ""

        # 2) 실제 남은 VRAM 검사
        try:
            import torch

            if not torch.cuda.is_available():
                return True, "CPU 모드 — VRAM 제한 없음"

            free, total = torch.cuda.mem_get_info()
            free_gb = free / 1024**3
            total_gb = total / 1024**3

            margin = self.budget.safety_margin_gb if self.budget else 0.5
            if est + margin > free_gb:
                if est > total_gb:
                    return False, (
                        f"예상 VRAM 사용량 ({est:.1f} GB)이 전체 VRAM "
                        f"({total_gb:.1f} GB)을 초과합니다."
                    )
                return False, (
                    f"예상 VRAM 사용량 ({est:.1f} GB) + 여유 ({margin:.1f} GB) "
                    f"이 사용 가능 VRAM ({free_gb:.1f} GB)을 초과합니다. "
                    f"해상도를 낮추거나 Steps를 줄이세요."
                )

            suffix = f" ({policy_message})" if policy_message else ""
            return True, f"VRAM OK: {est:.1f} GB / {free_gb:.1f} GB 사용 가능{suffix}"
        except Exception:
            return True, policy_message or "VRAM 확인 불가 — 계속 진행"

    def plan_strategy(
        self,
        architecture: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = 30,
    ):
        """메모리 전략을 결정한다 (v0.1 §8.2).

        VRAM에 다 안 들어오면 시스템 RAM으로 넘기는 전략을 자동 선택한다.
        """
        from ..memory.strategy import decide_strategy

        required = self.estimate_memory(architecture)
        budget = self.budget.limit_gb if self.budget else None
        detected = self.hardware.vram_gb
        return decide_strategy(
            required_vram_gb=required,
            vram_budget_gb=budget,
            vram_detected_gb=detected,
            width=width,
            height=height,
            steps=steps,
        )

    def load(self, model_path: Path, architecture: str, strategy=None) -> None:
        """Adapter 선택 후 모델 로드 + OOM 사전 검증.

        Args:
            strategy: MemoryStrategy. None이면 자동 결정.
        """
        if not self.can_handle(architecture):
            raise RuntimeError(
                f"지원하지 않는 아키텍처: {architecture}. "
                f"지원: {self.supported_architectures()}"
            )

        if strategy is None:
            strategy = self.plan_strategy(architecture)
        self.strategy = strategy

        if strategy.tier.value == "impossible":
            raise RuntimeError(f"메모리 부족: {strategy.reason}")

        ok, msg = self.check_vram(architecture)
        self.logger.info("VRAM check: %s", msg)

        adapter_cls = self._ADAPTERS[architecture]
        self._adapter = adapter_cls(self.hardware, self.logger)
        self._current_arch = architecture

        # RAM도 모자라면 전략이 제안한 낮은 설정을 사용한다
        if strategy.suggested_width:
            self.reduced_settings = {
                "width": strategy.suggested_width,
                "height": strategy.suggested_height,
                "steps": strategy.suggested_steps,
            }
            self.logger.info("메모리 절약 설정 적용: %s", self.reduced_settings)
        else:
            self.reduced_settings = None

        self._adapter.load(model_path, offload_mode=strategy.offload)
        self.logger.info("메모리 전략: %s", strategy.describe())

    @property
    def adapter(self) -> ImageModelAdapter | None:
        return self._adapter

    @property
    def loaded_path(self) -> Path | None:
        return self._adapter.loaded_path if self._adapter else None

    def generate(
        self,
        prompt: str,
        negative: str,
        width: int,
        height: int,
        steps: int,
        cfg: float,
        seed: int,
        progress: Callable[[int], None] | None = None,
    ) -> tuple:
        """Delegate generation to the active adapter."""
        if self._adapter is None:
            raise RuntimeError("Image model is not loaded")
        result: GenerationResult = self._adapter.generate(
            prompt, negative, width, height, steps, cfg, seed, progress
        )
        return result.image, result.seed

    def unload(self) -> None:
        """Unloading the pipeline and cleaning memory."""
        if self._adapter:
            self._adapter.unload()
        self._adapter = None
        self._current_arch = None
        self.strategy = None
        self.reduced_settings = None
        self.memory.cleanup()

    def supports_negative_prompt(self) -> bool:
        if self._adapter:
            return self._adapter.supports_negative_prompt
        return True
