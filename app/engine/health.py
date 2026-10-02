"""자원 사용률의 경고 단계 판정.

GUI 는 '무슨 색으로 칠할까'만 알면 되므로 판정 규칙은 여기 둔다.
PySide6 를 import 하지 않는다 — 그래서 GUI 없이 검증된다.

단계가 세 개고 기준이 자원마다 다른 이유
----------------------------------------
한계선을 넘는다고 곧바로 빨강으로 칠하면 안 된다.

VRAM 은 거의 꽉 찰 때가 **정상**이다. 이미지를 만드는 중이면 원래 그렇다.
여기에 RAM 과 같은 기준을 적용하면 생성할 때마다 오탐이 뜬다.

진짜 위험 신호는 **RAM** 이다. 31GB 머신에서 Qwen-Image 2.1 을 올리면
확산 모델 4GB + 텍스트 인코더 8.9GB + VAE 로 한 번에 약 13GB 가 필요해서
ComfyUI 가 메모리 고갈로 먼저 죽는다. 죽은 로그에는 트레이스백 없이
'Using RAM pressure cache' 만 남고, Comfy Desktop 가 다시 띄운다.

그래서 자원은 종류마다 다른 기준을 갖는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UsageLevel(str, Enum):
    """사용률 경고 단계."""

    OK = "ok"
    WARN = "warn"
    DANGER = "danger"


@dataclass(frozen=True)
class Thresholds:
    """경고 단계 기준 (사용률 %).

    Attributes:
        warn: 이 이상이면 주의.
        danger: 이 이상이면 위험.
    """

    warn: float
    danger: float

    def level(self, percent: float) -> UsageLevel:
        """사용률(%) 을 단계로 바꾼다."""
        if percent >= self.danger:
            return UsageLevel.DANGER
        if percent >= self.warn:
            return UsageLevel.WARN
        return UsageLevel.OK


# RAM 이 진짜 위험 신호다. ComfyUI 가 여기서 죽는다.
RAM = Thresholds(warn=75.0, danger=88.0)

# VRAM 은 꽉 차는 게 정상이다. 거의 찼을 때만 경고한다.
VRAM = Thresholds(warn=95.0, danger=98.0)

# GPU 사용률도 100% 가 정상이므로 포화 직전만 본다.
GPU = Thresholds(warn=90.0, danger=99.0)

# CPU 는 빠듯할수록 조용해지긴 하지만, 100% 에 가깝게 붙어 있으면
# GUI 가 눈에 띄게 느려진다. 그 전에 알려주는 편이 낫다.
CPU = Thresholds(warn=85.0, danger=95.0)


def usage_level(percent: float | None, thresholds: Thresholds) -> UsageLevel:
    """사용률로부터 경고 단계를 정한다.

    percent 가 None 이면 '모르는 것' 이므로 경고하지 않는다.
    아는 것만 경고해야 한다. 모르는 값을 위험으로 보면
    조회 실패만으로 사용자가 경고를 받게 된다.
    """
    if percent is None:
        return UsageLevel.OK
    return thresholds.level(float(percent))


def ram_level(percent: float | None) -> UsageLevel:
    """시스템 RAM 사용률의 단계."""
    return usage_level(percent, RAM)


def vram_level(percent: float | None) -> UsageLevel:
    """VRAM 사용률의 단계."""
    return usage_level(percent, VRAM)


def gpu_level(percent: float | None) -> UsageLevel:
    """GPU 사용률의 단계."""
    return usage_level(percent, GPU)


def cpu_level(percent: float | None) -> UsageLevel:
    """CPU 사용률의 단계."""
    return usage_level(percent, CPU)


def format_usage(
    label: str,
    percent: float | None,
    used: float | None = None,
    total: float | None = None,
) -> str:
    """상태바에 쓸 한 줄을 만든다.

    용량을 함께 알면 '18.7/31.2GB 60%' 처럼 보여준다.
    모르는 값은 'VRAM -' 처럼 숨기지 않고 그대로 비워 둔다.

    Args:
        label: 칸 이름. 빈 문자열이면 이름 없이 값만 (ModelInfo 의 RAM 칸).
    """
    if percent is None:
        return f"{label} -" if label else "-"
    if used is not None and total is not None and total > 0:
        body = f"{used:.1f}/{total:.1f}GB {percent:.0f}%"
    else:
        body = f"{percent:.0f}%"
    # 이름이 없으면 앞에 공백이 붙지 않게 한다 (칸이 밀린다)
    return f"{label} {body}" if label else body
