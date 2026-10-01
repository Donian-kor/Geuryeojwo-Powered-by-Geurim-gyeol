from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QSplitter, QMessageBox, QToolBar,
    QFormLayout, QGroupBox, QTextEdit,
)
from app.engine.session.manager import SessionManager, SessionMetadata


class SessionHistoryBrowser(QWidget):
    """Session History Browser 위젯.

    sessions/YYYY-MM-DD/HHmmss-N/ 구조의 세션을 브라우징한다.
    - 세션 메타데이터 확인
    - 세션 내 이미지 미리보기
    - 프롬프트 복사
    - 결과 재생성
    - 세션 삭제
    """

    regenerate_requested = Signal(str, dict, object)
    prompt_copied = Signal(str)

    def __init__(self, sessions_root: Path, parent=None):
        super().__init__(parent)
        self.sessions_root = sessions_root
        self.session_manager = SessionManager(sessions_root)
        self.setWindowTitle("Session History")
        self.resize(1000, 700)

        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QToolBar()
        toolbar.setMovable(False)
        self._toolbar_buttons = {}

        btn_refresh = QPushButton("새로고침")
        btn_delete = QPushButton("세션 삭제")
        btn_copy = QPushButton("Prompt 복사")
        btn_regen = QPushButton("재생성")

        self._toolbar_buttons["refresh"] = btn_refresh
        self._toolbar_buttons["delete"] = btn_delete
        self._toolbar_buttons["copy"] = btn_copy
        self._toolbar_buttons["regen"] = btn_regen

        for btn in [btn_refresh, btn_delete, btn_copy, btn_regen]:
            toolbar.addWidget(btn)
        layout.addWidget(toolbar)

        splitter = QSplitter(Qt.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["세션 ID", "이미지 수", "생성 일시"])
        self.tree.itemClicked.connect(self._on_item_selected)
        splitter.addWidget(self.tree)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.metadata_group = QGroupBox("Session 메타데이터")
        meta_layout = QFormLayout(self.metadata_group)
        self.lbl_original = QLabel("")
        self.lbl_enhanced = QTextEdit()
        self.lbl_enhanced.setReadOnly(True)
        self.lbl_enhanced.setMaximumHeight(100)
        self.lbl_negative = QTextEdit()
        self.lbl_negative.setReadOnly(True)
        self.lbl_negative.setMaximumHeight(80)
        self.lbl_params = QLabel("")
        meta_layout.addRow("원본 프롬프트:", self.lbl_original)
        meta_layout.addRow("강화 프롬프트:", self.lbl_enhanced)
        meta_layout.addRow("Negative:", self.lbl_negative)
        meta_layout.addRow("파라미터:", self.lbl_params)
        right_layout.addWidget(self.metadata_group, 2)

        self.image_list = QTreeWidget()
        self.image_list.setColumnCount(2)
        self.image_list.setHeaderLabels(["이미지", "Seed"])
        self.image_list.itemDoubleClicked.connect(self._on_image_double_clicked)
        right_layout.addWidget(QLabel("이미지 (더블클릭 미리보기)"), 1)
        right_layout.addWidget(self.image_list, 4)

        self.image_preview = QLabel("이미지를 선택해주세요")
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setMinimumSize(220, 180)
        self.image_preview.setStyleSheet("border: 1px solid #444; background: #222; color: #888;")
        right_layout.addWidget(self.image_preview, 3)

        splitter.addWidget(right_panel)
        layout.addWidget(splitter)

        btn_refresh.clicked.connect(self._refresh_list)
        btn_delete.clicked.connect(self._delete_session)
        btn_copy.clicked.connect(self._copy_prompt)
        btn_regen.clicked.connect(self._regenerate)

        self._current_session_path: Path | None = None

    def _refresh_list(self) -> None:
        """Session 목록 새로고침."""
        self.tree.clear()
        sessions = self.session_manager.list_sessions()

        for session_path in sessions:
            try:
                metadata, images = self.session_manager.get_session(session_path)
            except Exception:
                continue

            date_str = session_path.parent.name
            session_id = session_path.name

            date_item = self._ensure_date_item(date_str)
            item = QTreeWidgetItem([
                session_id,
                str(len(images)),
                metadata.created_at,
            ])
            item.setData(0, Qt.UserRole, str(session_path))
            date_item.addChild(item)

        self.tree.expandAll()

    def _ensure_date_item(self, date_str: str) -> QTreeWidgetItem:
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.text(0) == date_str:
                return item
        date_item = QTreeWidgetItem([date_str, "", ""])
        date_item.setData(0, Qt.UserRole, "date")
        self.tree.addTopLevelItem(date_item)
        return date_item

    def _on_item_selected(self, item: QTreeWidgetItem, column: int) -> None:
        """세션 선택 처리."""
        if item.data(0, Qt.UserRole) == "date":
            return

        session_path = Path(item.data(0, Qt.UserRole))
        self._current_session_path = session_path

        try:
            metadata, images = self.session_manager.get_session(session_path)
        except Exception as e:
            QMessageBox.warning(self, "오류", f"세션을 불러올 수 없습니다: {e}")
            return

        self.lbl_original.setText(metadata.original_prompt)
        self.lbl_enhanced.setPlainText(metadata.enhanced_prompt)
        self.lbl_negative.setPlainText(metadata.negative_prompt)
        self.lbl_params.setText(
            f"LLM: {metadata.llm_model or 'N/A'} | "
            f"Image Model: {metadata.image_model}\n"
            f"Seed: {metadata.seed} | "
            f"{metadata.width}x{metadata.height} | "
            f"Steps: {metadata.steps} | CFG: {metadata.cfg}\n"
            f"Sampler: {metadata.sampler} | "
            f"Generated: {metadata.created_at}"
        )

        self.image_list.clear()
        for img_path in images:
            img_item = QTreeWidgetItem([img_path.name, ""])
            img_item.setData(0, Qt.UserRole, str(img_path))
            self.image_list.addTopLevelItem(img_item)

    def _on_image_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """이미지 더블클릭 - 미리보기 표시."""
        img_path = Path(item.data(0, Qt.UserRole))
        pixmap = QPixmap(str(img_path))
        if pixmap.isNull():
            self.image_preview.setText("이미지를 불러올 수 없습니다")
        else:
            self.image_preview.setPixmap(pixmap.scaled(
                self.image_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

    def _delete_session(self) -> None:
        """선택된 세션 삭제."""
        if not self._current_session_path:
            return

        reply = QMessageBox.question(
            self, "삭제 확인",
            f"{self._current_session_path.name} 세션을 삭제하시겠습니까?\n"
            "모든 이미지와 메타데이터가 영구 삭제됩니다."
        )
        if reply == QMessageBox.Yes:
            self.session_manager.delete_session(self._current_session_path)
            self._refresh_list()
            self._current_session_path = None

    def _copy_prompt(self) -> None:
        """프롬프트 복사."""
        if not self._current_session_path:
            return

        try:
            metadata, _ = self.session_manager.get_session(self._current_session_path)
            from PySide6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(metadata.enhanced_prompt)
            self.prompt_copied.emit(metadata.enhanced_prompt)
        except Exception as e:
            QMessageBox.warning(self, "오류", f"프롬프트를 복사할 수 없습니다: {e}")

    def _regenerate(self) -> None:
        """결과 재생성."""
        if not self._current_session_path:
            return

        try:
            metadata, images = self.session_manager.get_session(self._current_session_path)
            self.regenerate_requested.emit(
                metadata.enhanced_prompt,
                {
                    "seed": metadata.seed,
                    "width": metadata.width,
                    "height": metadata.height,
                    "steps": metadata.steps,
                    "cfg": metadata.cfg,
                    "sampler": metadata.sampler,
                    "scheduler": metadata.scheduler,
                },
                metadata.image_model,
            )
        except Exception as e:
            QMessageBox.warning(self, "오류", f"재생성할 수 없습니다: {e}")
