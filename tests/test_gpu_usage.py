"""GPU 사용률 리더 회귀 테스트.

nvidia-smi 출력 형식은 버전에 따라 '6' 또는 '6 %' 다. 둘 다 읽어야 하고,
nvidia-smi 가 없는 기기(AMD/Intel) 에서는 매초 재시도하지 않고 조용히
'지원 안 함' 으로 settle 해야 한다.
"""
from __future__ import annotations

import subprocess
import sys
import threading

import pytest

from app.gui.gpu_usage import GpuUsageReader


class _FakeProc:
    """nvidia-smi 를 흉내 낸 프로세스."""

    def __init__(self, lines, stdout_closed: bool = False):
        self.returncode = None
        self.stdout = self if False else _FakeStdout(lines)
        self.stdout_closed = stdout_closed
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def __iter__(self):
        return iter(self.stdout)

    def close(self):
        pass


class _FakeStdout(list):
    def close(self):
        pass


def _reader_with(lines, monkeypatch) -> GpuUsageReader:
    """가짜 nvidia-smi 프로세스를 붙인 리더를 만든다."""
    proc = _FakeProc(lines)

    def fake_popen(*args, **kwargs):
        return proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    reader = GpuUsageReader()
    reader.start()
    # 읽기 스레드가 끝날 때까지 기다린다
    if threading.current_thread() is not threading.main_thread():
        pass
    for _ in range(200):
        if reader.percent() is not None or not reader.available:
            break
        import time

        time.sleep(0.01)
    return reader


# ------------------------------------------------------------------ 파싱


@pytest.mark.parametrize("line,expected", [
    ("6\n", 6.0),          # nounits 형식
    ("6 %\n", 6.0),        # 단위 포함 형식
    ("  42.5 %  \n", 42.5),
    ("0\n", 0.0),
    ("100\n", 100.0),
])
def test_reads_both_output_formats(monkeypatch, line, expected):
    """'6' 과 '6 %' 둘 다 읽어야 한다."""
    reader = _reader_with([line], monkeypatch)
    assert reader.available is True
    assert reader.percent() == expected


@pytest.mark.parametrize("line", [
    "[N/A]\n",       # GPU 가 없는 경우
    "Not Supported\n",
    "\n",
    "gpu_util, name\n",
])
def test_ignores_non_numeric_lines(monkeypatch, line):
    """숫자가 아닌 줄은 사용률로 착각하지 않는다."""
    reader = _reader_with([line], monkeypatch)
    assert reader.percent() is None


def test_keeps_latest_value(monkeypatch):
    """계속 들어오는 줄 중 마지막 값이 반영된다."""
    reader = _reader_with(["10\n", "80\n", "35\n"], monkeypatch)
    assert reader.percent() == 35.0


# --------------------------------------------------------- VRAM 동시 조회

@pytest.mark.parametrize("line,percent,used,total", [
    ("6, 1024, 24576\n", 6.0, 1024.0, 24576.0),
    ("6, 1024, 24576", 6.0, 1024.0, 24576.0),     # 개행 없는 마지막 줄
    ("0, 0, 24576\n", 0.0, 0.0, 24576.0),
    ("100, 24576, 24576\n", 100.0, 24576.0, 24576.0),
    ("  42 ,  512 ,  8192  \n", 42.0, 512.0, 8192.0),
])
def test_reads_utilization_and_vram_together(monkeypatch, line, percent, used, total):
    """사용률과 VRAM 을 한 줄에서 함께 읽는다 (프로세스를 하나 더 띄우지 않기)."""
    reader = _reader_with([line], monkeypatch)
    assert reader.percent() == percent
    assert reader.vram() == (used, total)


def test_single_field_line_still_works(monkeypatch):
    """회귀: 필드가 하나뿐인 형식도 여전히 읽는다 (구버전/테스트 호환)."""
    reader = _reader_with(["6\n"], monkeypatch)
    assert reader.percent() == 6.0
    assert reader.vram() == (None, None)


def test_vram_in_gb_converts_units(monkeypatch):
    """MB 를 GB 로 바꾼다 (표시용)."""
    reader = _reader_with(["6, 1024, 24576\n"], monkeypatch)
    used, total = reader.vram_gb()
    assert used == 1.0
    assert total == 24.0


def test_vram_unknown_when_not_read_yet(monkeypatch):
    """아직 한 줄도 안 읽었으면 모르는 것으로 둔다 (숫자를 지어내지 않는다)."""
    reader = _reader_with([], monkeypatch)
    assert reader.vram() == (None, None)
    assert reader.vram_gb() == (None, None)


def test_non_numeric_vram_line_is_ignored(monkeypatch):
    """'[N/A], [N/A], [N/A]' 같은 줄은 VRAM 을 지어내지 않는다."""
    reader = _reader_with(["[N/A], [N/A], [N/A]\n"], monkeypatch)
    assert reader.percent() is None
    assert reader.vram() == (None, None)


def test_partial_numeric_line_is_ignored(monkeypatch):
    """숫자 셋이 모이면 줄 전체를 버린다 (섞여 읽으면 값이 뒤틀린다)."""
    reader = _reader_with(["6, 1024, N/A\n"], monkeypatch)
    assert reader.percent() is None
    assert reader.vram() == (None, None)


def test_vram_cleared_on_stop(monkeypatch):
    """stop() 하면 VRAM 도 함께 비워진다 (옛 값을 계속 보여주지 않는다)."""
    proc = _FakeProc(["6, 1024, 24576\n"])
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: proc)
    reader = GpuUsageReader()
    reader.start()
    assert reader.vram() != (None, None)

    reader.stop()
    assert reader.vram() == (None, None)
    assert reader.vram_gb() == (None, None)


# ------------------------------------------------------------------ 실패


def test_unavailable_when_nvidia_smi_missing(monkeypatch):
    """nvidia-smi 가 없으면 조용히 사용 불가로 정한다."""
    def boom(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(subprocess, "Popen", boom)
    reader = GpuUsageReader()
    reader.start()

    assert reader.available is False
    assert reader.percent() is None


def test_does_not_retry_every_second(monkeypatch):
    """매 초 재시도하지 않는다 (실패할 때마다 콘솔을 띄우면 곤란하다).

    상태바가 1초마다 갱신되므로 start() 를 매번 부를 수 있다.
    """
    calls = []

    def boom(*args, **kwargs):
        calls.append(1)
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(subprocess, "Popen", boom)
    reader = GpuUsageReader()
    for _ in range(5):
        reader.start()

    assert len(calls) == 1, f"시도가 {len(calls)}번이다 (1번이어야 함)"


def test_stop_is_safe_without_start(monkeypatch):
    """한 번도 시작하지 않아도 stop() 이 예외를 내면 안 된다."""
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    reader = GpuUsageReader()
    reader.stop()  # 예외가 없어야 한다
    assert reader.available is False


def test_stop_terminates_process(monkeypatch):
    """stop() 은 떠 있는 nvidia-smi 를 종료한다 (창을 닫을 때 남으면 곤란)."""
    proc = _FakeProc(["10\n"])

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: proc)
    reader = GpuUsageReader()
    reader.start()
    assert reader.available is True

    reader.stop()

    assert proc.terminated is True
    assert reader.available is False
    assert reader.percent() is None


def test_start_is_idempotent(monkeypatch):
    """이미 떠 있으면 start() 를 다시 불러도 새로 띄우지 않는다."""
    proc = _FakeProc(["10\n"])
    calls = []

    def fake_popen(*args, **kwargs):
        calls.append(1)
        return proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    reader = GpuUsageReader()
    reader.start()
    reader.start()
    reader.start()

    assert len(calls) == 1, f"프로세스를 {len(calls)}번 띄웠다"



# ------------------------------------------------------------------ 플랫폼

def test_no_window_flag_only_on_windows(monkeypatch):
    """Windows 밖에서는 창을 숨기는 플래그를 쓰지 않는다."""
    from app.gui.gpu_usage import _no_window

    monkeypatch.setattr(sys, "platform", "linux")
    assert _no_window() == 0
    monkeypatch.setattr(sys, "platform", "darwin")
    assert _no_window() == 0
