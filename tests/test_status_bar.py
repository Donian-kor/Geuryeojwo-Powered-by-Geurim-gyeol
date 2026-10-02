"""상태바 갱신 회귀 테스트.

이렇게 고치는 이유
------------------
1. `psutil.cpu_percent(interval=0.1)` 은 이름과 달리 0.1초를 실제로
   sleep 한다(실측 100.5ms/회). 매초 부르면 1분에 6초를 창이 멈춰 있게
   된다. `interval=None` 은 0.018ms 로 끝난다.
2. 지표마다 주기가 다르다. CPU/GPU 는 연산 중 급상승이라 1초,
   RAM/VRAM 은 몇 분에 걸쳐 오르므로 3초면 충분하다.
3. RAM/VRAM 은 상태바와 ModelInfo 가 같은 값·같은 색을 보여야 한다.
   그래서 칠하는 함수는 _paint_usage 하나뿐이다.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel

from app.engine.health import UsageLevel
from app.gui.main_window import _LEVEL_QSS, _paint_usage


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- 색칠

def test_paint_usage_sets_text_and_color(qapp):
    label = QLabel("x")
    _paint_usage(label, "RAM 80%", UsageLevel.WARN)
    assert label.text() == "RAM 80%"
    assert "ffd93d" in label.styleSheet()


def test_paint_usage_ok_has_no_color(qapp):
    """정상일 때는 색을 칠하지 않는다 (창이 과장되지 않는다)."""
    label = QLabel("x")
    _paint_usage(label, "RAM 30%", UsageLevel.OK)
    assert label.styleSheet() == ""


def test_paint_usage_danger_is_red(qapp):
    label = QLabel("x")
    _paint_usage(label, "RAM 95%", UsageLevel.DANGER)
    assert "ff6b6b" in label.styleSheet()


def test_paint_usage_never_leaks_color_on_return_to_ok(qapp):
    """회귀: 빨강이었다가 정상으로 돌아와도 색이 남으면 안 된다."""
    label = QLabel("x")
    _paint_usage(label, "RAM 95%", UsageLevel.DANGER)
    _paint_usage(label, "RAM 30%", UsageLevel.OK)
    assert label.styleSheet() == "", "정상으로 돌아왔는데 색이 남았다"


def test_every_level_has_a_color_entry():
    """단계가 늘어도 표를 빠뜨리지 않게 한다."""
    for level in UsageLevel:
        assert level in _LEVEL_QSS, f"{level} 에 색이 없다"


def test_warn_and_danger_look_different():
    assert _LEVEL_QSS[UsageLevel.WARN] != _LEVEL_QSS[UsageLevel.DANGER]


# ---------------------------------------------------------------- 주기

def test_timers_are_split_by_metric_speed(qapp, monkeypatch):
    """CPU/GPU 는 1초, RAM/VRAM 은 3초. 지표마다 주기가 달라야 한다."""
    from app.gui.main_window import MainWindow

    w = MainWindow()
    try:
        assert w._fast_timer.interval() == 1000
        assert w._slow_timer.interval() == 3000
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()


def test_cpu_percent_does_not_block(qapp, monkeypatch):
    """회귀: interval=0.1 로 돌아가면 매초 0.1초씩 창이 멈춘다."""
    from app.gui import main_window as mw

    calls = []

    class _FakePsutil:
        @staticmethod
        def cpu_percent(interval=None):
            calls.append(interval)
            return 12.0

    monkeypatch.setitem(__import__("sys").modules, "psutil", _FakePsutil)
    w = mw.MainWindow()
    try:
        w._update_status_fast()
        assert calls, "cpu_percent 가 호출되지 않았다"
        assert all(c is None for c in calls), (
            f"interval 을 지정했다: {calls} — 0.1초 블로킹이 돌아왔다"
        )
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()


def test_status_bar_labels_show_values(qapp, monkeypatch):
    """상태바 네 칸이 모두 채워진다."""
    from app.gui.main_window import MainWindow

    w = MainWindow()
    try:
        w._update_status_fast()
        w._update_status_slow()
        for name in ("status_ram", "status_cpu", "status_vram", "status_gpu"):
            label = getattr(w, name)
            assert label.text(), f"{name} 이 비어 있다"
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()


# ---------------------------------------------------------------- ModelInfo

def test_model_info_shows_ram(qapp):
    """ModelInfo 에 RAM 칸이 있다. 서버가 죽는 진짜 신호이기 때문이다."""
    from app.gui.main_window import MainWindow

    w = MainWindow()
    try:
        w.model_info.refresh_resources()
        assert w.model_info.ram_label.text(), "RAM 칸이 비어 있다"
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()


def test_model_info_ram_and_status_bar_agree(qapp):
    """회귀: 두 곳에 같은 판단이 보여야 한다 (색이 어긋나면 안 된다)."""
    from app.gui.main_window import MainWindow

    w = MainWindow()
    try:
        w._update_status_slow()
        bar = w.status_ram.text().replace("RAM ", "")
        info = w.model_info.ram_label.text()
        assert bar == info, f"상태바 '{bar}' 와 ModelInfo '{info}' 가 다르다"
        assert w.status_ram.styleSheet() == w.model_info.ram_label.styleSheet()
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()


def test_model_info_shows_parameter_names_not_just_count(qapp):
    """회귀: '7개' 는 정보가 아니다. 이름이 보여야 한다."""
    from app.gui.main_window import MainWindow

    w = MainWindow()
    try:
        w.model_info.refresh()
        text = w.model_info.params_label.text()
        assert "개" not in text, f"여전히 개수만 보여준다: {text}"
        assert "·" in text, f"이름 목록이 아니다: {text}"
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()


def test_model_info_shows_description(qapp):
    """워크플로 설명은 파일에 이미 있는데 화면에 안 나왔었다."""
    from app.gui.main_window import MainWindow

    w = MainWindow()
    try:
        w.model_info.refresh()
        assert w.model_info.description_label.text() != ""
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()


def test_model_info_shows_comfyui_version(qapp):
    """버전 한 줄이 '이 노드가 없는 버전' 같은 실패 원인을 설명해 준다."""
    from app.gui.main_window import MainWindow

    w = MainWindow()
    try:
        w.model_info.refresh()
        assert w.model_info.comfy_label.text() != ""
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()


def test_model_info_vram_matches_status_bar(qapp):
    """회귀: VRAM 이 8.0GB 와 7.9GB 처럼 어긋나면 어느 쪽이 진짜인지 모른다.

    ComfyUI 값(새로고침 때 갱신)과 nvidia-smi 값(실시간)이 섞이면
    두 화면의 숫자가 다르다. 같은 출처를 쓰도록 고정한다.
    """
    from app.gui.main_window import MainWindow

    w = MainWindow()
    try:
        w._update_status_slow()
        bar = w.status_vram.text().replace("VRAM ", "")
        info = w.model_info.vram_label.text()
        if bar == "VRAM -":
            pytest.skip("VRAM 을 읽지 못하는 환경")
        assert bar == info, f"상태바 '{bar}' 와 ModelInfo '{info}' 가 다르다"
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()


# -------------------------------------------------- 섹션 배치 (B10)

def _show_model_tab(w):
    """Model 탭을 화면에 내준다.

    QStackedWidget 은 안 보이는 페이지를 레이아웃하지 않는다.
    숨겨진 채 측정하면 행이 꾹 눌려 겹쳐 보이고, 겹침 없는 척하는
    거짓말을 하게 된다. (첫 실측이 그랬다)
    """
    from PySide6.QtWidgets import QTabWidget

    tabs = w.findChild(QTabWidget)
    if tabs is None:
        return
    for i in range(tabs.count()):
        if "Model" in tabs.tabText(i):
            tabs.setCurrentIndex(i)
            return
    pytest.skip("Model 탭을 찾지 못했다")


def _label_geometry(panel):
    """(top, height, text) 목록을 위에서 아래 순으로."""
    out = []
    for lab in panel.findChildren(QLabel):
        text = lab.text().strip()
        if not text:
            continue
        g = lab.geometry()
        out.append((g.top(), g.height(), text))
    return sorted(out)


def test_model_info_has_two_sections(qapp):
    """워크플로 / 서버 로 나눴다.

    RAM 이 빨개지는 건 서버 문제인데 워크플로 정보와 같은 평면에 두면
    어느 쪽 때문인지 알 수 없다.
    """
    from app.gui.main_window import MainWindow

    w = MainWindow()
    try:
        _show_model_tab(w)
        app.processEvents()
        texts = [t for _, _, t in _label_geometry(w.model_info)]
        assert "워크플로" in texts
        assert "서버" in texts
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()


def test_model_info_labels_do_not_overlap(qapp):
    """회귀: 라벨이 세로로 꾹 눌리면 항목 이름과 값이 겹친다.

    wordWrap 을 켠 QLabel 의 minimumSizeHint 높이는 거의 0 이어서
    레이아웃이 행을 누른다. 14px 글자가 9px 칸에 들어가 겹쳤다.
    """
    from app.gui.main_window import MainWindow

    w = MainWindow()
    try:
        _show_model_tab(w)
        for _ in range(3):
            app.processEvents()
        rows = _label_geometry(w.model_info)
        for (top1, h1, t1), (top2, h2, t2) in zip(rows, rows[1:]):
            if top1 == top2:
                continue          # 같은 줄의 나란한 칸은 겹침이 아니다
            assert top1 + h1 <= top2 + 1, (
                f"겹침: '{t1}'(y={top1},h={h1}) 와 "
                f"'{t2}'(y={top2}) 가 포개진다"
            )
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()


def test_model_info_is_much_shorter_than_before(qapp):
    """회귀: 파라미터 13개를 개행하면 14줄이 되어 패널이 400px 넘었다."""
    from app.gui.main_window import MainWindow

    w = MainWindow()
    try:
        _show_model_tab(w)
        for _ in range(3):
            app.processEvents()
        h = w.model_info.height()
        assert h < 320, f"패널이 {h}px 로 다시 늘었다 (예전 403px)"
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()


def test_params_are_one_wrapped_line_not_thirteen(qapp):
    """회귀: ' · ' 로 이어 붙여야 한 줄(줄바꿈 가능)로 들어간다."""
    from app.gui.main_window import MainWindow

    w = MainWindow()
    try:
        _show_model_tab(w)
        w.model_info.refresh()
        text = w.model_info.params_label.text()
        assert "\n" not in text, "여전히 개행으로 여러 줄을 쌓는다"
        assert text.count("·") >= 5, f"이름이 빠졌다: {text[:60]}"
    finally:
        w._fast_timer.stop()
        w._slow_timer.stop()
        w.close()
