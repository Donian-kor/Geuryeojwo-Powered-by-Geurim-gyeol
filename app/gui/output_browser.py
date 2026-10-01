from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QSplitter, QMessageBox, QToolBar,
    QFileDialog,
)
from app.engine.output.manager import OutputManager, OutputMetadata


class OutputBrowser(QWidget):
    """Output Browser 위젯 (v0.1 §23).

    outputs/YYYY-MM-DD/ 구조의 이미지를 브라우징한다.
    - 자동 파일명 기록 확인
    - Seed 확인
    - Metadata 확인
    - Open Output Folder
    - Save As
    - 결과 삭제
    - 결과 재생성
    - Prompt 복사
    """

    regenerate_requested = Signal(str, dict)
    prompt_copied = Signal(str)

    def __init__(self, outputs_root: Path, parent=None):
        super().__init__(parent)
        self.outputs_root = outputs_root
        self.output_manager = OutputManager(outputs_root)
        self.setWindowTitle("Output Browser")
        self.resize(800, 600)

        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QToolBar()
        toolbar.setMovable(False)
        self._toolbar_buttons = {}

        btn_refresh = QPushButton("새로고침")
        btn_open = QPushButton("폴더 열기")
        btn_delete = QPushButton("삭제")
        btn_save = QPushButton("다른 이름으로 저장")
        btn_regen = QPushButton("재생성")
        btn_copy = QPushButton("Prompt 복사")

        self._toolbar_buttons["refresh"] = btn_refresh
        self._toolbar_buttons["open"] = btn_open
        self._toolbar_buttons["delete"] = btn_delete
        self._toolbar_buttons["save"] = btn_save
        self._toolbar_buttons["regen"] = btn_regen
        self._toolbar_buttons["copy"] = btn_copy

        for btn in [btn_refresh, btn_open, btn_delete, btn_save, btn_regen, btn_copy]:
            toolbar.addWidget(btn)
        layout.addWidget(toolbar)

        splitter = QSplitter(Qt.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["이미지", "Seed", "생성 일시"])
        self.tree.itemClicked.connect(self._on_item_selected)
        splitter.addWidget(self.tree)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.image_preview = QLabel("이미지를 선택해주세요")
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setMinimumSize(220, 180)
        self.image_preview.setStyleSheet("border: 1px solid #444; background: #222; color: #888;")
        right_layout.addWidget(self.image_preview, 3)

        self.meta_label = QLabel("메타데이터가 여기에 표시됩니다")
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet("padding: 8px; background: #1a1a1a; color: #ddd; border-radius: 4px;")
        right_layout.addWidget(self.meta_label, 2)

        splitter.addWidget(right_panel)
        layout.addWidget(splitter)

        btn_refresh.clicked.connect(self._refresh_list)
        btn_open.clicked.connect(self._open_folder)
        btn_delete.clicked.connect(self._delete_selected)
        btn_save.clicked.connect(self._save_as)
        btn_regen.clicked.connect(self._regenerate)
        btn_copy.clicked.connect(self._copy_prompt)

    def _refresh_list(self) -> None:
        """Output 목록 새로고침."""
        self.tree.clear()
        outputs = self.output_manager.list_outputs()

        for png_path, json_path in outputs:
            try:
                metadata, _ = self.output_manager.get_output(png_path)
            except Exception:
                continue

            date_str = png_path.parent.name
            item = QTreeWidgetItem([
                png_path.name,
                str(metadata.seed),
                metadata.created_at,
            ])
            item.setData(0, Qt.UserRole, str(png_path))
            item.setData(1, Qt.UserRole, metadata)

            date_item = QTreeWidgetItem([date_str, "", ""])
            date_item.setData(0, Qt.UserRole, "date")
            date_item.appendChild(item)

            top = self._ensure_date_item(date_str)
            top.addChild(item)

        # 정리
        for i in range(self.tree.topLevelItemCount()):
            top_item = self.tree.topLevelItem(i)
            top_item.expandAll()

    def _ensure_date_item(self, date_str: str):
        """날짜별 그룹 아이템 가져오기."""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.text(0) == date_str:
                return item
        date_item = QTreeWidgetItem([date_str, "", ""])
        date_item.setData(0, Qt.UserRole, "date")
        self.tree.addTopLevelItem(date_item)
        return date_item

    def _on_item_selected(self, item: QTreeWidgetItem, column: int) -> None:
        """트리 아이템 선택 처리."""
        if item.data(0, Qt.UserRole) == "date":
            return

        png_path = Path(item.data(0, Qt.UserRole))
        try:
            metadata, _ = self.output_manager.get_output(png_path)
        except Exception as e:
            QMessageBox.warning(self, "오류", f"메타데이터를 불러올 수 없습니다: {e}")
            return

        pixmap = QPixmap(str(png_path))
        if pixmap.isNull():
            self.image_preview.setText("이미지를 불러올 수 없습니다")
        else:
            self.image_preview.setPixmap(pixmap.scaled(
                self.image_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

        self.meta_label.setText(
            f"Seed: {metadata.seed}\n"
            f"Model: {metadata.model}\n"
            f"Size: {metadata.width}x{metadata.height}\n"
            f"Steps: {metadata.steps} | CFG: {metadata.cfg}\n"
            f"Sampler: {metadata.sampler}\n"
            f"Prompt: {metadata.prompt}\n"
            f"Negative: {metadata.negative_prompt}\n"
            f"Created: {metadata.created_at}"
        )
        self._current_item = item

    def _open_folder(self) -> None:
        """출력 폴더 열기."""
        import subprocess
        try:
            subprocess.run(f"explorer {self.outputs_root}", check=True)
        except Exception:
            pass

    def _delete_selected(self) -> None:
        """선택된 출력 삭제."""
        item = getattr(self, '_current_item', None)
        if not item:
            return

        png_path = Path(item.data(0, Qt.UserRole))
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"{png_path.name}을(를) 삭제하시겠습니까?\nJSON 메타데이터도 함께 삭제됩니다."
        )
        if reply == QMessageBox.Yes:
            self.output_manager.delete_output(png_path)
            self.tree.removeItemWidget(item, 0)
            item.parent().removeChild(item)

    def _save_as(self) -> None:
        """다른 이름으로 저장."""
        item = getattr(self, '_current_item', None)
        if not item:
            return

        png_path = Path(item.data(0, Qt.UserRole))
        save_path, _ = QFileDialog.getSaveFileName(
            self, "이미지 저장", str(png_path),
            "PNG Images (*.png);;All Files (*)"
        )
        if save_path:
            import shutil
            shutil.copy2(png_path, save_path)

    def _regenerate(self) -> None:
        """결과 재생성."""
        item = getattr(self, '_current_item', None)
        if not item:
            return

        metadata: OutputMetadata = item.data(1, Qt.UserRole)
        self.regenerate_requested.emit(
            metadata.prompt,
            {
                "seed": metadata.seed,
                "width": metadata.width,
                "height": metadata.height,
                "steps": metadata.steps,
                "cfg": metadata.cfg,
            },
        )

    def _copy_prompt(self) -> None:
        """Prompt 복사."""
        item = getattr(self, '_current_item', None)
        if not item:
            return

        metadata: OutputMetadata = item.data(1, Qt.UserRole)
        from PySide6.QtGui import QClipboard
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(metadata.prompt)
        self.prompt_copied.emit(metadata.prompt)
