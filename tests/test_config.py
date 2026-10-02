"""ComfyUI 설정의 models_dir (모델 폴더) 처리.

회귀 근거:
모델이 없을 때 등록 화면은 "어디에 파일을 넣어야 하는지" 알려줘야 한다.
경로를 모르면 '아무 데나' 가 되어 사용자가 모델을 못 찾아온다.
따라서 경로는 반드시 알아낼 수 있어야 하고, 못 알아내면 솔직히
빈 값으로 두어 사용자에게 한 번 물어볼 수 있게 한다.
"""
from __future__ import annotations

import json

from app.comfy.config import (
    DEFAULT_CONFIG, ComfyUIConfig, guess_models_dir,
)


def _make_models_tree(root):
    """root 아래에 ComfyUI 모델 폴더 구조를 만든다."""
    for folder in ("checkpoints", "diffusion_models", "text_encoders", "vae"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    return root


# --- 설정 읽고 쓰기 -----------------------------------------------------

def test_default_models_dir_is_empty(tmp_path):
    cfg = ComfyUIConfig.load(tmp_path / "comfyui.json")
    assert cfg.models_dir == ""


def test_models_dir_is_loaded(tmp_path):
    path = tmp_path / "comfyui.json"
    path.write_text(json.dumps({"models_dir": "C:/models"}), encoding="utf-8")
    assert ComfyUIConfig.load(path).models_dir == "C:/models"


def test_models_dir_survives_save_and_load(tmp_path):
    path = tmp_path / "sub" / "comfyui.json"
    ComfyUIConfig(models_dir="D:/m").save(path)
    assert ComfyUIConfig.load(path).models_dir == "D:/m"


def test_save_writes_models_dir_key(tmp_path):
    path = tmp_path / "comfyui.json"
    ComfyUIConfig(models_dir="D:/m").save(path)
    assert "models_dir" in json.loads(path.read_text(encoding="utf-8"))


def test_broken_config_does_not_crash(tmp_path):
    path = tmp_path / "comfyui.json"
    path.write_text("{ 이건 json 아님", encoding="utf-8")
    cfg = ComfyUIConfig.load(path)
    assert cfg.host == DEFAULT_CONFIG["host"]
    assert cfg.models_dir == ""


# --- 자동 찾기 ----------------------------------------------------------

def test_guess_finds_directory_with_model_subfolders(tmp_path):
    root = _make_models_tree(tmp_path / "models")
    assert guess_models_dir(roots=[root]) == str(root)


def test_guess_rejects_directory_without_model_subfolders(tmp_path):
    plain = tmp_path / "just_a_folder"
    plain.mkdir()
    assert guess_models_dir(roots=[plain]) == ""


def test_guess_accepts_any_single_model_subfolder(tmp_path):
    """설치된 모델이 하나뿐이어도 모델 폴더로 인정한다."""
    root = tmp_path / "models"
    (root / "vae").mkdir(parents=True)
    assert guess_models_dir(roots=[root]) == str(root)


def test_guess_returns_empty_when_nothing_matches(tmp_path):
    assert guess_models_dir(roots=[tmp_path / "a", tmp_path / "b"]) == ""


def test_guess_checks_roots_in_order(tmp_path):
    first = _make_models_tree(tmp_path / "first")
    second = _make_models_tree(tmp_path / "second")
    assert guess_models_dir(roots=[first, second]) == str(first)


def test_guess_uses_folders_list_from_argument(tmp_path):
    root = tmp_path / "models"
    (root / "upscale_models").mkdir(parents=True)
    # 기본 폴더 목록엔 없으므로 기본으로는 찾지 못한다
    assert guess_models_dir(roots=[root]) == ""
    assert guess_models_dir(folders=["upscale_models"], roots=[root]) == str(root)


def test_guess_does_not_die_on_missing_root(tmp_path):
    assert guess_models_dir(roots=[tmp_path / "없는 폴더"]) == ""


def test_guess_without_roots_uses_environment(monkeypatch, tmp_path):
    """환경 변수로 ComfyUI Desktop 경로를 찾는다 (실사용 환경)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    _make_models_tree(tmp_path / "Comfy-Desktop" / "ComfyUI-Shared" / "models")
    assert "ComfyUI-Shared" in guess_models_dir()


def test_guess_without_roots_returns_empty_when_absent(monkeypatch, tmp_path):
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "none"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "none"))
    monkeypatch.chdir(workdir)
    assert guess_models_dir() == ""