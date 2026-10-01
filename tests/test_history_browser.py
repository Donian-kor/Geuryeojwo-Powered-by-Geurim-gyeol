"""History 탭 목록 회귀 테스트.

세션 파일은 저장돼 있어도 목록에서 안 보이면 사용자는
"기록이 안 남는다"고 판단한다. 목록이 3단계(날짜>세션>이미지)에서
1줄(썸네일+프롬프트)로 바뀐 뒤에도 이 사실이 유지되는지 고정한다.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.engine.session.manager import SessionManager, SessionMetadata


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _png(path, color=(200, 40, 40)):
    """테스트용 실제 PNG 를 만든다 (썸네일 로딩 경로 검증)."""
    from PIL import Image

    Image.new("RGB", (64, 64), color).save(path)
    return path


def _make_session(sessions_root, prompt="해변에서 수영하는 한국여자",
                  images: int = 1, seed: int = 42):
    """세션 폴더를 만들고 이미지 파일을 images 장 넣는다."""
    meta = SessionMetadata(
        original_prompt=prompt,
        enhanced_prompt=prompt,
        negative_prompt="",
        llm_model=None,
        image_model="테스트 워크플로",
        seed=seed,
        width=64,
        height=64,
        steps=4,
        cfg=4.0,
    )
    session_dir = SessionManager(sessions_root).create_session(meta)
    for n in range(1, images + 1):
        _png(session_dir / f"{n:03d}.png", color=(10 * n, 40, 200 - 20 * n))
    return session_dir


def _browser(tmp_path):
    import app.gui.session_browser as sb

    sessions = tmp_path / "sessions"
    outputs = tmp_path / "outputs"
    sessions.mkdir(exist_ok=True)
    outputs.mkdir(exist_ok=True)
    return sb.HistoryBrowser(sessions, outputs)


def test_one_image_is_one_row(qapp, tmp_path):
    """세션에 이미지가 1장이면 목록에 1줄만 나온다 (3단계 아님)."""
    browser = _browser(tmp_path)
    _make_session(tmp_path / "sessions")

    browser._refresh_list()
    qapp.processEvents()

    tree = browser.tree
    assert tree.topLevelItemCount() == 1, (
        f"이미지 1장이 세션/날짜 행까지 붙어 {tree.topLevelItemCount()}줄이 됐다"
    )
    row = tree.topLevelItem(0)
    assert row.childCount() == 0, "이미지 1장인데 자식 행이 있다"
    assert row.isHidden() is False


def test_row_shows_prompt_not_folder_name(qapp, tmp_path):
    """첫 칸은 프롬프트 요약이다.

    예전에는 폴더명(HHMMSS-001) 이 그대로 보여 무엇인지 알 수 없었다.
    """
    browser = _browser(tmp_path)
    _make_session(tmp_path / "sessions", prompt="해변에서 수영하는 한국여자")

    browser._refresh_list()
    qapp.processEvents()

    text = browser.tree.topLevelItem(0).text(0)
    assert text == "해변에서 수영하는 한국여자"
    # 시각·순번으로 시작하는 옛 형식은 나오지 않는다
    assert not text[:6].isdigit(), f"옛 숫자 이름이 보인다: {text}"


def test_long_prompt_is_truncated_with_ellipsis(qapp, tmp_path):
    """긴 프롬프트는 잘리고 말줄임표로 끝난다."""
    browser = _browser(tmp_path)
    long_prompt = (
        "해변에서 수영하는 한국여자가 햇살 아래서 카메라를 바라보고 "
        "있으며 파도가 발밑에 부서치며 흩날리고 물방울이 증기를 만든다"
    )
    _make_session(tmp_path / "sessions", prompt=long_prompt)

    browser._refresh_list()
    qapp.processEvents()

    text = browser.tree.topLevelItem(0).text(0)
    assert text.endswith("…"), f"말줄임표가 없다: {text}"
    assert len(text) <= 61, f"너무 깁니다 ({len(text)}자): {text}"


def test_row_has_thumbnail_and_seed_and_time(qapp, tmp_path):
    """한 줄에 썸네일·seed·생성 시각이 모두 들어 있다."""
    browser = _browser(tmp_path)
    _make_session(tmp_path / "sessions", seed=137011622967013)

    browser._refresh_list()
    qapp.processEvents()

    row = browser.tree.topLevelItem(0)
    assert not row.icon(0).isNull(), "썸네일이 없다"
    assert row.text(1) == "137011622967013", f"seed 잘림/누락: {row.text(1)}"
    assert row.text(2), "생성 시각이 없다"


def test_one_click_shows_preview(qapp, tmp_path):
    """클릭 1번으로 미리보기가 나온다 (세션 행 + 이미지 행 이중 클릭 제거)."""
    browser = _browser(tmp_path)
    session_dir = _make_session(tmp_path / "sessions")

    browser._refresh_list()
    qapp.processEvents()

    row = browser.tree.topLevelItem(0)
    browser._on_item_selected(row, 0)

    assert browser._current_image == session_dir / "001.png"
    assert browser._current_session == session_dir
    assert not browser.image_preview.pixmap().isNull(), (
        "미리보기가 비어 있다 — 한 번 더 클릭해야 보인다"
    )


def test_multi_image_session_keeps_child_rows(qapp, tmp_path):
    """이미지가 여러 장이면 첫 줄 아래에 자식 행이 생긴다 (배치 생성 대비)."""
    browser = _browser(tmp_path)
    _make_session(tmp_path / "sessions", images=3)

    browser._refresh_list()
    qapp.processEvents()

    tree = browser.tree
    assert tree.topLevelItemCount() == 1
    parent = tree.topLevelItem(0)
    assert parent.childCount() == 2, "나머지 2장이 자식 행으로 있어야 한다"
    # 자식 행은 파일명으로 구분된다
    assert parent.child(0).text(0) == "002.png"


def test_new_session_is_visible_after_done_refresh(qapp, tmp_path):
    """생성 완료가 부르는 새로고침 이후에도 새 세션이 보인다."""
    sessions = tmp_path / "sessions"
    browser = _browser(tmp_path)
    _make_session(sessions, prompt="첫 번째 그림")

    browser._refresh_list()
    qapp.processEvents()
    assert "첫 번째 그림" in browser.tree.topLevelItem(0).text(0)

    # 생성 하나 더 = done() 이 하는 것과 동일한 호출
    _make_session(sessions, prompt="두 번째 그림")
    browser._refresh_list()
    qapp.processEvents()

    texts = [browser.tree.topLevelItem(i).text(0)
             for i in range(browser.tree.topLevelItemCount())]
    assert any("두 번째 그림" in t for t in texts), f"새 세션이 안 보인다: {texts}"
    # 날짜 그룹이 없으므로 모두 최상위 줄이다
    assert browser.tree.topLevelItemCount() == 2

