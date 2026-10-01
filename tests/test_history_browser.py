"""History 탭 세션 표시 회귀 테스트.

세션 파일은 저장돼 있어도, 트리에서 안 보이면 사용자는
"기록이 안 남는다"고 판단한다.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.engine.session.manager import SessionManager, SessionMetadata


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_session(sessions_root) -> "object":
    meta = SessionMetadata(
        original_prompt="p",
        enhanced_prompt="p",
        negative_prompt="",
        llm_model=None,
        image_model="테스트 워크플로",
        seed=42,
        width=64,
        height=64,
        steps=4,
        cfg=4.0,
    )
    return SessionManager(sessions_root).create_session(meta)


def test_refresh_keeps_date_nodes_expanded(qapp, tmp_path):
    """새로고침 후에도 날짜 노드가 펼쳐져 새 세션이 보여야 한다.

    회귀: _refresh_list() 가 expandAll() 직후 날짜 노드를 다시 접었다.
    생성이 끝나면 done() 이 이 함수를 다시 불러, 방금 만든 세션이
    접힌 날짜 안에 숨어 "세션이 안 남는 것"처럼 보였다.
    """
    import app.gui.session_browser as sb

    sessions = tmp_path / "sessions"
    outputs = tmp_path / "outputs"
    sessions.mkdir()
    outputs.mkdir()

    browser = sb.HistoryBrowser(sessions, outputs)
    session_dir = _make_session(sessions)

    browser._refresh_list()
    qapp.processEvents()

    tree = browser.tree
    assert tree.topLevelItemCount() == 1, "날짜 노드가 없다"

    date_item = tree.topLevelItem(0)
    assert date_item.isExpanded(), (
        "날짜 노드가 접혀 있어 방금 만든 세션이 화면에 보이지 않는다"
    )

    names = [date_item.child(j).text(0) for j in range(date_item.childCount())]
    assert session_dir.name in names, f"세션이 트리에 없다: {names}"

    # 이미지까지 곧바로 보이는 상태여야 한다
    session_item = next(
        date_item.child(j) for j in range(date_item.childCount())
        if date_item.child(j).text(0) == session_dir.name
    )
    assert session_item.isExpanded()


def test_new_session_is_visible_after_done_refresh(qapp, tmp_path):
    """생성 완료가 부르는 새로고침 이후에도 새 세션이 보인다."""
    import app.gui.session_browser as sb

    sessions = tmp_path / "sessions"
    outputs = tmp_path / "outputs"
    sessions.mkdir()
    outputs.mkdir()

    browser = sb.HistoryBrowser(sessions, outputs)
    before = _make_session(sessions)
    browser._refresh_list()
    qapp.processEvents()

    # 생성 하나 더 = done() 이 하는 것과 동일한 호출
    after = _make_session(sessions)
    browser._refresh_list()
    qapp.processEvents()

    date_item = browser.tree.topLevelItem(0)
    names = [date_item.child(j).text(0) for j in range(date_item.childCount())]
    assert before.name in names and after.name in names, f"{names}"
    assert date_item.isExpanded()
