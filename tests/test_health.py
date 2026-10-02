"""자원 사용률 경고 단계 판정 테스트.

이 모듈은 PySide6 를 import 하지 않는다. 그래서 GUI 없이 검증된다.
회귀: 모든 자원에 같은 기준을 적용하면 VRAM 이 정상치에서 경고가 된다.
생성 중 VRAM 이 꽉 차는 게 정상이므로 그건 오탐이다.
"""
from __future__ import annotations

import pytest

from app.engine.health import (
    CPU, GPU, RAM, VRAM, Thresholds, UsageLevel,
    cpu_level, format_usage, gpu_level, ram_level, usage_level, vram_level,
)


# --- 임계치 자체가 의도대로인가 -----------------------------------------

def test_ram_thresholds_catch_danger_early():
    """RAM 이 진짜 위험 신호라 먼저 경고해야 한다."""
    assert RAM.warn < 80, "RAM 은 80% 전에 주의해야 한다"
    assert RAM.danger < 95, "RAM 은 95% 전에 위험이어야 한다"
    assert RAM.warn < RAM.danger


def test_vram_thresholds_do_not_warn_on_normal_load():
    """회귀: 생성 중 VRAM 이 꽉 차는 게 정상이다.

    90% 까지는 조용해야 한다. 여기서 경고하면 매 생성마다 오탐이 된다.
    """
    assert VRAM.warn > 90, "VRAM 90% 는 정상치다. 경고하면 안 된다"
    assert VRAM.danger > VRAM.warn


def test_ram_and_vram_thresholds_differ():
    """같은 기준을 두 자원에 쓰면 안 된다."""
    assert (RAM.warn, RAM.danger) != (VRAM.warn, VRAM.danger)
    assert RAM.warn < VRAM.warn, "RAM 이 더 보수적이어야 한다"


def test_gpu_near_saturation_only():
    """GPU 100% 는 정상이므로 포화 직전만 본다."""
    assert gpu_level(100.0) in (UsageLevel.WARN, UsageLevel.DANGER)
    assert gpu_level(50.0) is UsageLevel.OK


def test_cpu_warns_before_it_pins_the_gui():
    """CPU 는 100% 에 닿기 전에 알려줘야 창이 눈에 띄게 느려진다."""
    assert cpu_level(50.0) is UsageLevel.OK
    assert cpu_level(CPU.warn) is UsageLevel.WARN
    assert cpu_level(99.0) is UsageLevel.DANGER
    # RAM 보다는 늦게 — CPU 는 창을 잠그지 않으므로
    assert CPU.warn > RAM.warn


def test_all_thresholds_are_ordered():
    """기준이 뒤집힌 자원이 있으면 경고 단계가 깨진다."""
    for name, t in (("RAM", RAM), ("VRAM", VRAM), ("GPU", GPU), ("CPU", CPU)):
        assert 0 < t.warn < t.danger <= 100, f"{name} 기준이 잘못됨"


# --- 단계 판정 ------------------------------------------------------------

def test_level_boundaries_are_inclusive():
    """기준과 정확히 같아도 해당 단계로 본다."""
    t = Thresholds(warn=75.0, danger=88.0)
    assert t.level(74.9) is UsageLevel.OK
    assert t.level(75.0) is UsageLevel.WARN
    assert t.level(87.9) is UsageLevel.WARN
    assert t.level(88.0) is UsageLevel.DANGER
    assert t.level(100.0) is UsageLevel.DANGER


def test_ram_levels():
    assert ram_level(20.0) is UsageLevel.OK
    assert ram_level(60.0) is UsageLevel.OK
    assert ram_level(80.0) is UsageLevel.WARN
    assert ram_level(95.0) is UsageLevel.DANGER


def test_vram_stays_quiet_during_generation():
    """생산 중 흔한 VRAM 사용률에서 경고가 뜨지 않아야 한다."""
    for pct in (0.0, 50.0, 80.0, 90.0, 94.0):
        assert vram_level(pct) is UsageLevel.OK, f"VRAM {pct}% 에 오탐"


def test_vram_warns_only_when_almost_full():
    assert vram_level(96.0) is UsageLevel.WARN
    assert vram_level(99.0) is UsageLevel.DANGER


def test_unknown_percent_is_not_treated_as_danger():
    """회귀: 조회 실패가 곧 위험 신호가 되면 안 된다."""
    assert ram_level(None) is UsageLevel.OK
    assert vram_level(None) is UsageLevel.OK
    assert gpu_level(None) is UsageLevel.OK
    assert usage_level(None, RAM) is UsageLevel.OK


def test_zero_percent_is_ok():
    assert ram_level(0.0) is UsageLevel.OK


def test_levels_are_comparable_by_value():
    """str 로 상속했으니 로그·딕셔너리 키로 쓰기 편해야 한다."""
    assert UsageLevel.OK == "ok"
    assert UsageLevel.WARN == "warn"
    assert UsageLevel.DANGER == "danger"
    assert {UsageLevel.OK: 1}[UsageLevel.OK] == 1


# --- 표기 -----------------------------------------------------------------

def test_format_usage_with_capacity():
    assert format_usage("RAM", 60.0, 18.7, 31.2) == "RAM 18.7/31.2GB 60%"


def test_format_usage_without_capacity():
    assert format_usage("CPU", 12.0) == "CPU 12%"


def test_format_usage_unknown_shows_dash():
    """값을 모르면 빈칸 대신 '-' 로 않는다(숨기지 않는다)."""
    assert format_usage("VRAM", None) == "VRAM -"
    assert format_usage("VRAM", None, 1.0, 24.0) == "VRAM -"


def test_format_usage_without_label_has_no_leading_space():
    """회귀: 이름이 빈 칸(ModelInfo 의 RAM)은 값만 보여야 한다.

    앞에 공백이 붙으면 칸이 밀려서 상태바와 값이 어긋나 보인다.
    """
    assert format_usage("", 60.0, 18.7, 31.2) == "18.7/31.2GB 60%"
    assert not format_usage("", 60.0).startswith(" ")
    assert format_usage("", None) == "-"


def test_format_usage_ignores_zero_total():
    """total 이 0 이면 나누기 대신 백분만 보여준다."""
    assert format_usage("VRAM", 10.0, 1.0, 0.0) == "VRAM 10%"


def test_format_usage_rounds_percent():
    assert format_usage("RAM", 60.4, 18.7, 31.2) == "RAM 18.7/31.2GB 60%"
    assert format_usage("RAM", 60.6, 18.7, 31.2) == "RAM 18.7/31.2GB 61%"
