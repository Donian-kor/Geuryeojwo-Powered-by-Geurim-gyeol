"""기본 워크플로 — 계열별로 하나씩 두고, 모델은 사용자가 고르게 한다.

회귀 근거: 기본 워크플로에 모델 파일명을 박아 두면, 그 파일이 없는
PC 에서 모든 항목이 '설치 안 됨' 으로 뜬다. 모델 이름은 비워 두고
계열(family)만 선언한다. 그러면 그 계열에 맞는 설치 모델이 있을 때만
자동으로 골라 주고, 없으면 무엇을 설치해야 하는지 알려 준다.

또 하나: 계열에 맞는 모델이 하나도 없을 때 목록의 첫 항목이 그대로
선택되어, 다른 계열 모델로 조용히 그림을 만들 수 있었다.
'(이 계열 모델 없음)' 상태로 시작하는 것이 그 방지를 한다.
"""
from __future__ import annotations

import contextlib
import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from app.comfy.client import ComfyClient, SystemInfo
from app.comfy.model_family import clear_cache, workflow_family
from app.comfy.workflow import list_workflows, load_workflow
from app.engine.comfy_engine import GeurimGyeolEngine

BASE_DIR = Path(__file__).resolve().parents[1] / "workflows" / "base"

# 배포하는 기본 워크플로. 계열이 하나씩 있어야 한다.
EXPECTED_FAMILIES = {"qwen-image", "flux", "sdxl", "zimage", "ernie"}

# 기본 노드 (ComfyUI 기본 제공). 커스텀 팩 없이도 돌아야 한다.
CORE_NODES = {
    "UNETLoader", "VAELoader", "CLIPLoader", "DualCLIPLoader",
    "CheckpointLoaderSimple", "CLIPTextEncode", "TextEncodeQwenImage21",
    "EmptyLatentImage", "EmptySD3LatentImage", "ConditioningZeroOut",
    "ModelSamplingAuraFlow", "KSampler", "VAEDecode", "SaveImage",
}


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def models_dir(tmp_path):
    """계열 판별용 safetensors 파일이 있는 models 폴더."""
    from test_model_family import QWEN_KEYS, SDXL_KEYS, _safetensors

    root = tmp_path / "models"
    for folder in ("checkpoints", "diffusion_models", "text_encoders",
                   "vae", "loras"):
        (root / folder).mkdir(parents=True)
    _safetensors(root / "diffusion_models" / "qwen.safetensors", QWEN_KEYS)
    _safetensors(root / "checkpoints" / "xl.safetensors", SDXL_KEYS)
    _safetensors(root / "text_encoders" / "clip.safetensors", ["a.weight"])
    _safetensors(root / "vae" / "ae.safetensors", ["b.weight"])
    return root


OPTIONS = {
    "diffusion_models": ["qwen.safetensors"],
    "checkpoints": ["xl.safetensors"],
    "text_encoders": ["clip.safetensors"],
    "vae": ["ae.safetensors"],
    "loras": [],
}


def _plain_window(qapp, monkeypatch):
    """네트워크 조회를 전부 막은 빈 MainWindow.

    monkeypatch 로 되돌린다. 여기서 클래스 속성에 직접 대입하면
    되돌아가지 않아, 뒤에 실행되는 다른 테스트 파일의 ComfyUI 응답까지
    이 가짜 값으로 바꿔 버린다. (알려지지 않은 실패가 된다)
    """
    import app.gui.main_window as mw

    async def _fake(self):
        return SystemInfo(online=True, comfyui_version="0.0.0-test",
                          device_name="TEST", vram_total_gb=8.0,
                          vram_free_gb=4.0)

    monkeypatch.setattr(ComfyClient, "get_system_info", _fake)
    monkeypatch.setattr(GeurimGyeolEngine, "model_options",
                        lambda self: dict(OPTIONS))
    monkeypatch.setattr(GeurimGyeolEngine, "input_options",
                        lambda self, node_class, input_name:
                        ["qwen_image", "lumina2", "flux"])
    monkeypatch.setattr(GeurimGyeolEngine, "sampler_options",
                        lambda self: {"sampler": ["euler"],
                                      "scheduler": ["simple"]})
    monkeypatch.setattr(GeurimGyeolEngine, "online",
                        property(lambda self: True))
    qapp.processEvents()
    return mw.MainWindow()


def _show(window, name, models_dir, options: dict | None = None):
    """base/ 아래 워크플로를 연 창을 만든다."""
    wf = load_workflow(BASE_DIR / f"{name}.json")
    window.engine.active_workflow = wf
    window.engine.config.models_dir = str(models_dir)
    window._comfy_models = dict(options or OPTIONS)
    clear_cache()
    window._setup_models(wf.parameters, wf.defaults())
    return window


# --- 배포 파일 자체 --------------------------------------------------

def test_every_family_has_a_base_workflow():
    """계열마다 기본 워크플로가 하나씩 있어야 한다."""
    found = set()
    for path in BASE_DIR.glob("*.json"):
        found.add((load_workflow(path).meta or {}).get("family", ""))
    assert found == EXPECTED_FAMILIES


def test_base_workflows_list_models_folder():
    """base/ 아래 파일도 목록에 잡혀야 고를 수 있다."""
    names = {p.name for p in list_workflows(BASE_DIR.parent)}
    assert "sdxl.json" in names, "base/ 아래 워크플로가 목록에 없다"
    assert "zanime.json" in names


def test_base_workflow_declares_family_without_model_files():
    """모델을 못 찾아도 파일이 밝힌 계열로 판별된다."""
    assert workflow_family(load_workflow(BASE_DIR / "flux.json"), "없는/경로") == "flux"


def test_base_workflow_leaves_model_name_blank():
    """모델 이름을 비워 둔다. PC 마다 설치된 파일이 다르기 때문이다."""
    for path in BASE_DIR.glob("*.json"):
        for node in load_workflow(path).prompt.values():
            for name in ("unet_name", "ckpt_name", "clip_name1", "clip_name2"):
                assert node["inputs"].get(name, "") == "", (
                    f"{path.name} · {node['class_type']} · {name} 에 "
                    "모델 이름이 박혀 있다"
                )


def test_base_workflow_uses_only_core_nodes():
    """커스텀 노드가 없으면 커스텀 팩 없이도 동작한다."""
    for path in BASE_DIR.glob("*.json"):
        for node in load_workflow(path).prompt.values():
            assert node["class_type"] in CORE_NODES, (
                f"{path.name} 에 기본 노드가 아닌 {node['class_type']} 가 있다"
            )


def test_base_workflow_can_be_generated_from():
    """기본 워크플로가 이 프로그램의 최소 요건(그림 저장)을 만족한다."""
    from app.comfy.check import check_fitness, output_nodes
    for path in BASE_DIR.glob("*.json"):
        wf = load_workflow(path)
        assert output_nodes(wf.prompt), f"{path.name} 에 저장 노드가 없다"
        assert check_fitness(wf.prompt) is None, path.name


# --- 한 계열에 모델이 여럿인 경우 (ERNIE Base / Turbo) -----------------

# ERNIE-Image 와 ERNIE-Image-Turbo 는 같은 계열이라 판별 결과가 같지만
# 최적 스텝/guidance 가 정반대다. (각 HuggingFace 모델카드 권장값)
ERNIE_EXPECTED = {
    "ernie": (50, 4.0),        # Base  — 50 steps, guidance 4.0
    "ernie-turbo": (8, 1.0),   # Turbo —  8 steps, guidance 1.0
}


@pytest.mark.parametrize("name,expected", sorted(ERNIE_EXPECTED.items()))
def test_ernie_variants_keep_their_own_optimal_settings(name, expected):
    """ERNIE Base 와 Turbo 는 서로 다른 워크플로로 배포한다.

    회귀 근거: 두 모델이 최적값이 다르므로 워크플로를 나눴다. 그런데 둘을
    한 파일로 합치면 어느 한쪽의 값(예: Turbo 에 50스텝)이 그대로 굳는다.
    워크플로가 둘로 갈라져 있고 각자 권장값을 갖고 있는지 확인한다.
    """
    path = BASE_DIR / f"{name}.json"
    assert path.exists(), f"{name}.json 이 없다"
    defaults = load_workflow(path).defaults()
    assert (defaults["steps"], defaults["cfg"]) == expected, name


def test_ernie_variants_share_one_family():
    """둘 다 'ernie' 계열이다. 계열을 쪼개지 않는다.

    계열을 나누면 turbo 를 고르지 못하는 PC 에서 'ERNIE 계열 모델이
    없습니다' 라고 잘못 말하게 된다.
    """
    for name in ERNIE_EXPECTED:
        assert workflow_family(
            load_workflow(BASE_DIR / f"{name}.json"), "없는/경로"
        ) == "ernie", name


def test_both_ernie_variants_are_listed():
    """사용자가 고를 수 있어야 하므로 둘 다 목록에 잡혀야 한다."""
    names = {p.name for p in list_workflows(BASE_DIR.parent)}
    assert "ernie.json" in names
    assert "ernie-turbo.json" in names


def test_ernie_variants_have_distinct_names():
    """드롭다운에서 구별돼야 한다. 이름이 같으면 고른 티가 안 난다."""
    names = [load_workflow(BASE_DIR / f"{n}.json").name
             for n in ERNIE_EXPECTED]
    assert len(set(names)) == len(names), f"이름이 겹친다: {names}"


@pytest.mark.parametrize("wf_name,variant", [("ernie", "base"),
                                            ("ernie-turbo", "turbo")])
def test_workflow_declares_its_variant(wf_name, variant):
    """같은 계열의 두 워크플로가 원하는 변형을 밝힌다."""
    meta = load_workflow(BASE_DIR / f"{wf_name}.json").meta
    assert meta.get("variant") == variant, wf_name


def test_other_base_workflows_declare_no_variant():
    """ERNIE 처럼 Base/Turbo 쌍이 없는 계열은 변형을 밝히지 않는다.

    잘못 밝히면 설치되지 않은 변형을 기다리며 모델 목록이 비어 보인다.
    """
    paired = {f"{n}.json" for n in ERNIE_EXPECTED}
    for path in BASE_DIR.glob("*.json"):
        if path.name in paired:
            continue
        meta = load_workflow(path).meta
        assert meta.get("variant", "") == "", path.name


# --- GUI 에서 자동으로 각 모델이 골라지는지 -------------------------------

ERNIE_NAMES = ["ERNIE-AIO-Base.safetensors", "ERNIE-AIO-Turbo.safetensors"]


@contextlib.contextmanager
def _ernie_window(qapp, models_dir, monkeypatch, wf_name):
    """ERNIE 계열 모델이 있는 창. 모델 목록을 ComfyUI 응답으로 흉내낸다."""
    options = dict(OPTIONS)
    options["checkpoints"] = list(ERNIE_NAMES)
    monkeypatch.setattr(GeurimGyeolEngine, "model_options",
                        lambda self: dict(options))
    window = _plain_window(qapp, monkeypatch)
    try:
        _show(window, wf_name, models_dir, options)
        yield window
    finally:
        window.close()


@pytest.fixture
def ernie_models_dir(tmp_path):
    """Base 와 Turbo 가 함께 설치된 models 폴더."""
    from test_model_family import ERNIE_KEYS, _safetensors

    root = tmp_path / "models"
    for folder in ("checkpoints", "diffusion_models", "text_encoders",
                   "vae", "loras"):
        (root / folder).mkdir(parents=True)
    for name, inner in (("ERNIE-AIO-Base.safetensors", "ernie\\ernie-image-fp8.safetensors"),
                        ("ERNIE-AIO-Turbo.safetensors", "ernie\\ernie-image-turbo-fp8.safetensors")):
        _safetensors(root / "checkpoints" / name, ERNIE_KEYS,
                     {"prompt": json.dumps({"2": {
                         "class_type": "UNETLoader",
                         "inputs": {"unet_name": inner}}})})
    return root


def test_turbo_workflow_auto_picks_turbo_model(qapp, ernie_models_dir,
                                               monkeypatch):
    """회귀: Turbo 워크플로를 열면 Turbo 모델이 자동으로 선택된다."""
    with _ernie_window(qapp, ernie_models_dir, monkeypatch, "ernie-turbo") as window:
        assert window.model_combos["checkpoint"].currentText() == (
            "ERNIE-AIO-Turbo.safetensors"
        )


def test_base_workflow_auto_picks_base_model(qapp, ernie_models_dir,
                                             monkeypatch):
    """회귀: Base 워크플로를 열면 Base 모델이 자동으로 선택된다."""
    with _ernie_window(qapp, ernie_models_dir, monkeypatch, "ernie") as window:
        assert window.model_combos["checkpoint"].currentText() == (
            "ERNIE-AIO-Base.safetensors"
        )


# --- GUI 동작 -------------------------------------------------------

def test_matching_model_is_picked_automatically(qapp, models_dir, monkeypatch):
    """계열에 맞는 설치 모델이 있으면 대신 골라 준다."""
    window = _plain_window(qapp, monkeypatch)
    try:
        _show(window, "qwen-image", models_dir)
        assert window.model_combos["unet"].currentText() == "qwen.safetensors"
        assert window._missing_family_model() == ""
    finally:
        window.close()


def test_checkpoint_is_picked_for_checkpoint_style_workflow(qapp, models_dir, monkeypatch):
    window = _plain_window(qapp, monkeypatch)
    try:
        _show(window, "sdxl", models_dir)
        combo = window.model_combos["checkpoint"]
        assert combo.currentText() == "xl.safetensors"
    finally:
        window.close()


# --- AIO 체크포인트 (모델+CLIP+VAE가 한 파일) ---------------------------
# Z-Image 계열 기본 워크플로(zanime)는 CheckpointLoaderSimple(ckpt_name)로
# AIO 체크포인트를 불러온다. UNETLoader 구조와 달라 모델 칸이
# checkpoints 폴더에서 고른다.


def test_aio_checkpoint_workflow_picks_aio_model(qapp, tmp_path, monkeypatch):
    """회귀: AIO 체크포인트 워크플로(zanime)가 모델을 고를 수 있어야 한다.

    배포 워크플로가 UNETLoader 를 썼을 때 diffusion_models 에 AIO 체크포인트가
    없으면 후보가 0개가 돼 '계열 모델이 없습니다'로 막혔다.
    CheckpointLoaderSimple 을 쓰는 Z-Anime 워크플로에서는 checkpoints 에 있는
    AIO 체크포인트가 자동으로 고려져야 한다.
    """
    from test_model_family import ZIMAGE_KEYS, _safetensors

    root = tmp_path / "models"
    for folder in ("checkpoints", "diffusion_models", "text_encoders",
                   "vae", "loras"):
        (root / folder).mkdir(parents=True)
    # AIO 체크포인트: 확산 모델 + CLIP + VAE 가 한 파일에 든다.
    _safetensors(root / "checkpoints" / "z-anime-base-aio.safetensors",
                 ZIMAGE_KEYS)
    options = dict(OPTIONS)
    options["checkpoints"] = ["z-anime-base-aio.safetensors"]
    window = _plain_window(qapp, monkeypatch)
    try:
        _show(window, "zanime", root, options)
        combo = window.model_combos["checkpoint"]
        assert combo.currentText() == "z-anime-base-aio.safetensors"
        assert window._missing_family_model() == ""
    finally:
        window.close()


def test_other_family_model_is_not_silently_chosen(qapp, models_dir, monkeypatch):
    """Flux 워크플로에 Qwen 모델이 자동으로 고르지 않아야 한다.

    회귀 근거: 자동 선택이 실패하면 목록의 첫 항목이 그대로 선택돼,
    다른 계열 모델로 조용히 그림을 만들 수 있었다.
    """
    window = _plain_window(qapp, monkeypatch)
    try:
        _show(window, "flux", models_dir)
        combo = window.model_combos["unet"]
        assert combo.currentText() != "qwen.safetensors"
        assert combo.currentText().startswith("("), "선택 안 된 상태여야 한다"
        assert "Flux" in window._missing_family_model()
    finally:
        window.close()


def test_other_family_item_is_disabled_with_reason(qapp, models_dir, monkeypatch):
    window = _plain_window(qapp, monkeypatch)
    try:
        _show(window, "flux", models_dir)
        combo = window.model_combos["unet"]
        item = combo.model().item(combo.findText("qwen.safetensors"))
        assert item is not None and not item.isEnabled()
        assert "Flux 계열" in item.toolTip()
    finally:
        window.close()


def test_generation_is_blocked_when_family_model_is_missing(qapp, models_dir,
                                                            monkeypatch):
    """계열 모델이 없으면 생성 전에 막고 안내한다."""
    from PySide6.QtWidgets import QMessageBox

    window = _plain_window(qapp, monkeypatch)
    try:
        _show(window, "flux", models_dir)
        shown = {}
        monkeypatch.setattr(
            QMessageBox, "warning",
            staticmethod(lambda *a: shown.setdefault("title", a[1])),
        )
        monkeypatch.setattr(window.engine, "build_request",
                            lambda **kw: pytest.fail("차단되지 않고 실행되었다"))
        window.prompt.setPlainText("고양이")
        window.start()
        assert "Flux" in shown.get("title", "")
    finally:
        window.close()