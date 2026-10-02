"""워크플로 가져오기 창과 프로필 저장.

회귀 근거:
- 사용자가 가져온 워크플로를 배포본과 한 폴더에 섞으면 지울 때 헷갈린다.
- 파일 이름이 겹치면 드롭다운에서 찾을 수 없게 된다 (드롭다운이 파일 이름으로 찾는다).
- 등록 버튼이 막혔는지 여부는 '취소'는 항상 누를 수 있어야 하므로
  disabled 여부로 판단한다.
"""
from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from app.comfy.workflow import (
    infer_parameters, list_workflows, load_workflow, safe_stem, save_profile,
)
from app.gui.import_dialog import ImportWorkflowDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


CORE_TYPES = {"UNETLoader", "EmptyLatentImage", "KSampler", "SaveImage"}


# --- 픽스처 --------------------------------------------------------------

_ONE_OUTPUT = {
    "1": {"class_type": "UNETLoader",
          "inputs": {"unet_name": "u.safetensors", "weight_dtype": "default"}},
    "3": {"class_type": "EmptyLatentImage",
          "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
    "4": {"class_type": "KSampler",
          "inputs": {"seed": 1, "steps": 8, "cfg": 1.0,
                     "sampler_name": "euler", "scheduler": "simple",
                     "denoise": 1, "model": ["1", 0],
                     "positive": ["1", 0], "negative": ["1", 0],
                     "latent_image": ["3", 0]}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["4", 0]},
          "_meta": {"title": "이미지 저장"}},
}

_TWO_OUTPUTS = dict(_ONE_OUTPUT, **{
    "95": {"class_type": "SaveImage", "inputs": {"images": ["4", 0]},
           "_meta": {"title": "업스케일됨"}},
})

_BROKEN_NODES = dict(_ONE_OUTPUT, **{
    "54": {"inputs": {"UNKNOWN": -1}, "_meta": {"title": "Seed Control"}},
})


def _write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _opened(qapp, data, tmp_path, name="wf.json", types=CORE_TYPES):
    """파일을 열어 검사가 끝난 창을 돌려준다."""
    path = _write(tmp_path / name, data)
    dlg = ImportWorkflowDialog()
    dlg._known_types = types
    dlg.open_file(path)
    return dlg


# --- safe_stem ----------------------------------------------------------

def test_safe_stem_replaces_windows_illegal_chars():
    assert safe_stem('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"


def test_safe_stem_falls_back_when_empty():
    assert safe_stem("   ") == "workflow"
# --- save_profile -------------------------------------------------------

def test_save_profile_goes_into_profiles_subfolder(tmp_path):
    target = save_profile(tmp_path, "제니 콜", "설명", _ONE_OUTPUT)
    assert target.parent == tmp_path / "profiles"
    assert target.exists()


def test_saved_profile_is_listed(tmp_path):
    """profiles/ 아래에 있어도 목록에 잡혀야 쓸 수 있다."""
    save_profile(tmp_path, "제니 콜", "", _ONE_OUTPUT)
    assert len(list_workflows(tmp_path)) == 1


def test_saved_profile_is_readable_back(tmp_path):
    """저장한 파일이 그대로 워크플로로 읽혀야 한다 (라운드트립)."""
    target = save_profile(tmp_path, "제니 콜", "설명", _ONE_OUTPUT, "9")
    wf = load_workflow(target)
    if not wf.parameters:
        wf.parameters = infer_parameters(wf.prompt)
    assert wf.name == "제니 콜"
    assert wf.description == "설명"
    assert wf.output_node == "9"
    assert wf.defaults()["width"] == 1024


def test_saved_profile_keeps_model_slots(tmp_path):
    """등록한 뒤 Model 탭 콤보에 모델이 나타나야 한다."""
    target = save_profile(tmp_path, "제니 콜", "", _ONE_OUTPUT)
    wf = load_workflow(target)
    wf.parameters = wf.parameters or infer_parameters(wf.prompt)
    assert "unet" in wf.parameters


def test_duplicate_name_gets_number(tmp_path):
    first = save_profile(tmp_path, "제니 콜", "", _ONE_OUTPUT)
    second = save_profile(tmp_path, "제니 콜", "", _ONE_OUTPUT)
    assert first != second
    assert second.name.endswith("-2.json")
    assert len(list_workflows(tmp_path)) == 2


def test_profile_stem_does_not_collide_with_shipped_file(tmp_path):
    """배포본과 파일 이름이 겹치면 드롭다운에서 구분할 수 없다."""
    (tmp_path / "qwen-image-2.1.json").write_text("{}", encoding="utf-8")
    target = save_profile(tmp_path, "qwen-image-2.1", "", _ONE_OUTPUT)
    assert target.stem != "qwen-image-2.1"


def test_name_and_file_name_are_separate(tmp_path):
    """이름에 문자가 섞여도 파일은 안전해야 한다."""
    target = save_profile(tmp_path, "제니: 콜/2", "", _ONE_OUTPUT)
    assert target.stem == "제니_ 콜_2"


# --- list_workflows -----------------------------------------------------

def test_list_workflows_returns_empty_for_missing_dir(tmp_path):
    assert list_workflows(tmp_path / "없는 폴더") == []


def test_list_workflows_ignores_non_json(tmp_path):
    (tmp_path / "readme.txt").write_text("x", encoding="utf-8")
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    assert [p.name for p in list_workflows(tmp_path)] == ["a.json"]


# --- 대화상자 -----------------------------------------------------------

def test_dialog_starts_with_instruction(qapp):
    dlg = ImportWorkflowDialog()
    assert "Export Workflow (API)" in dlg.report_view.toPlainText()
    assert dlg.register_btn.isEnabled() is False
    dlg.close()


def test_opening_valid_workflow_enables_register(qapp, tmp_path):
    dlg = _opened(qapp, _ONE_OUTPUT, tmp_path)
    assert dlg.register_btn.isEnabled() is True
    assert dlg.file_label.text() == "wf.json"
    dlg.close()


def test_missing_node_blocks_register(qapp, tmp_path):
    """노드가 없으면 등록할 수 있게 두면 그대로 실패한다."""
    dlg = _opened(qapp, _BROKEN_NODES, tmp_path)
    assert dlg.register_btn.isEnabled() is False
    assert "Seed Control" in dlg.report_view.toPlainText()
    dlg.close()


def test_single_output_needs_no_choice(qapp, tmp_path):
    """기본 화면에 없는 칸을 늘 보이면 무엇을 고르는지 알 수 없다."""
    dlg = _opened(qapp, _ONE_OUTPUT, tmp_path)
    assert dlg.needs_output_choice() is False
    dlg.close()


def test_two_outputs_offer_choice_with_titles(qapp, tmp_path):
    dlg = _opened(qapp, _TWO_OUTPUTS, tmp_path)
    assert dlg.needs_output_choice() is True
    assert dlg.output_combo.count() == 2
    assert dlg.chosen_output() == "9"
    dlg.output_combo.setCurrentIndex(1)
    assert dlg.chosen_output() == "95"
    dlg.close()


def test_broken_json_shows_error(qapp, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ 이건 json 아님", encoding="utf-8")
    dlg = ImportWorkflowDialog()
    dlg.open_file(path)
    assert dlg.register_btn.isEnabled() is False
    assert "읽을 수 없습니다" in dlg.report_view.toPlainText()
    dlg.close()


def test_ui_format_shows_export_instructions(qapp, tmp_path):
    dlg = _opened(qapp, {"nodes": [{"id": 1}], "links": []}, tmp_path,
                  name="ui.json", types=None)
    assert dlg.register_btn.isEnabled() is False
    assert "Export Workflow (API)" in dlg.report_view.toPlainText()
    dlg.close()


@pytest.mark.parametrize("filename,expected", [
    ("api_image_z_image_turbo.json", "z image turbo"),
    ("workflow_sdxl.json", "sdxl"),
    ("예시api_test.json", "test"),
    ("plain.json", "plain"),
])
def test_default_name_strips_prefixes(qapp, tmp_path, filename, expected):
    dlg = _opened(qapp, _ONE_OUTPUT, tmp_path, name=filename)
    assert dlg.workflow_name() == expected
# --- 배치 -------------------------------------------------------------

def test_buttons_belong_to_the_dialog(qapp):
    """회귀: root.addLayout(buttons) 를 빠뜨리면 버튼이 부모 없이 남는다.

    실제로 한 번 이 상태가 됐고, 그때는 버튼이 창 밖이라
    '등록할 방법이 없다' 는 화면이 나갔다.
    """
    dlg = ImportWorkflowDialog()
    try:
        assert dlg.register_btn.parentWidget() is dlg
        assert dlg.cancel_btn.parentWidget() is dlg
    finally:
        dlg.close()


def _inside(dlg, widget) -> bool:
    """위젯 전체가 창 안에 들어 있는가."""
    top = widget.mapTo(dlg, QPoint(0, 0))
    return (top.y() + widget.height() <= dlg.height()
            and top.x() + widget.width() <= dlg.width())


def test_buttons_are_inside_the_window(qapp, tmp_path):
    dlg = _opened(qapp, _ONE_OUTPUT, tmp_path)
    dlg.show()
    qapp.processEvents()
    try:
        assert _inside(dlg, dlg.register_btn), "등록 버튼이 창 밖이다"
        assert _inside(dlg, dlg.cancel_btn), "취소 버튼이 창 밖이다"
    finally:
        dlg.close()


def test_long_report_still_leaves_buttons_visible(qapp, tmp_path):
    """경고가 길어져도 버튼이 밀려나면 안 된다."""
    many = dict(_ONE_OUTPUT)
    for i in range(40):
        many[f"x{i}"] = {"inputs": {"UNKNOWN": i}, "_meta": {"title": f"노드 {i}"}}
    dlg = _opened(qapp, many, tmp_path)
    dlg.show()
    qapp.processEvents()
    try:
        assert _inside(dlg, dlg.register_btn), "긴 안내에서 버튼이 창 밖으로 밀렸다"
        assert _inside(dlg, dlg.name_edit), "이름 칸이 창 밖으로 밀렸다"
    finally:
        dlg.close()


def test_minimum_size_keeps_buttons_visible(qapp):
    """최소 크기로 줄여도 버튼이 남아야 한다."""
    dlg = ImportWorkflowDialog()
    dlg.resize(dlg.minimumSizeHint())
    dlg.show()
    qapp.processEvents()
    try:
        assert _inside(dlg, dlg.register_btn)
        assert _inside(dlg, dlg.cancel_btn)
    finally:
        dlg.close()
    dlg.close()


def test_manual_name_is_not_overwritten(qapp, tmp_path):
    """'다시 가져오기' 를 눌러도 지은 이름을 지우면 안 된다."""
    dlg = _opened(qapp, _ONE_OUTPUT, tmp_path)
    dlg.name_edit.setText("직접 지은 이름")
    dlg.open_file(tmp_path / "wf.json")
    assert dlg.workflow_name() == "직접 지은 이름"
    dlg.close()
    assert safe_stem("...") == "workflow"


def test_safe_stem_is_length_limited():
    assert len(safe_stem("가" * 200)) <= 60


def test_safe_stem_keeps_korean():
    assert safe_stem("제니 콜") == "제니 콜"