"""새로고침이 GUI 스레드를 막지 않는지, 선택이 유지되는지 검증.

회귀: 예전 refresh_models() 는 engine.refresh_status() 를 직접 불러
GUI 스레드에서 네트워크를 기다렸다. 서버가 꺼져 있거나 자동 실행 대기
(launch_wait_seconds 기본 90초)면 창이 그만큼 멈췄다.
"""
from __future__ import annotations

import json
import shutil
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.comfy.client import SystemInfo
from app.engine.comfy_engine import GeurimGyeolEngine

# 조회가 얼만큼 느려야 "블로킹"으로 판정할 수 있는가
FAKE_DELAY = 0.6

FAKE_OPTIONS = {
    "diffusion_models": ["unetA.safetensors", "unetB.safetensors"],
    "text_encoders": ["clip.safetensors"],
    "vae": ["vae.safetensors"],
    "loras": ["lora.safetensors"],
    "checkpoints": [],
}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def slow_engine(qapp, tmp_path, monkeypatch, project_root):
    """네트워크 조회가 FAKE_DELAY 만큼 걸리는 MainWindow 를 만들어 준다."""

    def _fake_status(self, allow_launch=True):
        time.sleep(FAKE_DELAY)
        self.system_info = SystemInfo(
            online=True, comfyui_version="0.0.0-fake", device_name="FAKE GPU",
            vram_total_gb=8.0, vram_free_gb=4.0,
        )
        return self.system_info

    def _fake_models(self):
        time.sleep(FAKE_DELAY)
        return dict(FAKE_OPTIONS)

    def _fake_samplers(self):
        time.sleep(FAKE_DELAY)
        return {"sampler": ["euler", "dpmpp_2m"], "scheduler": ["normal"]}

    def _build():
        import app.gui.main_window as mw

        base = json.loads(
            (project_root / "workflows" / "qwen-image-2.1-baseline.json")
            .read_text(encoding="utf-8")
        )
        prompt = json.loads(json.dumps(base))
        prompt["1"]["inputs"]["unet_name"] = FAKE_OPTIONS["diffusion_models"][0]

        root = tmp_path / "root"
        for name in ("config", "workflows", "outputs", "sessions"):
            (root / name).mkdir(parents=True, exist_ok=True)
        shutil.copy(
            project_root / "config" / "comfyui.json",
            root / "config" / "comfyui.json",
        )
        (root / "workflows" / "M.json").write_text(
            json.dumps({"name": "테스트", "prompt": prompt}, ensure_ascii=False),
            encoding="utf-8",
        )

        monkeypatch.setattr(GeurimGyeolEngine, "refresh_status", _fake_status)
        monkeypatch.setattr(GeurimGyeolEngine, "model_options", _fake_models)
        monkeypatch.setattr(GeurimGyeolEngine, "sampler_options", _fake_samplers)
        monkeypatch.setattr(mw, "ROOT", root)

        window = mw.MainWindow()
        qapp.processEvents()
        return window

    return _build


def _wait_worker(qapp, window, limit=20.0):
    """백그라운드 조회가 끝날 때까지 이벤트만 돌린다."""
    started = time.perf_counter()
    while time.perf_counter() - started < limit:
        qapp.processEvents()
        worker = window._info_worker
        if worker is None or not worker.isRunning():
            qapp.processEvents()
            break
        time.sleep(0.01)
    return time.perf_counter() - started


def test_window_appears_while_worker_still_running(slow_engine):
    """창은 조회가 끝나기 전에 뜬다 (GUI 스레드에서 기다리지 않는다).

    회귀: 예전에는 __init__ 가 engine.initialize() 로 서버 상태를
    직접 조회했다. ComfyUI 가 꺼져 있거나 자동 실행 대기(기본 90초)
    면 그만큼 창이 뜨지 않았다.

    시간 비교 대신 "조회가 아직 진행 중인지" 로 판정한다 —
    실제 UI 구성 시간은 별도로 들쭉날쭉해서 계측 기준으로 쓰기 어렵다.
    """
    w = slow_engine()
    try:
        worker = w._info_worker
        assert worker is not None, "백그라운드 조회가 시작되지 않았다"
        assert worker.isRunning(), (
            "창이 뜬 시점에 조회가 이미 끝났다 — GUI 스레드에서 기다렸다"
        )
    finally:
        w.close()


def test_refresh_models_returns_immediately(slow_engine, qapp):
    """[상태 새로고침] 은 네트워크 대기를 하지 않고 즉시 반환한다."""
    w = slow_engine()
    try:
        _wait_worker(qapp, w)          # 첫 조회는 끝낸다
        started = time.perf_counter()
        w.refresh_models()
        elapsed = time.perf_counter() - started
        # 조회 3건이 걸리면 최소 4.5초는 걸려야 한다
        assert elapsed < 0.5, (
            f"refresh_models() 가 {elapsed:.2f}초를 쥐고 있다 — GUI 스레드 블로킹"
        )
    finally:
        _wait_worker(qapp, w)
        w.close()


def test_refresh_keeps_user_model_selection(slow_engine, qapp):
    """새로고침해도 사용자가 직접 고른 모델이 되돌아가지 않는다."""
    w = slow_engine()
    try:
        _wait_worker(qapp, w)
        combo = w.model_combos["unet"]
        assert combo.count() >= 2, f"테스트 목록이 안 채워졌다: {combo.count()}"

        combo.setCurrentText("unetB.safetensors")
        assert combo.currentText() == "unetB.safetensors"

        w.refresh_models()
        _wait_worker(qapp, w)

        assert w.model_combos["unet"].currentText() == "unetB.safetensors", (
            "새로고침을 누르니 워크플로 기본값으로 되돌아갔다"
        )
    finally:
        _wait_worker(qapp, w)
        w.close()


def test_refresh_fills_models_after_worker(slow_engine, qapp):
    """백그라운드 조회가 끝나면 목록이 채워진다."""
    w = slow_engine()
    try:
        _wait_worker(qapp, w)
        assert "FAKE GPU" in w.comfy_label.text()
        assert w.model_combos["unet"].count() >= 2
        assert w.status_refresh.isEnabled(), "조회 후 버튼이 그대로 꺼져 있다"
    finally:
        _wait_worker(qapp, w)
        w.close()
