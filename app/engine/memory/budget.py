"""VRAM 예산 관리 (v0.1 §8.4, §27).

사용자 사양이 다를 수 있으므로, 어떤 VRAM을 "사용 가능한 기준"으로 삼을지
정책으로 관리한다.

정책 모드:
    "default"  - 보수적 기본값 (8 GB). 어떤 PC에서도 안전하게 동작한다.
    "auto"     - 감지된 VRAM의 90% (디바이스 여유분 확보)
    "custom"   - 사용자가 직접 지정한 값
    "unlimited" - 제한 없음 (고사양 PC 전용)

기본값이 "default"(8 GB)인 이유: 사용자가 자기 사양을 모르는 경우에도
프로그램이 동작해야 한다. 16 GB 이상 사용자는 "auto" 또는 "custom"으로
상향할 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VramLimitMode(Enum):
    """VRAM 제한 모드."""

    DEFAULT = "default"
    AUTO = "auto"
    CUSTOM = "custom"
    UNLIMITED = "unlimited"


# 보수적 기본 상한: 대다수 PC에서 안전한 값
CONSERVATIVE_VRAM_GB = 8.0
# auto 모드에서 디버그/프레임버퍼용으로 남겨둘 여유
AUTO_KEEP_FREE_GB = 0.8
# 최소한의 안전 마진
MIN_SAFETY_MARGIN_GB = 0.5


@dataclass(frozen=True)
class VramBudget:
    """계산된 VRAM 예산."""

    limit_gb: float | None
    mode: VramLimitMode
    detected_gb: float | None
    safety_margin_gb: float = MIN_SAFETY_MARGIN_GB

    @property
    def is_unlimited(self) -> bool:
        return self.limit_gb is None

    @property
    def usable_gb(self) -> float | None:
        """안전 마진을 제외한 실제 사용 가능량."""
        if self.limit_gb is None:
            return None
        return max(0.0, self.limit_gb - self.safety_margin_gb)

    def describe(self) -> str:
        """사용자에게 보여줄 설명."""
        if self.mode == VramLimitMode.UNLIMITED:
            base = "제한 없음"
        elif self.mode == VramLimitMode.AUTO:
            base = f"자동 감지 {self.limit_gb:.1f} GB"
        elif self.mode == VramLimitMode.CUSTOM:
            base = f"사용자 지정 {self.limit_gb:.1f} GB"
        else:
            base = f"기본값 {self.limit_gb:.1f} GB (보수적)"

        detected = (
            f" / 감지 GPU {self.detected_gb:.1f} GB"
            if self.detected_gb
            else ""
        )
        return f"{base}{detected}"

    def can_fit(self, required_gb: float) -> tuple[bool, str]:
        """예상 사용량이 예산과 실제 GPU 양쪽을 만족하는지 검사한다 (§8.4)."""
        if self.limit_gb is None:
            # 무제한이어도 실제 GPU VRAM은 넘을 수 없다
            if self.detected_gb and required_gb > self.detected_gb:
                return False, (
                    f"예상 VRAM {required_gb:.1f} GB이 실제 GPU VRAM "
                    f"({self.detected_gb:.1f} GB)을 초과합니다.\n"
                    f"더 작은 모델을 선택하거나 해상도를 낮추세요."
                )
            return True, f"VRAM 제한 없음 — {required_gb:.1f} GB 사용 예정"

        usable = self.usable_gb or 0.0

        # 실제 GPU VRAM을 먼저 검사한다 (예산보다 실질적인 제약)
        if self.detected_gb and required_gb > self.detected_gb:
            return False, (
                f"예상 VRAM {required_gb:.1f} GB이 실제 GPU VRAM "
                f"({self.detected_gb:.1f} GB)을 초과합니다.\n"
                f"더 작은 모델을 선택하거나 해상도를 낮추세요."
            )

        if required_gb <= usable:
            return True, (
                f"VRAM 예산 내: {required_gb:.1f} GB / 사용 가능 {usable:.1f} GB "
                f"({self.describe()})"
            )

        return False, (
            f"예상 VRAM {required_gb:.1f} GB이 사용 가능 {usable:.1f} GB을 "
            f"초과합니다.\n현재 설정: {self.describe()}\n"
            f"설정에서 VRAM 제한을 올리거나, 해상도/Steps를 낮추세요."
        )
def compute_budget(
    mode: str | VramLimitMode = VramLimitMode.DEFAULT,
    custom_gb: float | None = None,
    detected_gb: float | None = None,
    safety_margin_gb: float = MIN_SAFETY_MARGIN_GB,
) -> VramBudget:
    """VRAM 예산을 계산한다.

    Args:
        mode: 제한 모드
        custom_gb: custom 모드에서 사용할 GB 값
        detected_gb: 감지된 GPU VRAM (auto 모드에서 사용)
    """
    if isinstance(mode, str):
        try:
            mode = VramLimitMode(mode)
        except ValueError:
            mode = VramLimitMode.DEFAULT

    if mode == VramLimitMode.UNLIMITED:
        return VramBudget(None, mode, detected_gb, safety_margin_gb)

    if mode == VramLimitMode.AUTO:
        if detected_gb:
            limit = max(0.0, detected_gb - AUTO_KEEP_FREE_GB)
        else:
            # GPU를 못 쓰는 환경이면 보수적 기본값으로 되돌린다
            limit = CONSERVATIVE_VRAM_GB
        return VramBudget(limit, mode, detected_gb, safety_margin_gb)

    if mode == VramLimitMode.CUSTOM:
        limit = float(custom_gb) if custom_gb else CONSERVATIVE_VRAM_GB
        return VramBudget(limit, mode, detected_gb, safety_margin_gb)

    return VramBudget(CONSERVATIVE_VRAM_GB, mode, detected_gb, safety_margin_gb)


class VramBudgetManager:
    """VRAM 예산을 설정에서 읽어 관리한다 (v0.1 §3.4 Configuration Driven)."""

    def __init__(
        self,
        detected_gb: float | None,
        mode: str = "default",
        custom_gb: float | None = None,
        safety_margin_gb: float = MIN_SAFETY_MARGIN_GB,
    ):
        self.detected_gb = detected_gb
        self.mode = mode
        self.custom_gb = custom_gb
        self.safety_margin_gb = safety_margin_gb
        self.budget = compute_budget(mode, custom_gb, detected_gb, safety_margin_gb)

    @classmethod
    def from_config(cls, config: dict, detected_gb: float | None) -> "VramBudgetManager":
        memory = (config or {}).get("memory", {}) or {}
        return cls(
            detected_gb=detected_gb,
            mode=memory.get("vram_limit_mode", "default"),
            custom_gb=memory.get("vram_limit_gb"),
            safety_margin_gb=memory.get("safety_margin_gb", MIN_SAFETY_MARGIN_GB),
        )

    def to_config(self) -> dict:
        """현재 설정을 app_config.json 형식으로 반환한다."""
        return {
            "vram_limit_mode": self.mode,
            "vram_limit_gb": self.custom_gb if self.custom_gb else CONSERVATIVE_VRAM_GB,
            "safety_margin_gb": self.safety_margin_gb,
        }

    def set_mode(self, mode: str, custom_gb: float | None = None) -> VramBudget:
        """제한 모드를 변경한다."""
        self.mode = mode
        if custom_gb is not None:
            self.custom_gb = custom_gb
        self.budget = compute_budget(
            mode, self.custom_gb, self.detected_gb, self.safety_margin_gb
        )
        return self.budget

    @property
    def limit_gb(self) -> float | None:
        return self.budget.limit_gb

    @property
    def usable_gb(self) -> float | None:
        return self.budget.usable_gb

    def can_fit(self, required_gb: float) -> tuple[bool, str]:
        return self.budget.can_fit(required_gb)

    def describe(self) -> str:
        return self.budget.describe()