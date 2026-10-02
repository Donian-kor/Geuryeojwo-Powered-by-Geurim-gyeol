"""워크플로 가져오기 대화상자.

ComfyUI 에서 가져온 워크플로를 검사해 보여주고, 이름·설명을 정해 등록한다.
판정은 app/comfy/check.py 가 맡는다. 이 파일은 그 결과를 그릴 뿐이며
판정을 다시 하지 않는다 (GUI 에 규칙을 두지 않기 위해서).

여기서 늘 보이는 위젯은 이름·설명·버튼뿐이다.
결과 저장 노드가 2개일 때만 선택 칸이 추가로 나타난다.
기본 화면이 늘 같아야 사용자가 무엇을 고르는지 알고 쓸 수 있다.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextBrowser, QVBoxLayout,
)

from app.comfy.check import (
    LEVEL_BLOCK, LEVEL_INFO, LEVEL_OK, LEVEL_WARN, CheckItem, CheckReport,
    check_workflow, prompt_of,
)

# 상태별 글자색과 표시 문자.
_STYLE = {
    LEVEL_OK:    ("#2e7d32", "✓"),
    LEVEL_INFO:  ("#555555", "·"),
    LEVEL_WARN:  ("#b26a00", "⚠"),
    LEVEL_BLOCK: ("#c62828", "✕"),
}


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


class NodeTypesWorker(QThread):
    """설치된 노드 종류를 백그라운드에서 읽는다.

    /object_info 응답이 수백 KB 다 (노드 1000종 이상).
    GUI 스레드에서 읽으면 창이 그만큼 멈춘다.
    """

    fetched = Signal(object)

    def __init__(self, engine):
        super().__init__()
        self.engine = engine

    def run(self) -> None:
        try:
            self.fetched.emit(self.engine.node_types())
        except Exception:
            self.fetched.emit(set())


class ImportWorkflowDialog(QDialog):
    """워크플로 하나를 가져와 등록하는 창."""

    def __init__(self, engine=None, installed_models=None, models_dir="",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("워크플로 가져오기")
        # 버튼이 창 밖으로 밀려나면 등록할 방법이 없다.
        # 경고 문장이 길어지니 넉넉한 높이를 준다.
        self.setMinimumSize(560, 560)
        self.resize(680, 720)
        # 경고·안내를 읽기 편한 크기로 통일한다.
        self.setStyleSheet("font-size: 14px;")

        self._engine = engine
        self._installed = installed_models or {}
        self._models_dir = str(models_dir or "")
        self._known_types: set[str] | None = None
        self._path: Path | None = None
        self._data: dict | None = None
        self._report: CheckReport | None = None
        self._worker: NodeTypesWorker | None = None

        root = QVBoxLayout(self)

        # --- 파일 선택 -------------------------------------------------
        pick = QHBoxLayout()
        pick.addWidget(QLabel("파일:"))
        self.file_label = QLabel("(아직 고르지 않았습니다)")
        self.file_label.setStyleSheet("color:#555;")
        pick.addWidget(self.file_label, 1)
        self.browse_btn = QPushButton("파일 선택")
        self.browse_btn.clicked.connect(self._on_browse)
        pick.addWidget(self.browse_btn)
        root.addLayout(pick)

        # --- 검사 결과 -------------------------------------------------
        self.report_view = QTextBrowser()
        self.report_view.setOpenExternalLinks(True)
        self.report_view.setMinimumHeight(240)
        self.report_view.setHtml(
            "<p style='color:#777'>위에서 워크플로 파일을 고르세요.</p>"
            "<p style='color:#777'>ComfyUI 에서 "
            "<b>File → Export Workflow (API)</b> 로 내보낸 파일을 "
            "여기에 가져오면 됩니다.</p>"
        )
        root.addWidget(self.report_view, 1)

        # --- 결과 선택 (2개 이상일 때만 나타남) ------------------------
        self.output_combo = QComboBox()
        self.output_combo.setVisible(False)
        form = QFormLayout()
        self.output_label = QLabel("받을 이미지")
        self.output_label.setVisible(False)
        form.addRow(self.output_label, self.output_combo)
        root.addLayout(form)

        # --- 이름 / 설명 ------------------------------------------------
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: Z-Image Turbo")
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("비워도 됩니다")
        form.addRow("이름", self.name_edit)
        form.addRow("설명", self.desc_edit)

        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#c62828; font-size:14px;")
        self.hint.setVisible(False)
        root.addWidget(self.hint)

        # --- 버튼 ------------------------------------------------------
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.clicked.connect(self.reject)
        self.register_btn = QPushButton("등록")
        self.register_btn.setEnabled(False)
        self.register_btn.clicked.connect(self.accept)
        buttons.addWidget(self.register_btn)
        buttons.addWidget(self.cancel_btn)
        root.addLayout(buttons)

    # --- 검사 결과 그리기 ----------------------------------------------

    @staticmethod
    def _item_html(item: CheckItem) -> str:
        color, mark = _STYLE.get(item.level, ("#333333", "·"))
        out = [f'<p style="margin:4px 0 0">'
               f'<b style="color:{color}">{mark} {_esc(item.title)}</b></p>']
        if item.detail:
            body = _esc(item.detail).replace("\n", "<br>")
            out.append(f'<p style="margin:0 0 2px 20px;color:#444">{body}</p>')
        for label, value in item.rows:
            if label:
                out.append(f'<p style="margin:2px 0 0 20px">'
                           f'<code>{_esc(label)}</code></p>')
            if value:
                out.append(f'<p style="margin:0 0 0 34px;color:#777">'
                           f'{_esc(value)}</p>')
        for label, url in item.links:
            out.append(f'<p style="margin:2px 0 0 34px">'
                       f'<a href="{_esc(url)}">{_esc(label)} 에서 찾기 →</a></p>')
        if item.actions:
            out.append('<div style="margin:6px 0 10px 20px;color:#333">')
            for index, action in enumerate(item.actions, 1):
                out.append(f'<div style="margin:1px 0">{index}. {_esc(action)}</div>')
            out.append("</div>")
        return "".join(out)

    def _render(self, report: CheckReport) -> None:
        self.report_view.setHtml(
            "".join(self._item_html(i) for i in report.items)
        )

        prompt = prompt_of(self._data or {}) or {}
        self.output_combo.clear()
        for node_id in report.outputs:
            node = prompt.get(node_id) or {}
            title = (node.get("_meta") or {}).get("title") or node_id
            self.output_combo.addItem(title, node_id)
        # 결과가 하나면 고를 것이 없다. 칸을 미리 보여주지 않는다.
        multi = len(report.outputs) > 1
        self.output_combo.setVisible(multi)
        self.output_label.setVisible(multi)

        self.register_btn.setEnabled(not report.blocked)
        if report.blocked:
            self.hint.setText(
                "이대로는 등록할 수 없습니다. 위 안내대로 준비한 뒤 다시 가져오세요."
            )
        elif not report.ready:
            self.hint.setText("경고가 있지만 등록은 됩니다.")
        else:
            self.hint.setText("")
        self.hint.setVisible(bool(self.hint.text()))

    # --- 파일 열기와 검사 ------------------------------------------------

    @staticmethod
    def _default_name(path: Path) -> str:
        """파일 이름에서 관례적인 접두사를 뗀다.

        'api_image_z_image_turbo' -> 'z image turbo'
        접두사는 여러 개 겹칠 수 있어 반복해서 뺀다.
        """
        stem = path.stem
        prefixes = ("api_", "예시", "workflow_", "image_", "video_")
        changed = True
        while changed:
            changed = False
            for prefix in prefixes:
                if stem.lower().startswith(prefix.lower()):
                    stem = stem[len(prefix):]
                    changed = True
                    break
        return stem.replace("_", " ").strip() or path.stem

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "워크플로 파일 가져오기", "",
            "워크플로 (*.json);;모든 파일 (*.*)",
        )
        if path:
            self.open_file(path)

    def open_file(self, path) -> None:
        """파일을 읽고 검사 결과를 화면에 그린다."""
        path = Path(path)
        self.file_label.setText(path.name)
        try:
            self._data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._data = None
            self._path = None
            self.report_view.setHtml(
                f'<p style="color:#c62828">파일을 읽을 수 없습니다.<br>'
                f'{_esc(exc)}</p>'
            )
            self.register_btn.setEnabled(False)
            return
        self._path = path
        if not self.name_edit.text():
            self.name_edit.setText(self._default_name(path))
        self._check()

    def _check(self) -> None:
        report = check_workflow(
            self._data or {}, self._known_types, self._installed,
            self._models_dir or None,
        )
        self._report = report
        self._render(report)
        self._ask_node_types()

    def _ask_node_types(self) -> None:
        """노드 종류는 필요할 때 한 번만 읽는다. (응답이 매우 크다)"""
        if self._known_types is not None or self._engine is None:
            return
        self._worker = NodeTypesWorker(self._engine)
        self._worker.fetched.connect(self._on_node_types)
        self._worker.start()

    def _on_node_types(self, types) -> None:
        """노드 종류를 받아온 뒤 다시 검사한다."""
        self._known_types = set(types or ())
        if self._data is None:
            return
        report = check_workflow(
            self._data, self._known_types, self._installed,
            self._models_dir or None,
        )
        self._report = report
        self._render(report)

    # --- 값 꺼내기 ------------------------------------------------------

    def workflow_name(self) -> str:
        return self.name_edit.text().strip()

    def workflow_description(self) -> str:
        return self.desc_edit.text().strip()

    def chosen_output(self) -> str:
        """사용자가 고른 결과 노드. 고르지 않았으면 빈 문자열."""
        return self.output_combo.currentData() or ""

    def needs_output_choice(self) -> bool:
        """결과가 여러 개여서 고를 곳이 필요한가.

        창이 열리기 전에는 setVisible(True) 를 해도 isVisible() 이 False 라
        '숨겨졌는지' 알 수 없다. 이 값으로 판단한다.
        """
        return self.output_combo.count() > 1

    def source_path(self):
        return self._path

    def document(self):
        return self._data

    def report(self):
        return self._report