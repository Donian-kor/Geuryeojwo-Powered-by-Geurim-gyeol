"""메모리 전략 결정 (v0.1 §8.2, §8.4).

"VRAM을 0으로 만드는 것이 목표가 아니다. 다음 단계에서 필요한 메모리를
확보할 수 있는 상태인지 확인하고 보장하는 것이 목표"다 (v0.1 §8.2).

ComfyUI의 SHARED VRAMState처럼, VRAM이 부족하면 시스템 RAM으로 넘기는
전략을 3단계로 결정한다.

    TIER_FULL      모델 전체를 VRAM에 올림 (가장 빠름)
    TIER_OFFLOAD   가중치를 RAM에 두고 필요할 때만 VRAM으로 (느림, 되돌아옴)
    TIER_REDUCED   offload + 해상도/steps 축소 (가장 느림, 하지만 동작)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import psutil


class OffloadMode(Enum):
    """가중치 오프로드 방식 (v0.1 §3.3)."""

    NONE = "none"
    MODEL_CPU = "model_cpu"
    GROUP = "group"
    SEQUENTIAL = "sequential"


class MemoryTier(Enum):
    """메모리 전략 단계."""

    FULL = "full"
    OFFLOAD = "offload"
    REDUCED = "reduced"
    IMPOSSIBLE = "impossible"


# offload 시 RAM 필요량 배수 (가중치 + 런타임 오버헤드)
RAM_OVERHEAD_FACTOR = 1.5
# offload 시 VRAM 요구량 중 RAM이 감당해야 하는 비율.
# enable_model_cpu_offload를 쓰면 가중치는 RAM에 남고 VRAM에는
# Activations만 올라가므로, 전체 VRAM 요구량을 RAM 기준으로 잡으면
# 과도하게 엄격해져 실행 가능한 경우를 거절하게 된다.
OFFLOAD_RAM_DUTY_RATIO = 0.5
# RAM에도 여유를 남기기 위한 최소 확보량
RAM_RESERVE_GB = 2.0
# TIER_REDUCED에서 적용할 비율
REDUCED_RESOLUTION_RATIO = 0.75
REDUCED_STEPS_RATIO = 0.7


def reduced_ram_need(vram_gb: float) -> float:
    """offload 상태에서 특정 VRAM 요구량이 필요로 하는 RAM (GB)."""
    return vram_gb * RAM_OVERHEAD_FACTOR * OFFLOAD_RAM_DUTY_RATIO + RAM_RESERVE_GB
@dataclass(frozen=True)
class MemoryStrategy:
    """결정된 메모리 전략."""

    tier: MemoryTier
    offload: OffloadMode
    reason: str
    required_vram_gb: float = 0.0
    required_ram_gb: float = 0.0
    vram_budget_gb: float | None = None
    vram_detected_gb: float | None = None
    ram_available_gb: float | None = None
    suggested_width: int | None = None
    suggested_height: int | None = None
    suggested_steps: int | None = None

    @property
    def uses_offload(self) -> bool:
        return self.offload != OffloadMode.NONE

    @property
    def suggested_resolution(self) -> str:
        """제안된 해상도 문자열 (없으면 빈 문자열)."""
        if not self.suggested_width or not self.suggested_height:
            return ""
        return f"{self.suggested_width}x{self.suggested_height}"

    @property
    def speed_hint(self) -> str:
        """사용자에게 보여줄 속도 안내."""
        if self.tier == MemoryTier.FULL:
            return "최고 속도"
        if self.offload == OffloadMode.GROUP:
            return "약 10% 느림 (메모리 절약)"
        if self.offload == OffloadMode.MODEL_CPU:
            return "약 20-30% 느림 (메모리 절약)"
        if self.offload == OffloadMode.SEQUENTIAL:
            return "매우 느림 (극한 절약)"
        return "-"

    def describe(self) -> str:
        """한 줄 설명."""
        if self.tier == MemoryTier.FULL:
            return f"VRAM 전체 사용 — {self.reason}"
        if self.tier == MemoryTier.REDUCED:
            return f"메모리 절약 모드 ({self.speed_hint}) — {self.reason}"
        if self.tier == MemoryTier.OFFLOAD:
            return f"시스템 RAM 사용 ({self.speed_hint}) — {self.reason}"
        return f"실행 불가 — {self.reason}"

    def to_dict(self) -> dict:
        return {
            "tier": self.tier.value,
            "offload": self.offload.value,
            "reason": self.reason,
            "required_vram_gb": self.required_vram_gb,
            "required_ram_gb": self.required_ram_gb,
            "speed_hint": self.speed_hint,
        }


def _round_to_multiple(value: int, multiple: int = 8) -> int:
    """해상도를 8의 배수로 맞춘다 (latent 격자 규칙)."""
    return max(multiple, int(value) // multiple * multiple)


def current_ram_available_gb() -> float | None:
    """실월 가능 시스템 RAM (GB). 실패 시 None."""
    try:
        return psutil.virtual_memory().available / 1024**3
    except Exception:
        return None


def decide_strategy(
    required_vram_gb: float,
    vram_budget_gb: float | None,
    vram_detected_gb: float | None,
    ram_available_gb: float | None = None,
    preferred_offload: OffloadMode = OffloadMode.MODEL_CPU,
    width: int = 1024,
    height: int = 1024,
    steps: int = 30,
) -> MemoryStrategy:
    """VRAM/RAM 상태를 보고 실행 전략을 결정한다 (v0.1 §8.2).

    Args:
        required_vram_gb: 모델 전체를 VRAM에 올릴 때 필요한 VRAM
        vram_budget_gb: 사용자가 정한 VRAM 예산 (None = 무제한)
        vram_detected_gb: 물리적으로 설치된 VRAM
        ram_available_gb: 실측 가용 시스템 RAM (None이면 조회)
        preferred_offload: 사용자가 선호하는 offload 방식
    """
    if ram_available_gb is None:
        ram_available_gb = current_ram_available_gb()

    required_ram = required_vram_gb * RAM_OVERHEAD_FACTOR
    common = {
        "required_vram_gb": required_vram_gb,
        "required_ram_gb": round(required_ram, 1),
        "vram_budget_gb": vram_budget_gb,
        "vram_detected_gb": vram_detected_gb,
        "ram_available_gb": ram_available_gb,
    }

    # GPU가 없는 환경은 CPU 폴백이므로 offload가 의미 없다
    if not vram_detected_gb:
        return MemoryStrategy(
            tier=MemoryTier.FULL,
            offload=OffloadMode.NONE,
            reason="GPU 없음 — CPU 모드",
            **common,
        )

    # 1단계: VRAM만으로 충분한가?
    limit = vram_budget_gb if vram_budget_gb is not None else vram_detected_gb
    margin = 0.5
    if required_vram_gb + margin <= limit:
        return MemoryStrategy(
            tier=MemoryTier.FULL,
            offload=OffloadMode.NONE,
            reason=f"{required_vram_gb:.1f} GB < 예산 {limit:.1f} GB",
            **common,
        )

    # 2단계: RAM에 담을 수 있는가?
    # offload를 쓰면 가중치 대부분이 RAM에 머물고 VRAM에는 Activations만
    # 올라가므로, VRAM 요구량 전체를 RAM 기준으로 잡으면 과도하게 엄격하다.
    # 실제로는 VRAM 요구량의 일부만 RAM에서 감당하면 되므로 0.5배로 산정한다.
    ram_need = required_ram * OFFLOAD_RAM_DUTY_RATIO + RAM_RESERVE_GB
    if ram_available_gb is not None and ram_need <= ram_available_gb:
        return MemoryStrategy(
            tier=MemoryTier.OFFLOAD,
            offload=preferred_offload,
            reason=(
                f"{required_vram_gb:.1f} GB가 VRAM 예산을 초과해 "
                f"시스템 RAM({ram_available_gb:.0f} GB)으로 넘깁니다"
            ),
            **common,
        )

    # 2.5단계: 해상도를 낮추면 offload로도 가능해지는가?
    if ram_available_gb is not None:
        reduced_vram = required_vram_gb * REDUCED_RESOLUTION_RATIO
        reduced_ram = reduced_ram_need(reduced_vram)
        if reduced_vram + margin <= limit and reduced_ram <= ram_available_gb:
            return MemoryStrategy(
                tier=MemoryTier.REDUCED,
                offload=preferred_offload,
                reason=(
                    f"VRAM 예산({limit:.1f} GB)에 담기 어려워 해상도를 "
                    f"{int(REDUCED_RESOLUTION_RATIO * 100)}%로 낮추고 "
                    f"시스템 RAM을 함께 사용합니다"
                ),
                suggested_width=_round_to_multiple(width * REDUCED_RESOLUTION_RATIO),
                suggested_height=_round_to_multiple(height * REDUCED_RESOLUTION_RATIO),
                suggested_steps=max(1, int(steps * REDUCED_STEPS_RATIO)),
                **common,
            )

    return MemoryStrategy(
        tier=MemoryTier.IMPOSSIBLE,
        offload=OffloadMode.NONE,
        reason=(
            f"VRAM({vram_detected_gb:.1f} GB)과 시스템 RAM"
            f"({ram_available_gb or 0:.0f} GB) 모두 부족합니다. "
            f"더 작은 모델을 선택하세요."
        ),
        **common,
    )
