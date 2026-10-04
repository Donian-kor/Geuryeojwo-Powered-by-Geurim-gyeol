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
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

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

# 백그라운드 조회의 결과가 목록에 반영될 때까지 기다리는 상한.
# 워커는 네트워크 I/O 를 하므로 PC 사양과 ComfyUI 응답에 따라 시간이
# 들쭉날쭉하다. 여기서 대기를 고정하면 워커가 아직일 때 테스트가 시작해
# 목록이 비어 있고, 그 결과가 '설치 안 된 모델을 목록에서 지웠다' 는
# 잘못된 실패로 보인다. (실제로 그랬다)
_WAIT_LIMIT_SECONDS = 30.0


def _wait_models(window, qapp) -> None:
    """백그라운드 조회가 끝나 목록이 채워질 때까지 기다린다.

    워커가 끝났다는 것과 시그널이 위젯에 반영됐다는 것은 별개다.
    시그널은 GUI 스레드에서 처리되므로 둘 다 확인해야 한다.

    Args:
        window: MainWindow
        qapp: QApplication (이벤트를 펄 때 쓴다)
    """
    worker = window._info_worker
    if worker is None:
        return
    deadline = time.monotonic() + _WAIT_LIMIT_SECONDS
    while worker.isRunning() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    worker.wait(int(_WAIT_LIMIT_SECONDS * 1000))
    # 시그널이 반영될 때까지 이벤트를 돌린다
    for _ in range(20):
        if window._comfy_models:
            break
        qapp.processEvents()
        time.sleep(0.01)


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
            (project_root / "workflows" / "base" / "qwen-image.json")
            .read_text(encoding="utf-8")
        )
        prompt = base.get("prompt", base)
        prompt = json.loads(json.dumps(prompt))
        prompt["1"]["inputs"]["unet_name"] = unet
        # 나머지는 모두 설치된 것으로 맞춘다 (unet 만 판정 대상)
        prompt["2"]["inputs"]["clip_name"] = FAKE_OPTIONS["text_encoders"][0]
        prompt["3"]["inputs"]["vae_name"] = FAKE_OPTIONS["vae"][0]
        for node_id, node in prompt.items():
            if "lora_name" in node.get("inputs", {}):
                node["inputs"]["lora_name"] = FAKE_OPTIONS["loras"][0]

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
        # CLIP 타입 선택지도 서버를 부른다. 이러지 않으면 테스트가 실제
        # ComfyUI 에 접속해 결과가 서버 상태에 따라 달라진다.
        monkeypatch.setattr(
            GeurimGyeolEngine, "input_options",
            lambda self, node_class, input_name: ["qwen_image", "lumina2"],
        )
        monkeypatch.setattr(
            GeurimGyeolEngine, "sampler_options",
            lambda self: {"sampler": ["euler"], "scheduler": ["normal"]},
        )
        monkeypatch.setattr(
            GeurimGyeolEngine, "online", property(lambda self: True)
        )
        # 인핸서 조회는 실제 서버의 /object_info(2.5MB) 를 부른다. 막지 않으면
        # 워커가 PC 속도·서버 응답에 따라 5초 넘게 걸려 실행마다 결과가 달라진다.
        monkeypatch.setattr(
            GeurimGyeolEngine, "enhancer_status",
            lambda self: (False, "테스트에서는 인핸서를 쓰지 않는다"),
        )
        monkeypatch.setattr(mw, "ROOT", root)

        window = mw.MainWindow()
        qapp.processEvents()
        # 서버 조회는 백그라운드 워커가 하므로, 끝날 때까지 기다려
        # 위젯에 반영시킨 뒤 돌려준다 (그대로 두면 목록이 비어 있다)
        _wait_models(window, qapp)
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
# CLIP 로더의 type 선택지. (실제 ComfyUI 는 노드 종류마다 다르다)
CLIP_TYPE_OPTIONS = ["qwen_image", "lumina2", "sdxl", "flux"]


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
        # CLIP 타입 선택지도 서버를 부른다. 이러지 않으면 테스트가 실제
        # ComfyUI 에 접속해 결과가 서버 상태에 따라 달라진다.
        monkeypatch.setattr(
            GeurimGyeolEngine, "input_options",
            lambda self, node_class, input_name: list(CLIP_TYPE_OPTIONS),
        )
        monkeypatch.setattr(
            GeurimGyeolEngine, "sampler_options",
            lambda self: {"sampler": ["euler"], "scheduler": ["normal"]},
        )
        monkeypatch.setattr(
            GeurimGyeolEngine, "online", property(lambda self: True)
        )
        monkeypatch.setattr(
            GeurimGyeolEngine, "enhancer_status",
            lambda self: (False, "테스트에서는 인핸서를 쓰지 않는다"),
        )
        monkeypatch.setattr(mw, "ROOT", root)

        window = mw.MainWindow()
        qapp.processEvents()
        _wait_models(window, qapp)
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


def test_unet_row_is_absent_for_sd_workflow(make_sd_window):
    """회귀: SD 워크플로에는 확산 모델 칸 자체가 없어야 한다.

    B19 전에는 없는 칸을 미리 만들어 두고 '(사용 안 함)' 으로 껐는데,
    미리 정한 목록으로는 CLIP 이 2~4개인 워크플로를 담을 수 없다.
    """
    w = make_sd_window("sdA.safetensors")
    try:
        assert "unet" not in w.model_combos
        assert "checkpoint" in w.model_combos
    finally:
        w.close()


def test_checkpoint_row_is_absent_for_qwen_workflow(make_window):
    """회귀: Qwen 워크플로에는 체크포인트 칸이 없어야 한다."""
    w = make_window("installedA.safetensors")
    try:
        assert "checkpoint" not in w.model_combos
        assert "unet" in w.model_combos
    finally:
        w.close()


# --- Model 탭 배치 -----------------------------------------------------

def _show_model_tab(qapp, window):
    """Model 탭을 선택하고 배치를 계산한다."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QTabWidget

    window.findChild(QTabWidget).setCurrentIndex(1)
    window.show()
    qapp.processEvents()
    return QPoint


def test_model_tab_is_split_left_and_right(qapp):
    """회귀: 목록(왼쪽)과 모델 칸(오른쪽)이 나란히 있어야 한다.

    위아래로 두면 목록의 빈 세로 공간이 모델 칸을 아래로 밀어낸다.
    """
    window = _plain_window(qapp)
    try:
        QPoint = _show_model_tab(qapp, window)
        list_x = window.workflow_list.mapTo(window, QPoint(0, 0)).x()
        model_x = window.model_boxes.mapTo(window, QPoint(0, 0)).x()
        assert model_x > list_x, "모델 칸이 목록의 오른쪽에 없다"
    finally:
        window.close()


def test_model_info_stays_full_width_below(qapp):
    """ModelInfo 는 아래에 전체 폭으로 그대로 둔다."""
    window = _plain_window(qapp)
    try:
        QPoint = _show_model_tab(qapp, window)
        box = window.model_boxes
        info = window.model_info
        box_x = box.mapTo(window, QPoint(0, 0))
        info_x = info.mapTo(window, QPoint(0, 0))
        assert info_x.x() + info.width() >= box_x.x() + box.width(), \
            "ModelInfo 가 모델 칸보다 좁다"
        assert info_x.y() > box_x.y(), "ModelInfo 가 위로 올라왔다"
    finally:
        window.close()


def test_model_combos_are_aligned_and_label_column_is_narrow(qapp):
    """회귀: 라벨이 왼쪽 끝, 콤보가 오른쪽 끝에 붙으면 화면이 깨진 것 같다.

    예전에는 두 열이 같은 폭을 나눠 라벨과 콤보 사이에 수백 px 가 떨어졌다.
    이제는 남는 폭이 모두 콤보에 간다. (라벨 열은 내용만큼만)
    """
    window = _plain_window(qapp)
    try:
        _show(window, _sd_prompt())
        QPoint = _show_model_tab(qapp, window)
        grid = window._model_grid
        combos = []
        labels = []
        for row in range(grid.rowCount()):
            label_item = grid.itemAtPosition(row, 0)
            combo_item = grid.itemAtPosition(row, 1)
            if not label_item or not combo_item:
                continue
            label = label_item.widget()
            combo = combo_item.widget()
            if not isinstance(label, QLabel):
                continue          # 두 열을 가로지르는 구분선 등
            combos.append(combo.mapTo(window, QPoint(0, 0)).x())
            labels.append(label.mapTo(window, QPoint(0, 0)).x())
        assert len(combos) >= 2, "확인할 행이 없다"
        # 모든 콤보가 같은 자리에서 시작해야 세로로 정렬돼 보인다
        assert len(set(combos)) == 1, f"콤보 시작 위치가 어긋난다: {combos}"
        # 라벨 열이 화면을 다 먹지 않아야 한다
        span = combos[0] - labels[0]
        assert 0 < span < 260, f"라벨 열이 {span}px 로 넓다"
    finally:
        window.close()


# --- CLIP 2~4개인 워크플로 (Flux / SD3 / Hunyuan) ------------------------

def _clip_workflow(clip_class: str, count: int, clip_type: str = "") -> dict:
    """clip_name1..N 을 가진 워크플로를 만든다."""
    inputs = {f"clip_name{i + 1}": f"clip{i + 1}.safetensors"
              for i in range(count)}
    if clip_type:
        inputs["type"] = clip_type
    return {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": "u.safetensors"}},
        "2": {"class_type": clip_class, "inputs": inputs},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "v.safetensors"}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "고양이", "clip": ["2", 0]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "6": {"class_type": "KSampler",
              "inputs": {"seed": 1, "steps": 20, "cfg": 4.0,
                         "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1, "model": ["1", 0],
                         "positive": ["4", 0], "latent_image": ["5", 0]}},
        "7": {"class_type": "VAEDecode",
              "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0]}},
    }


def _show(window, prompt):
    from app.comfy.workflow import Workflow, infer_parameters
    specs = infer_parameters(prompt)
    # 실제 프로그램은 워크플로를 먼저 선택한 뒤 칸을 세운다.
    # 인접어 칸을 보여줄지 판단할 때 선택된 워크플로를 보기 때문이다.
    window.engine.active_workflow = Workflow(
        path=Path("메모리.json"), name="메모리", description="",
        output_node="", prompt=prompt, parameters=specs,
    )
    # 워크플로 기본값도 넘긴다. 목록이 비었을 때 그것으로 칸을 채운다.
    window._setup_models(specs, window.engine.active_workflow.defaults())
    return window


def _plain_window(qapp):
    """네트워크 조회를 전부 막은 빈 MainWindow."""
    import app.gui.main_window as mw

    async def _fake(self):
        return SystemInfo(online=True, comfyui_version="0.0.0-test",
                          device_name="TEST", vram_total_gb=8.0,
                          vram_free_gb=4.0)

    ComfyClient.get_system_info = _fake
    GeurimGyeolEngine.model_options = lambda self: dict(SD_OPTIONS)
    GeurimGyeolEngine.input_options = (
        lambda self, node_class, input_name: list(CLIP_TYPE_OPTIONS)
    )
    GeurimGyeolEngine.sampler_options = (
        lambda self: {"sampler": ["euler"], "scheduler": ["normal"]}
    )
    # 회귀 근거: 인핸서 조회는 실제 서버의 /object_info(2.5MB) 를 부른다.
    # 막지 않으면 워커가 오래 걸려 closeEvent 의 3초 대기를 넘기고,
    # 실행 중인 스레드가 창과 함께 소멸하며 프로그램이 죽는다.
    # 값은 '사용 가능' 으로 둔다. 서버가 켜져 있을 때의 실제 동작과
    # 같아야 인접어 칸을 다루는 테스트의 기대가 유지된다.
    GeurimGyeolEngine.enhancer_status = (
        lambda self: (True, "테스트용 인핸서 사용 가능")
    )
    GeurimGyeolEngine.online = property(lambda self: True)
    qapp.processEvents()
    window = mw.MainWindow()
    # 회귀 근거: 여기서 워커를 기다리지 않으면 조회가 늦게 끝나 테스트
    # 도중에 _comfy_models 를 덮어쓴다. _show_loras 가 넣어 둔 lora 목록이
    # 지워지며 'lora' 칸이 사라져 KeyError 가 났다.
    # ('lora' 칸은 목록이 비어 있으면 아예 만들지 않는다)
    _wait_models(window, qapp)
    return window


@pytest.mark.parametrize("cls,count,expected", [
    ("DualCLIPLoader", 2, ["clip1", "clip2"]),
    ("TripleCLIPLoader", 3, ["clip1", "clip2", "clip3"]),
    ("QuadrupleCLIPLoader", 4, ["clip1", "clip2", "clip3", "clip4"]),
])
def test_multi_clip_slots_are_recognized(qapp, cls, count, expected):
    """회귀: CLIP 이 2~4개인 워크플로는 그만큼 칸이 있어야 한다.

    clips 를 clip_name 으로만 찾던 때는 Flux 워크플로에서 아예 칸이 안 나왔다.
    """
    window = _plain_window(qapp)
    try:
        _show(window, _clip_workflow(cls, count))
        for key in expected:
            assert key in window.model_combos, f"{key} 칸이 없다"
        assert "clip" not in window.model_combos, "단일 CLIP 칸이 잘못 생겼다"
    finally:
        window.close()


def test_multi_clip_rows_are_ordered(qapp):
    """칸이 늘 때도 순서가 흔들리면 선택지가 제자리에서 점프한다."""
    window = _plain_window(qapp)
    try:
        _show(window, _clip_workflow("QuadrupleCLIPLoader", 4))
        assert list(window._model_labels.values()) == [
            "확산 모델", "텍스트 인코더 1", "텍스트 인코더 2",
            "텍스트 인코더 3", "텍스트 인코더 4", "VAE",
            "인핸서 모델 (로컬 GGUF)",
        ]
        assert list(window.model_combos) == [
            "unet", "clip1", "clip2", "clip3", "clip4", "vae", "local_model",
        ]
    finally:
        window.close()


def test_switching_workflows_rebuilds_rows(qapp, tmp_path, project_root):
    """워크플로를 바꾸면 칸도 그에 맞춰 바뀐다."""
    import app.gui.main_window as mw

    root = tmp_path / "multi"
    for name in ("config", "workflows", "outputs", "sessions"):
        (root / name).mkdir(parents=True, exist_ok=True)
    shutil.copy(project_root / "config" / "comfyui.json",
                root / "config" / "comfyui.json")
    (root / "workflows" / "sd.json").write_text(
        json.dumps({"name": "SD", "prompt": _sd_prompt()}, ensure_ascii=False),
        encoding="utf-8")
    (root / "workflows" / "flux.json").write_text(
        json.dumps({"name": "Flux",
                    "prompt": _clip_workflow("DualCLIPLoader", 2)},
                   ensure_ascii=False),
        encoding="utf-8")
    mw.ROOT = root

    window = _plain_window(qapp)
    try:
        _show(window, _sd_prompt())
        assert "checkpoint" in window.model_combos
        assert "clip1" not in window.model_combos
        _show(window, _clip_workflow("DualCLIPLoader", 2))
        assert "checkpoint" not in window.model_combos
        assert "clip1" in window.model_combos
    finally:
        window.close()


def _sd_prompt() -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "sdA.safetensors"}},
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




def _no_injection_prompt() -> dict:
    """프롬프트를 받는 노드가 아예 없는 워크플로.

    텍스트 인코더가 없으니 인접어 노드를 끼워 넣을 자리가 없다.
    인접어 기능 자체를 쓸 수 없으므로 GGUF 칸도 숨겨져야 한다.
    """
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "sdA.safetensors"}},
        "3": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "4": {"class_type": "KSampler",
              "inputs": {"seed": 1, "steps": 20, "cfg": 7.0,
                         "sampler_name": "euler", "scheduler": "normal",
                         "denoise": 1, "model": ["1", 0],
                         "positive": ["9", 0], "negative": ["9", 0],
                         "latent_image": ["3", 0]}},
        "5": {"class_type": "VAEDecode",
              "inputs": {"samples": ["4", 0], "vae": ["1", 2]}},
        "6": {"class_type": "SaveImage", "inputs": {"images": ["5", 0]}},
    }


def test_enhancer_row_shows_even_without_enhancer_node(qapp):
    """회귀: 인접어 체크박스는 켤 수 있는데 고를 칸이 없던 문제.

    인접어 노드가 없는 워크플로는 생성할 때 자동으로 끼워 넣는다.
    그래도 사용자가 GGUF 를 고를 수 있어야 하므로 칸이 남아야 한다.
    """
    window = _plain_window(qapp)
    try:
        _show(window, _sd_prompt())
        _show_model_tab(qapp, window)
        assert "local_model" in window.model_combos, (
            "인접어 칸이 없다: " + str(list(window.model_combos))
        )
        combo = window.model_combos["local_model"]
        assert combo.count() >= 1, "GGUF 선택지가 하나도 없다"
    finally:
        window.close()


def test_enhancer_row_hidden_when_injection_impossible(qapp):
    """끼워 넣을 자리가 없으면 인접어 기능 자체가 못 쓰므로 칸도 숨긴다."""
    window = _plain_window(qapp)
    try:
        _show(window, _no_injection_prompt())
        _show_model_tab(qapp, window)
        assert "local_model" not in window.model_combos, (
            "끼울 수 없는 워크플로에 인접어 칸이 나왔다: "
            + str(list(window.model_combos))
        )
    finally:
        window.close()


# --- CLIP 로더의 type --------------------------------------------------

def test_clip_type_row_appears_next_to_the_clip_files(qapp):
    """CLIP 종류를 고르는 칸이 CLIP 파일 칸 바로 뒤에 있어야 한다.

    회귀: '어떤 CLIP 인지'(lumina2/flux/qwen_image)는 고를 수단이 없었다.
    """
    window = _plain_window(qapp)
    try:
        window._comfy_input_options = {"DualCLIPLoader": list(CLIP_TYPE_OPTIONS)}
        _show(window, _clip_workflow("DualCLIPLoader", 2, clip_type="flux"))
        _show_model_tab(qapp, window)
        assert "clip_type" in window.model_combos, "CLIP 타입 칸이 없다"
        keys = list(window.model_combos)
        assert keys.index("clip_type") == keys.index("clip2") + 1, (
            f"CLIP 칸 바로 뒤여야 한다: {keys}"
        )
        combo = window.model_combos["clip_type"]
        assert combo.currentText() == "flux", "워크플로에 박힌 값을 보여야 한다"
        assert combo.isEnabled()
        assert combo.count() == len(CLIP_TYPE_OPTIONS)
    finally:
        window.close()


def test_clip_type_row_absent_when_node_has_no_type_input(qapp):
    """type 입력이 없는 워크플로에는 칸이 없어야 한다."""
    window = _plain_window(qapp)
    try:
        _show(window, _clip_workflow("DualCLIPLoader", 2))
        _show_model_tab(qapp, window)
        assert "clip_type" not in window.model_combos
    finally:
        window.close()


def test_chosen_clip_type_and_files_reach_the_request(qapp):
    """고른 타입과 CLIP 파일이 실제 파라미터 키로 넘어가야 한다.

    회귀: clip1~clip4 와 clip_type 은 위젯 키와 ComfyUI 입력 이름이 달라
    대응표에 없었고, 그 결과 선택이 조용히 버려졌다.
    """
    window = _plain_window(qapp)
    try:
        window._comfy_input_options = {"DualCLIPLoader": list(CLIP_TYPE_OPTIONS)}
        # 실제로 고를 수 있게 설치된 CLIP 목록을 채운다
        window._comfy_models = {
            **SD_OPTIONS,
            "text_encoders": [
                "clip1.safetensors", "clip2.safetensors", "새_CLIP_1.safetensors",
            ],
        }
        _show(window, _clip_workflow("DualCLIPLoader", 2, clip_type="flux"))
        _show_model_tab(qapp, window)

        window.model_combos["clip_type"].setCurrentText("sdxl")
        window.model_combos["clip1"].setCurrentText("새_CLIP_1.safetensors")
        extra = window._collect_extra()

        assert extra["clip_type"] == "sdxl"
        assert extra["clip1"] == "새_CLIP_1.safetensors"
        assert extra["clip2"] == "clip2.safetensors", "CLIP 2 도 넘어가야 한다"
    finally:
        window.close()



# --- 이어 붙은 LoRA ---------------------------------------------------

def _lora_chain(count: int) -> dict:
    """UNET -> LoRA -> LoRA … 로 이어진 워크플로."""
    prompt = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "u.safetensors"}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "8": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "고양이", "clip": ["6", 0]}},
    }
    previous = "1"
    for i in range(count):
        node_id = str(2 + i)
        prompt[node_id] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"lora_name": f"lora{i}.safetensors",
                       "strength_model": 0.8, "model": [previous, 0]},
        }
        previous = node_id
    prompt["9"] = {
        "class_type": "KSampler",
        "inputs": {"seed": 1, "steps": 20, "cfg": 4.0, "sampler_name": "euler",
                   "scheduler": "normal", "denoise": 1, "model": [previous, 0],
                   "positive": ["8", 0], "latent_image": ["5", 0]},
    }
    return prompt


def _show_loras(qapp, window, count: int) -> None:
    from app.comfy.workflow import Workflow, infer_parameters

    prompt = _lora_chain(count)
    specs = infer_parameters(prompt)
    workflow = Workflow(
        path=Path("메모리.json"), name="메모리", description="",
        output_node="", prompt=prompt, parameters=specs,
    )
    window.engine.active_workflow = workflow
    window._setup_models(specs, workflow.defaults())
    window._setup_lora_strength(specs, workflow.defaults())
    _show_model_tab(qapp, window)


def test_multi_lora_gets_a_row_and_a_strength_each(qapp):
    """회귀: LoRA 가 이어져 있는데 칸과 강도 줄이 하나뿐이었다."""
    window = _plain_window(qapp)
    try:
        window._comfy_models = {
            **SD_OPTIONS, "loras": ["lora0.safetensors", "lora1.safetensors"],
        }
        _show_loras(qapp, window, 2)
        keys = list(window.model_combos)
        assert "lora" in keys and "lora2" in keys, f"LoRA 칸이 둘이어야 한다: {keys}"
        # 순서는 lora -> lora2 이어야 한다
        assert keys.index("lora") < keys.index("lora2")
        assert len(window._lora_sliders) == 2, "강도 줄도 LoRA 만큼 있어야 한다"
        # lora_box 는 Generation 탭에 있다. 탭이 꺼져 있으니 isVisible 로
        # 판단하면 안 되고, 명시적으로 숨겼는지만 본다.
        assert not window.lora_box.isHidden(), "강도 줄을 감춰 놨다"
    finally:
        window.close()


def test_single_lora_keeps_one_strength_row(qapp):
    window = _plain_window(qapp)
    try:
        window._comfy_models = {**SD_OPTIONS, "loras": ["lora0.safetensors"]}
        _show_loras(qapp, window, 1)
        assert "lora" in window.model_combos
        assert "lora2" not in window.model_combos
        assert len(window._lora_sliders) == 1
    finally:
        window.close()


def test_each_lora_file_and_strength_reaches_its_own_node(qapp):
    """고른 값이 각 LoRA 노드로 따로 가야 한다."""
    window = _plain_window(qapp)
    try:
        window._comfy_models = {
            **SD_OPTIONS, "loras": ["lora0.safetensors", "lora1.safetensors"],
        }
        _show_loras(qapp, window, 2)
        window.model_combos["lora"].setCurrentText("lora1.safetensors")
        window.model_combos["lora2"].setCurrentText("lora0.safetensors")
        window._lora_sliders[0][2].setValue(70)
        window._lora_sliders[1][2].setValue(30)

        extra = window._collect_extra()
        assert extra["lora_strength"] == 0.7
        assert extra["lora_strength2"] == 0.3

        workflow = window.engine.active_workflow
        payload = workflow.apply(extra)
        assert payload["2"]["inputs"]["strength_model"] == 0.7
        assert payload["3"]["inputs"]["strength_model"] == 0.3
        assert payload["2"]["inputs"]["lora_name"] == "lora1.safetensors"
        assert payload["3"]["inputs"]["lora_name"] == "lora0.safetensors"
    finally:
        window.close()

# --- Generate 탭: 기본은 최소한으로 ---------------------------------

def test_advanced_settings_are_hidden_by_default(qapp):
    """대부분의 사용자는 손댈 대상이 없다. 워크플로 값이 이미 최적값이다."""
    window = _plain_window(qapp)
    try:
        assert window.advanced.isHidden(), "고급 설정이 기본으로 떠 있다"
        assert window.advanced_btn.text() == "고급"
        assert window.advanced_btn.isChecked() is False
    finally:
        window.close()


def test_advanced_button_reveals_the_rest(qapp):
    window = _plain_window(qapp)
    try:
        window.advanced_btn.setChecked(True)
        qapp.processEvents()
        assert not window.advanced.isHidden()
        assert window.advanced_btn.text() == "고급 닫기"
        # 감춘 항목이 정말 고급 안에 있는지 확인한다
        for widget in (window.w, window.h, window.scheduler,
                       window.lora_box, window.enhance):
            parent = widget.parent()
            while parent is not None and parent is not window.advanced:
                parent = parent.parent()
            assert parent is window.advanced, "고급 안의 항목이 아니다"

        window.advanced_btn.setChecked(False)
        qapp.processEvents()
        assert window.advanced.isHidden()
    finally:
        window.close()


def test_generate_tab_shows_only_the_essentials(qapp):
    """스텝·CFG·KSampler·시드·프롬프트·네거티브만 기본으로 보여야 한다."""
    window = _plain_window(qapp)
    try:
        window.show()
        qapp.processEvents()
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QTabWidget

        tab = window.findChild(QTabWidget).widget(0)
        point = QPoint(0, 0)

        def top_of(widget):
            return widget.mapTo(tab, point).y()

        # 순서: 프롬프트 -> 네거티브 -> 값들
        assert top_of(window.prompt) < top_of(window.neg)
        assert top_of(window.neg) < top_of(window.steps)
        assert top_of(window.steps) < top_of(window.generate)
        # 프롬프트가 화면을 다 먹지 않아야 아래 값들이 밀려나지 않는다
        assert window.prompt.maximumHeight() <= 260
    finally:
        window.close()
# --- 계열이 다른 모델은 고르지 못하게 한다 ----------------------------

def _unet_workflow(model_name: str) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": model_name}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "고양이", "clip": ["3", 0]}},
        "3": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": "t.safetensors", "type": "qwen_image"}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "6": {"class_type": "KSampler",
              "inputs": {"seed": 1, "steps": 30, "cfg": 4.0,
                         "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1, "model": ["1", 0],
                         "positive": ["2", 0], "latent_image": ["5", 0]}},
    }


def _family_window(qapp, tmp_path):
    """계열 판별이 가능한 창. 모델 파일을 직접 만들어 넣는다."""
    from test_model_family import QWEN_KEYS, SDXL_KEYS, _safetensors

    root = tmp_path / "models"
    (root / "diffusion_models").mkdir(parents=True)
    (root / "text_encoders").mkdir(parents=True)
    (root / "loras").mkdir(parents=True)
    (root / "checkpoints").mkdir(parents=True)
    _safetensors(root / "diffusion_models" / "qwen.safetensors", QWEN_KEYS)
    _safetensors(root / "diffusion_models" / "xl.safetensors", SDXL_KEYS)

    window = _plain_window(qapp)
    window.engine.config.models_dir = str(root)
    window._comfy_models = {
        "diffusion_models": ["qwen.safetensors", "xl.safetensors"],
        "text_encoders": ["t.safetensors"],
        "checkpoints": [], "vae": [], "loras": [],
    }
    return window


def test_other_family_model_cannot_be_picked(qapp, tmp_path):
    """Qwen 워크플로에서 SDXL 확산 모델을 고를 수 없어야 한다."""
    window = _family_window(qapp, tmp_path)
    try:
        _show(window, _unet_workflow("qwen.safetensors"))
        combo = window.model_combos["unet"]
        ok = combo.model().item(combo.findText("qwen.safetensors"))
        bad = combo.model().item(combo.findText("xl.safetensors"))
        assert ok.isEnabled(), "같은 계열은 고를 수 있어야 한다"
        assert not bad.isEnabled(), "다른 계열을 고를 수 있게 두었다"
        assert "Qwen-Image 계열" in bad.toolTip()
        assert "SDXL" in bad.toolTip(), "왜 안 되는지 알려야 한다"
    finally:
        window.close()


def test_unknown_workflow_family_blocks_nothing(qapp, tmp_path):
    """워크플로 계열을 모르면 아무것도 막지 않는다.

    추측해서 막으면 쓸 수 있는 모델까지 못 쓰게 된다.
    """
    from test_model_family import _safetensors, QWEN_KEYS

    window = _family_window(qapp, tmp_path)
    try:
        # 워크플로가 가리키는 모델을 지워 판별이 안 되게 만든다
        (tmp_path / "models" / "diffusion_models" / "없는모델.safetensors").write_bytes(b"")
        _show(window, _unet_workflow("없는모델.safetensors"))
        combo = window.model_combos["unet"]
        for name in ("qwen.safetensors", "xl.safetensors"):
            item = combo.model().item(combo.findText(name))
            assert item.isEnabled(), f"모르는 상태에서 {name} 을 막았다"
    finally:
        window.close()


# --- 드롭다운을 펼치지 않아도 빨간색으로 보여야 한다 ----------------------

def _closed_is_red(combo) -> bool:
    """콤보가 접힌 상태의 글자가 빨간색인지.

    항목 색(Qt.ForegroundRole)은 드롭다운을 펼쳤을 때만 보인다. 접힌
    상태의 글자는 콤보가 따로 그리므로 QSS 로 칠해야 한다.
    """
    return RED in combo.styleSheet().lower()


def test_missing_model_is_red_in_closed_combo(make_window):
    """설치 안 된 모델은 드롭다운을 펼치지 않아도 빨간색이어야 한다.

    회귀: 목록 항목 색만 칠해서 닫힌 화면은 멀쩡했다. 사용자는 문제를
    알아채려면 드롭다운을 눌러 확인해야 했다.
    """
    w = make_window(MISSING)
    try:
        combo = w.model_combos["unet"]
        assert combo.currentText() == MISSING
        assert _closed_is_red(combo), "설치 안 된 값인데 닫힌 화면은 빨갛지 않다"
    finally:
        w.close()


def test_installed_model_is_not_red_in_closed_combo(make_window):
    """설치된 모델은 빨간색으로 칠하지 않는다."""
    w = make_window("installedA.safetensors")
    try:
        assert not _closed_is_red(w.model_combos["unet"])
    finally:
        w.close()


def test_red_clears_when_installed_model_is_picked(make_window):
    """설치된 모델로 바꾸면 접힌 화면의 빨간색도 사라져야 한다."""
    w = make_window(MISSING)
    try:
        combo = w.model_combos["unet"]
        assert _closed_is_red(combo)
        combo.setCurrentIndex(combo.findText("installedA.safetensors"))
        assert not _closed_is_red(combo), "고쳐졌는데 빨간색이 남아 있다"
    finally:
        w.close()


def test_other_family_value_is_red_in_closed_combo(qapp, tmp_path):
    """다른 계열의 값이 남아 있어도 닫힌 화면에서 빨간색이어야 한다."""
    window = _family_window(qapp, tmp_path)
    try:
        _show(window, _unet_workflow("qwen.safetensors"))
        combo = window.model_combos["unet"]
        assert not _closed_is_red(combo), "같은 계열인데 빨갛게 표시되었다"
        # 다른 계열의 값을 고른 상태로 남는다. (저장된 선택, 워크플로 기본값)
        combo.setCurrentIndex(combo.findText("xl.safetensors"))
        assert combo.currentText() == "xl.safetensors"
        assert _closed_is_red(combo), "다른 계열인데 닫힌 화면은 빨갛지 않다"
    finally:
        window.close()


def test_other_family_item_is_painted_red(qapp, tmp_path):
    """다른 계열 항목은 목록에서도 빨간색으로 칠한다."""
    window = _family_window(qapp, tmp_path)
    try:
        _show(window, _unet_workflow("xl.safetensors"))
        combo = window.model_combos["unet"]
        assert _color(combo, combo.findText("qwen.safetensors")) == RED
        assert _color(combo, combo.findText("xl.safetensors")) != RED
    finally:
        window.close()


def test_placeholder_text_is_not_red(qapp, tmp_path):
    """'(이 계열 모델 없음)' 같은 안내 문구는 빨간색이 아니다."""
    window = _family_window(qapp, tmp_path)
    try:
        _show(window, _unet_workflow("qwen.safetensors"))
        assert not window._value_is_bad("unet", "(이 계열 모델 없음 — 선택하세요)")
    finally:
        window.close()


# --- 워크플로별 모델 선택 저장과 삭제 -------------------------------------

def test_model_choice_survives_reopen(make_sd_window):
    """프로그램을 껐다 켜도 고른 모델이 그대로 선택되어 있어야 한다.

    회귀: 선택이 워크플로 기본값으로 되돌아가면 매번 다시 골라야 한다.
    """
    w = make_sd_window("sdA.safetensors")
    try:
        combo = w.model_combos["checkpoint"]
        combo.setCurrentIndex(combo.findText("sdB.safetensors"))
        assert w._model_choices["S"]["checkpoint"] == "sdB.safetensors"
        saved = json.loads(
            w._model_choices_path.read_text(encoding="utf-8")
        )
        assert saved == {"S": {"checkpoint": "sdB.safetensors"}}
    finally:
        w.close()

    다시 = make_sd_window("sdA.safetensors")
    try:
        assert 다시.model_combos["checkpoint"].currentText() == "sdB.safetensors", (
            "다시 열었을 때 워크플로 기본값으로 돌아갔다"
        )
    finally:
        다시.close()


def test_model_choice_file_is_read_back_on_start(qapp, isolated_root, project_root):
    """저장된 파일이 있으면 워크플로 기본값보다 우선한다."""
    import app.gui.main_window as mw

    (isolated_root / "workflows").mkdir(parents=True, exist_ok=True)
    (isolated_root / "workflows" / "S.json").write_text(
        json.dumps({"name": "SD", "prompt": _sd_prompt()}, ensure_ascii=False),
        encoding="utf-8",
    )
    (isolated_root / "config" / "model_choices.json").write_text(
        json.dumps({"S": {"checkpoint": "sdB.safetensors"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert mw.ROOT == isolated_root
    window = _plain_window(qapp)
    try:
        index = next(
            i for i in range(window.workflow.count())
            if window.workflow.itemData(i) == "S"
        )
        window.workflow.setCurrentIndex(index)
        combo = window.model_combos["checkpoint"]
        assert combo.currentText() == "sdB.safetensors"
    finally:
        window.close()


def _delete_root(tmp_path, project_root):
    """base/ 와 profiles/ 워크플로를 하나씩 둔 루트를 만든다."""
    import shutil as _shutil

    root = tmp_path / "delroot"
    for name in ("config", "workflows", "outputs", "sessions"):
        (root / name).mkdir(parents=True, exist_ok=True)
    _shutil.copy(project_root / "config" / "comfyui.json",
                 root / "config" / "comfyui.json")
    (root / "workflows" / "base").mkdir(parents=True, exist_ok=True)
    (root / "workflows" / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "workflows" / "base" / "sd.json").write_text(
        json.dumps({"name": "SD", "prompt": _sd_prompt()}, ensure_ascii=False),
        encoding="utf-8")
    (root / "workflows" / "profiles" / "extra.json").write_text(
        json.dumps({"name": "Extra", "prompt": _sd_prompt()}, ensure_ascii=False),
        encoding="utf-8")
    return root


def test_imported_workflow_can_be_deleted(qapp, tmp_path, project_root,
                                        isolated_root, monkeypatch):
    """가져온 워크플로는 지울 수 있고, 목록과 저장된 선택도 함께 사라진다."""
    import app.gui.main_window as mw

    root = _delete_root(tmp_path, project_root)
    for name in ("config", "workflows", "outputs", "sessions"):
        (root / name).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mw, "ROOT", root)

    window = _plain_window(qapp)
    try:
        window.workflow.setCurrentIndex(1)
        assert window.workflow_list.currentRow() == 1
        window._model_choices["extra"] = {"checkpoint": "sdB.safetensors"}
        monkeypatch.setattr(
            QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
        )
        window._on_delete_workflow()
        assert not (root / "workflows" / "profiles" / "extra.json").exists()
        assert [wf.path.stem for wf in window.engine.workflows] == ["sd"]
        assert window.workflow_list.count() == 1
        assert "extra" not in window._model_choices
    finally:
        window.close()


def test_base_workflow_cannot_be_deleted(qapp, tmp_path, project_root,
                                         isolated_root, monkeypatch):
    """배포된 기본 워크플로는 지울 수 없다."""
    import app.gui.main_window as mw

    root = _delete_root(tmp_path, project_root)
    for name in ("config", "workflows", "outputs", "sessions"):
        (root / name).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mw, "ROOT", root)

    window = _plain_window(qapp)
    try:
        window.workflow.setCurrentIndex(0)
        assert window.workflow_list.currentRow() == 0
        monkeypatch.setattr(
            QMessageBox, "question",
            lambda *a, **k: pytest.fail("기본 워크플로에도 삭제를 물었다"),
        )
        window._on_delete_workflow()
        assert (root / "workflows" / "base" / "sd.json").exists()
        assert "지울 수 없습니다" in window.status.text()
    finally:
        window.close()
