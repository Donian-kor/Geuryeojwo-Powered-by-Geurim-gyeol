"""모델 선택 — 워크플로가 지정한 모델이 설치되지 않았을 때의 동작.

회귀: ComfyUI 목록에 없는 모델을 목록의 첫 번째 파일로 조용히
대체하면, 사용자도 모르는 채 다른 모델로 생성된다. 그래서
설치 안 된 이름을 목록에 그대로 두고 빨간색·경고로 표시하며,
생성 자체를 막는다.

네트워크와 GUI 창이 필요 없도록 ComfyUI 목록·접속 상태를 통제하고
QT_QPA_PLATFORM=offscreen (conftest) 을 쓴다.
"""
from __future__ import annotations

import json
import shutil

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from app.comfy.client import ComfyClient, SystemInfo
from app.engine.comfy_engine import GeurimGyeolEngine

# ComfyUI 에 "설치되어 있는" 모델 목록 (테스트 전용 가짜 응답)
FAKE_OPTIONS = {
    "diffusion_models": ["installedA.safetensors", "installedB.safetensors"],
    "text_encoders": ["clip_installed.safetensors"],
    "vae": ["vae_installed.safetensors"],
    "loras": ["lora_installed.safetensors"],
    "checkpoints": [],
}

MISSING = "MISSING-MODEL.safetensors"
RED = "#ff6b6b"


class _StubResult:
    """엔진 generate() 를 대신하는 즉시 반환 값 (실 네트워크 차단용)."""

    success = False
    error = "테스트용 stub"
    image_path = None
    metadata: dict = {}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_window(qapp, tmp_path, monkeypatch, project_root):
    """지정한 확산 모델명을 쓰는 워크플로로 MainWindow 를 만들어 준다."""

    def _build(unet: str):
        import app.gui.main_window as mw

        base = json.loads(
            (project_root / "workflows" / "qwen-image-2.1-baseline.json")
            .read_text(encoding="utf-8")
        )
        prompt = json.loads(json.dumps(base))
        prompt["1"]["inputs"]["unet_name"] = unet
        # 나머지는 모두 설치된 것으로 맞춘다 (unet 만 판정 대상)
        prompt["2"]["inputs"]["clip_name"] = FAKE_OPTIONS["text_encoders"][0]
        prompt["3"]["inputs"]["vae_name"] = FAKE_OPTIONS["vae"][0]
        prompt["16"]["inputs"]["lora_name"] = FAKE_OPTIONS["loras"][0]

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

        # ComfyUI 목록과 접속 상태를 통제한다 (실제 서버 불필요)
        async def _fake_system_info(self):
            return SystemInfo(
                online=True,
                comfyui_version="0.0.0-test",
                device_name="TEST GPU",
                vram_total_gb=8.0,
                vram_free_gb=4.0,
            )

        # get_system_info 를 막지 않으면 MainWindow 가 실제 서버에
        # 접속하려 시도한다. ComfyUI 가 꺼져 있으면 테스트가 수십 초
        # 걸리고, 켜져 있는지에 따라 결과가 달라진다.
        monkeypatch.setattr(
            ComfyClient, "get_system_info", _fake_system_info
        )
        monkeypatch.setattr(
            GeurimGyeolEngine, "model_options",
            lambda self: dict(FAKE_OPTIONS),
        )
        monkeypatch.setattr(
            GeurimGyeolEngine, "sampler_options",
            lambda self: {"sampler": ["euler"], "scheduler": ["normal"]},
        )
        monkeypatch.setattr(
            GeurimGyeolEngine, "online", property(lambda self: True)
        )
        monkeypatch.setattr(mw, "ROOT", root)

        window = mw.MainWindow()
        qapp.processEvents()
        # 서버 조회는 백그라운드 워커가 하므로, 끝날 때까지 기다려
        # 위젯에 반영시킨 뒤 돌려준다 (그대로 두면 목록이 비어 있다)
        if window._info_worker is not None:
            window._info_worker.wait(5000)
        for _ in range(5):
            qapp.processEvents()
        return window

    return _build


def _color(combo, index: int):
    brush = combo.itemData(index, Qt.ForegroundRole)
    return brush.color().name() if brush is not None else None


def test_missing_model_is_kept_not_substituted(make_window):
    """설치 안 된 모델을 목록의 다른 파일로 대체하지 않는다."""
    w = make_window(MISSING)
    try:
        combo = w.model_combos["unet"]
        assert combo.currentText() == MISSING, (
            f"워크플로 지정값이 바뀌었다: {combo.currentText()}"
        )
        # 대체해 버렸다면 지정값이 목록에서 사라진다
        assert combo.count() == 3
        assert combo.findText("installedA.safetensors") >= 0
        assert combo.findText("installedB.safetensors") >= 0
        assert combo.findText(MISSING) >= 0
    finally:
        w.close()


def test_missing_model_is_painted_red(make_window):
    """설치 안 된 항목은 빨간색으로 표시되고 이유를 알린다."""
    w = make_window(MISSING)
    try:
        combo = w.model_combos["unet"]
        index = combo.findText(MISSING)
        assert _color(combo, index) == RED

        installed_index = combo.findText("installedA.safetensors")
        assert _color(combo, installed_index) != RED, (
            "설치된 모델까지 빨갛게 표시되었다"
        )
        assert "설치되어 있지" in combo.itemData(index, Qt.ToolTipRole)
    finally:
        w.close()


def test_missing_model_shows_warning_label(make_window):
    """모델 탭의 경고 라벨에 무엇이 없는지 표시한다."""
    w = make_window(MISSING)
    try:
        assert w._missing_models() == [("unet", MISSING)]
        assert not w._model_warning.isHidden(), "경고 라벨이 숨겨져 있다"
        assert MISSING in w._model_warning.text()
    finally:
        w.close()


def test_picking_installed_model_clears_warning(make_window):
    """설치된 모델로 바꾸면 경고가 사라진다."""
    w = make_window(MISSING)
    try:
        assert not w._model_warning.isHidden()
        combo = w.model_combos["unet"]
        combo.setCurrentIndex(combo.findText("installedA.safetensors"))
        assert w._missing_models() == []
        assert w._model_warning.isHidden(), "설치된 모델인데 경고가 남아 있다"
    finally:
        w.close()


def test_generation_is_blocked_when_model_missing(make_window, monkeypatch):
    """설치 안 된 모델이면 생성을 시작하기 전에 막는다."""
    w = make_window(MISSING)
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda parent, title, text, *a, **k: captured.append((title, text)),
    )
    try:
        w.prompt.setPlainText("테스트 프롬프트")
        w.start()
        assert captured, "설치 안 된 모델인데 생성이 시작되었다"
        assert captured[0][0] == "설치되지 않은 모델"
        assert MISSING in captured[0][1]
        assert w.worker is None, "Worker 가 만들어졌다"
    finally:
        w.close()


def test_installed_model_generation_is_not_blocked(make_window, monkeypatch):
    """모두 설치되어 있으면 경고 없이 생성으로 넘어간다."""
    warnings: list = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda parent, title, text, *a, **k: warnings.append((title, text)),
    )
    # 실 생성을 막기 위해 엔진을 즉시 반환하는 대역으로 대체한다.
    # (차단 조건이 '모델 설치 여부'임만 확인하는 것이 목적이다)
    monkeypatch.setattr(
        GeurimGyeolEngine, "generate",
        lambda self, req, on_progress=None: _StubResult(),
    )
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)

    w = make_window("installedA.safetensors")
    try:
        assert w._missing_models() == []
        assert w._model_warning.isHidden()
        w.prompt.setPlainText("테스트 프롬프트")
        w.start()
        assert not warnings, f"설치된 모델인데 경고가 떴다: {warnings}"
        assert w.worker is not None, "생성 Worker 가 시작되지 않았다"
        w.worker.wait(5000)
    finally:
        if w.worker is not None:
            w.worker.wait(5000)
        w.close()
# --- 체크포인트(SD 계열) ------------------------------------------------

# 회귀 근거:
# Model 탭의 모델 콤보는 4개(unet/clip/vae/lora) 로 고정돼 있었다.
# 그 결과 CheckpointLoaderSimple 을 쓰는 워크플로를 등록하면
# 'checkpoint' 파라미터가 생겨도 고를 칸이 없어서
# 설치돼 있는 체크포인트를 하나도 고를 수 없었다.

SD_OPTIONS = {
    "checkpoints": ["sdA.safetensors", "sdB.safetensors"],
    "diffusion_models": [],
    "text_encoders": [],
    "vae": [],
    "loras": [],
}


@pytest.fixture
def make_sd_window(qapp, tmp_path, monkeypatch, project_root):
    """체크포인트를 쓰는(SD 계열) 워크플로로 MainWindow 를 만들어 준다."""

    def _build(checkpoint: str):
        import app.gui.main_window as mw

        prompt = {
            "1": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": checkpoint}},
            "2": {"class_type": "CLIPTextEncode",
                  "inputs": {"text": "고양이", "clip": ["1", 1]}},
            "3": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": 512, "height": 512, "batch_size": 1}},
            "4": {"class_type": "KSampler",
                  "inputs": {"seed": 1, "steps": 20, "cfg": 7.0,
                             "sampler_name": "euler", "scheduler": "normal",
                             "denoise": 1, "model": ["1", 0],
                             "positive": ["2", 0], "negative": ["2", 0],
                             "latent_image": ["3", 0]}},
            "5": {"class_type": "VAEDecode",
                  "inputs": {"samples": ["4", 0], "vae": ["1", 2]}},
            "6": {"class_type": "SaveImage", "inputs": {"images": ["5", 0]}},
        }
        root = tmp_path / "sdroot"
        for name in ("config", "workflows", "outputs", "sessions"):
            (root / name).mkdir(parents=True, exist_ok=True)
        shutil.copy(project_root / "config" / "comfyui.json",
                    root / "config" / "comfyui.json")
        (root / "workflows" / "S.json").write_text(
            json.dumps({"name": "SD", "prompt": prompt}, ensure_ascii=False),
            encoding="utf-8",
        )

        async def _fake_system_info(self):
            return SystemInfo(
                online=True, comfyui_version="0.0.0-test",
                device_name="TEST GPU", vram_total_gb=8.0, vram_free_gb=4.0,
            )

        monkeypatch.setattr(ComfyClient, "get_system_info", _fake_system_info)
        monkeypatch.setattr(
            GeurimGyeolEngine, "model_options", lambda self: dict(SD_OPTIONS)
        )
        monkeypatch.setattr(
            GeurimGyeolEngine, "sampler_options",
            lambda self: {"sampler": ["euler"], "scheduler": ["normal"]},
        )
        monkeypatch.setattr(
            GeurimGyeolEngine, "online", property(lambda self: True)
        )
        monkeypatch.setattr(mw, "ROOT", root)

        window = mw.MainWindow()
        qapp.processEvents()
        if window._info_worker is not None:
            window._info_worker.wait(5000)
        for _ in range(5):
            qapp.processEvents()
        return window

    return _build


def test_checkpoint_combo_exists(make_sd_window):
    w = make_sd_window(SD_OPTIONS["checkpoints"][0])
    try:
        assert "checkpoint" in w.model_combos
    finally:
        w.close()


def test_checkpoint_combo_lists_installed_models(make_sd_window):
    w = make_sd_window("sdA.safetensors")
    try:
        combo = w.model_combos["checkpoint"]
        assert combo.isEnabled(), "체크포인트 고르는 칸이 비활성이다"
        items = [combo.itemText(i) for i in range(combo.count())]
        assert "sdA.safetensors" in items and "sdB.safetensors" in items
        assert combo.currentText() == "sdA.safetensors"
    finally:
        w.close()


def test_unet_combo_disabled_for_sd_workflow(make_sd_window):
    """SD 워크플로는 확산 모델 폴더를 보지 않는다."""
    w = make_sd_window("sdA.safetensors")
    try:
        combo = w.model_combos["unet"]
        assert combo.isEnabled() is False
        assert combo.itemText(0) == "(사용 안 함)"
    finally:
        w.close()


def test_checkpoint_combo_disabled_for_qwen_workflow(make_window):
    """회귀: Qwen 워크플로에서는 체크포인트 칸이 꺼져 있어야 한다."""
    w = make_window("installedA.safetensors")
    try:
        combo = w.model_combos["checkpoint"]
        assert combo.isEnabled() is False
        assert combo.itemText(0) == "(사용 안 함)"
    finally:
        w.close()

