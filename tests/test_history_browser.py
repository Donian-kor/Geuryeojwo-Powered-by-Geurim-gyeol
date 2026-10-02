"""History 탭 목록 회귀 테스트.

세션 파일은 저장돼 있어도 목록에서 안 보이면 사용자는
"기록이 안 남는다"고 판단한다. 목록이 날짜 그룹 아래 한 줄
(썸네일+프롬프트)로 바뀐 뒤에도 이 사실이 유지되는지 고정한다.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.engine.session.manager import SessionManager, SessionMetadata


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def confirm_yes(monkeypatch):
    """삭제 확인창이 테스트를 멈추게 하지 않도록 '예' 로 자동 응답한다."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.Yes),
    )
    return QMessageBox.Yes


def _png(path, color=(200, 40, 40)):
    """테스트용 실제 PNG 를 만든다 (썸네일 로딩 경로 검증)."""
    from PIL import Image

    Image.new("RGB", (64, 64), color).save(path)
    return path


def _make_session(sessions_root, prompt="해변에서 수영하는 한국여자",
                  images: int = 1, seed: int = 42, date_str: str | None = None):
    """세션 폴더를 만들고 이미지 파일을 images 장 넣는다.

    date_str 을 주면 그 날짜 폴더로 옮긴다 (날짜 그룹 테스트용).
    """
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

    if date_str is not None:
        target = session_dir.parent.parent / date_str / session_dir.name
        target.parent.mkdir(parents=True, exist_ok=True)
        session_dir.rename(target)
        session_dir = target
    return session_dir


def _browser(tmp_path):
    import app.gui.session_browser as sb

    sessions = tmp_path / "sessions"
    outputs = tmp_path / "outputs"
    sessions.mkdir(exist_ok=True)
    outputs.mkdir(exist_ok=True)
    return sb.HistoryBrowser(sessions, outputs)


def _rows(browser):
    """(날짜 그룹 제목, [행 텍스트들]) 목록을 평평하게 만든다."""
    tree = browser.tree
    return [
        (
            tree.topLevelItem(i).text(0),
            [tree.topLevelItem(i).child(j).text(0)
             for j in range(tree.topLevelItem(i).childCount())],
        )
        for i in range(tree.topLevelItemCount())
    ]


def _first_row(browser):
    """첫 번째 날짜 그룹의 첫 번째 행을 돌려준다."""
    return browser.tree.topLevelItem(0).child(0)


# ------------------------------------------------------------------ 구조


def test_images_are_grouped_by_date(qapp, tmp_path):
    """행은 날짜 그룹 아래에 놓인다."""
    sessions = tmp_path / "sessions"
    browser = _browser(tmp_path)
    _make_session(sessions, prompt="첫날 그림", date_str="2026-10-01")
    _make_session(sessions, prompt="둘째날 그림", date_str="2026-10-02")

    browser._refresh_list()
    qapp.processEvents()

    groups = _rows(browser)
    assert len(groups) == 2, f"날짜 그룹이 {len(groups)}개다 (2개여야 함)"

    titles = [title for title, _ in groups]
    assert any("2026년 10월 01일" in t for t in titles), titles
    assert any("2026년 10월 02일" in t for t in titles), titles

    flat = [row for _, rows in groups for row in rows]
    assert "첫날 그림" in flat, flat
    assert "둘째날 그림" in flat, flat


def test_one_image_is_one_row_under_date(qapp, tmp_path):
    """세션에 이미지가 1장이면 날짜 그룹 아래 1줄만 나온다."""
    browser = _browser(tmp_path)
    _make_session(tmp_path / "sessions")

    browser._refresh_list()
    qapp.processEvents()

    groups = _rows(browser)
    assert len(groups) == 1, f"날짜 그룹이 {len(groups)}개다"
    assert len(groups[0][1]) == 1, f"행이 {len(groups[0][1])}개다"


def test_date_group_can_collapse_and_expand(qapp, tmp_path):
    """날짜 그룹은 접었다 펼 수 있다."""
    browser = _browser(tmp_path)
    _make_session(tmp_path / "sessions")

    browser._refresh_list()
    qapp.processEvents()

    group = browser.tree.topLevelItem(0)
    group.setExpanded(False)
    assert group.isExpanded() is False
    group.setExpanded(True)
    assert group.isExpanded() is True


def test_multi_image_session_keeps_all_rows(qapp, tmp_path):
    """이미지가 여러 장이면 같은 날짜 그룹 아래에 모두 나온다."""
    browser = _browser(tmp_path)
    _make_session(tmp_path / "sessions", images=3)

    browser._refresh_list()
    qapp.processEvents()

    groups = _rows(browser)
    assert len(groups) == 1
    assert len(groups[0][1]) == 3, f"3장이 나와야 한다: {groups[0][1]}"
    # 첫 줄은 프롬프트, 나머지는 파일명으로 구분된다
    assert groups[0][1][1:] == ["002.png", "003.png"]


def test_row_shows_prompt_not_folder_name(qapp, tmp_path):
    """첫 칸은 프롬프트 요약이다.

    예전에는 폴더명(HHMMSS-001) 이 그대로 보여 무엇인지 알 수 없었다.
    """
    browser = _browser(tmp_path)
    _make_session(tmp_path / "sessions", prompt="해변에서 수영하는 한국여자")

    browser._refresh_list()
    qapp.processEvents()

    text = _first_row(browser).text(0)
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

    text = _first_row(browser).text(0)
    assert text.endswith("…"), f"말줄임표가 없다: {text}"
    assert len(text) <= 61, f"너무 깁니다 ({len(text)}자): {text}"


# ------------------------------------------------------------------ 행 내용


def test_row_has_thumbnail_and_seed_and_time(qapp, tmp_path):
    """한 줄에 썸네일·seed·생성 시간이 모두 들어 있다."""
    browser = _browser(tmp_path)
    _make_session(tmp_path / "sessions", seed=137011622967013)

    browser._refresh_list()
    qapp.processEvents()

    row = _first_row(browser)
    assert not row.icon(0).isNull(), "썸네일이 없다"
    assert row.text(1) == "137011622967013", f"seed 잘림/누락: {row.text(1)}"
    assert row.text(2), "생성 시간이 없다"


def test_time_column_shows_no_iso_separator(qapp, tmp_path):
    """생성 시간 칸에는 ISO 구분자(T) 가 없고 '08시 47분 20초' 형태다.

    날짜는 날짜 그룹 제목에 있으므로 반복하면 안 된다.
    """
    import app.gui.session_browser as sb

    assert sb.format_time("2026-10-02T08:47:20") == "08시 47분 20초"
    assert sb.format_time("2026-10-01T23:59:09") == "23시 59분 09초"
    # 해석 불가 값은 원본을 그대로 보여준다 (데이터를 숨기지 않는다)
    assert sb.format_time("파싱불가") == "파싱불가"
    assert sb.format_time("") == ""

    browser = _browser(tmp_path)
    _make_session(tmp_path / "sessions")
    browser._refresh_list()
    qapp.processEvents()

    text = _first_row(browser).text(2)
    assert "T" not in text, f"ISO 구분자가 그대로 보인다: {text}"
    assert "년" not in text, f"날짜가 반복된다: {text}"
    assert "시" in text, text


def test_one_click_shows_preview(qapp, tmp_path):
    """클릭 1번으로 미리보기가 나온다 (세션 행 + 이미지 행 이중 클릭 제거)."""
    browser = _browser(tmp_path)
    session_dir = _make_session(tmp_path / "sessions")

    browser._refresh_list()
    qapp.processEvents()

    browser._on_item_selected(_first_row(browser), 0)

    assert browser._current_image == session_dir / "001.png"
    assert browser._current_session == session_dir
    assert not browser.image_preview.pixmap().isNull(), (
        "미리보기가 비어 있다 — 한 번 더 클릭해야 보인다"
    )


def test_new_session_is_visible_after_done_refresh(qapp, tmp_path):
    """생성 완료가 부르는 새로고침 이후에도 새 세션이 보인다."""
    sessions = tmp_path / "sessions"
    browser = _browser(tmp_path)
    _make_session(sessions, prompt="첫 번째 그림")

    browser._refresh_list()
    qapp.processEvents()
    flat = [row for _, rows in _rows(browser) for row in rows]
    assert any("첫 번째 그림" in t for t in flat)

    # 생성 하나 더 = done() 이 하는 것과 동일한 호출
    _make_session(sessions, prompt="두 번째 그림")
    browser._refresh_list()
    qapp.processEvents()

    flat = [row for _, rows in _rows(browser) for row in rows]
    assert any("두 번째 그림" in t for t in flat), f"새 세션이 안 보인다: {flat}"
    assert sum(len(rows) for _, rows in _rows(browser)) == 2


# ------------------------------------------------------------------ 삭제


def test_deleting_session_image_removes_row_immediately(qapp, tmp_path, confirm_yes):
    """이미지를 지우면 전체 새로고침 없이 그 줄이 바로 사라진다."""
    browser = _browser(tmp_path)
    _make_session(tmp_path / "sessions", prompt="지울 그림")

    browser._refresh_list()
    qapp.processEvents()
    browser._on_item_selected(_first_row(browser), 0)
    image_path = browser._current_image
    assert image_path.exists()

    browser._delete_selected()

    assert not image_path.exists(), "디스크에서 지워지지 않았다"
    rows = [row for _, rows in _rows(browser) for row in rows]
    assert rows == [], f"목록에 여전히 보인다: {rows}"


def test_deleting_session_image_also_deletes_source_output(qapp, tmp_path, confirm_yes):
    """세션의 복사본만 지우면 원본이 '미분류' 로 되살아난다.

    회귀 방지: 원본 outputs 까지 지워야 새로고침 후에도 행이 없다.
    """
    from PIL import Image

    from app.engine.output.manager import OutputManager, OutputMetadata

    sessions = tmp_path / "sessions"
    outputs = tmp_path / "outputs"
    outputs.mkdir(exist_ok=True)
    browser = _browser(tmp_path)

    # 원본 출력 1장
    output_manager = OutputManager(outputs)
    png, _ = output_manager.save_output(
        Image.new("RGB", (64, 64), (10, 20, 30)),
        OutputMetadata(
            seed=42, model="wf", prompt="되살아나는 그림", negative_prompt="",
            width=64, height=64, steps=4, cfg=4.0,
        ),
    )

    # 그 원본을 세션에 넣는다 (실제 생성 흐름과 동일)
    meta = SessionMetadata(
        original_prompt="되살아나는 그림", enhanced_prompt="되살아나는 그림",
        negative_prompt="", llm_model=None, image_model="wf",
        seed=42, width=64, height=64, steps=4, cfg=4.0,
    )
    session_manager = SessionManager(sessions)
    session_dir = session_manager.create_session(meta)
    session_manager.add_image_to_session(session_dir, meta, png, 1)

    browser._refresh_list()
    qapp.processEvents()
    assert len([r for _, rows in _rows(browser) for r in rows]) == 1

    browser._on_item_selected(_first_row(browser), 0)
    browser._delete_selected()

    assert not (session_dir / "001.png").exists(), "세션 복사본이 남았다"
    assert not png.exists(), "원본 outputs 가 남아 미분류로 되살아난다"

    # 새로고침해도 되살아나지 않아야 한다
    browser._refresh_list()
    qapp.processEvents()
    rows = [row for _, rows in _rows(browser) for row in rows]
    assert rows == [], f"새로고침 후 되살아났다: {rows}"


def test_deleting_session_removes_all_its_rows_and_sources(qapp, tmp_path, confirm_yes):
    """세션 삭제는 그 세션의 모든 줄과 원본을 함께 지운다."""
    from PIL import Image

    from app.engine.output.manager import OutputManager, OutputMetadata

    sessions = tmp_path / "sessions"
    outputs = tmp_path / "outputs"
    outputs.mkdir(exist_ok=True)
    browser = _browser(tmp_path)

    output_manager = OutputManager(outputs)
    originals = []
    for n in (1, 2):
        png, _ = output_manager.save_output(
            Image.new("RGB", (64, 64), (10 * n, 20, 30)),
            OutputMetadata(
                seed=42, model="wf", prompt="두 장짜리", negative_prompt="",
                width=64, height=64, steps=4, cfg=4.0,
            ),
        )
        originals.append(png)

    meta = SessionMetadata(
        original_prompt="두 장짜리", enhanced_prompt="두 장짜리",
        negative_prompt="", llm_model=None, image_model="wf",
        seed=42, width=64, height=64, steps=4, cfg=4.0,
    )
    session_manager = SessionManager(sessions)
    session_dir = session_manager.create_session(meta)
    for index, png in enumerate(originals, start=1):
        session_manager.add_image_to_session(session_dir, meta, png, index)

    browser._refresh_list()
    qapp.processEvents()
    assert len([r for _, rows in _rows(browser) for r in rows]) == 2

    browser._on_item_selected(_first_row(browser), 0)
    # 세션 삭제를 직접 부른다 (이미지 선택이 있으면 이미지 삭제가 된다)
    browser._delete_session(browser._current_session)

    assert not session_dir.exists(), "세션 폴더가 남았다"
    for png in originals:
        assert not png.exists(), f"원본이 남았다: {png}"

    browser._refresh_list()
    qapp.processEvents()
    assert _rows(browser) == [], "목록에 남았다"


def test_date_label_count_updates_after_delete(qapp, tmp_path, confirm_yes):
    """삭제 후 날짜 그룹 제목의 개수가 맞춰진다."""
    browser = _browser(tmp_path)
    _make_session(tmp_path / "sessions", images=2)

    browser._refresh_list()
    qapp.processEvents()
    assert "2" in browser.tree.topLevelItem(0).text(0)

    browser._on_item_selected(_first_row(browser), 0)
    browser._delete_selected()

    assert "1" in browser.tree.topLevelItem(0).text(0), (
        browser.tree.topLevelItem(0).text(0)
    )