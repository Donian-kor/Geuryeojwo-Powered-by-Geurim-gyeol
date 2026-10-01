from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QSplitter, QMessageBox, QToolBar,
    QFormLayout, QGroupBox, QTextEdit, QFileDialog,
)
from app.engine.session.manager import SessionManager
from app.engine.output.manager import OutputManager


class HistoryBrowser(QWidget):
    """기록 브라우저 위젯.

    Output Browser 와 Session History 를 하나로 합친 위젯.
    트리는 날짜 > 세션 > 이미지 3단계로 구성된다.

    - sessions/YYYY-MM-DD/HHmmss-N/ 세션과 세션 안의 이미지를 브라우징한다
    - 세션에 들어가지 않은 outputs/ 이미지��� 별도 그룹으로 보여준다
    - 세션 메타데이터 (원본/강화 프롬프트, LLM, 워크플로) 확인
    - 이미지 단위 메타데이터 확인
    - 프롬프트 복사 / 결과 재생성 (워크플로 자동 선택)
    - 이미지 삭제 / 세션 삭제
    - 폴더 열기 / 다른 이름으로 저장
    """

    regenerate_requested = Signal(str, dict, object)
    prompt_copied = Signal(str)

    def __init__(self, sessions_root: Path, outputs_root: Path | None = None, parent=None):
        super().__init__(parent)
        self.sessions_root = sessions_root
        self.outputs_root = outputs_root or sessions_root.parent / "outputs"
        self.session_manager = SessionManager(sessions_root)
        self.output_manager = OutputManager(self.outputs_root)
        self.setWindowTitle("History")
        self.resize(1100, 720)

        self._current_session: Path | None = None
        self._current_image: Path | None = None

        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QToolBar()
        toolbar.setMovable(False)
        self._toolbar_buttons = {}

        btn_refresh = QPushButton("새로고침")
        btn_open = QPushButton("폴더 열기")
        btn_save = QPushButton("다른 이름으로 저장")
        btn_delete = QPushButton("삭제")
        btn_copy = QPushButton("Prompt 복사")
        btn_regen = QPushButton("재생성")

        self._toolbar_buttons["refresh"] = btn_refresh
        self._toolbar_buttons["open"] = btn_open
        self._toolbar_buttons["save"] = btn_save
        self._toolbar_buttons["delete"] = btn_delete
        self._toolbar_buttons["copy"] = btn_copy
        self._toolbar_buttons["regen"] = btn_regen

        for btn in (btn_refresh, btn_open, btn_save, btn_delete, btn_copy, btn_regen):
            toolbar.addWidget(btn)
        layout.addWidget(toolbar)

        splitter = QSplitter(Qt.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["항목", "Seed", "생성 일시"])
        self.tree.itemClicked.connect(self._on_item_selected)
        splitter.addWidget(self.tree)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.metadata_group = QGroupBox("메타데이터")
        meta_layout = QFormLayout(self.metadata_group)
        self.lbl_original = QLabel("")
        self.lbl_original.setWordWrap(True)
        self.lbl_enhanced = QTextEdit()
        self.lbl_enhanced.setReadOnly(True)
        self.lbl_enhanced.setMaximumHeight(100)
        self.lbl_negative = QTextEdit()
        self.lbl_negative.setReadOnly(True)
        self.lbl_negative.setMaximumHeight(80)
        self.lbl_params = QLabel("")
        self.lbl_params.setWordWrap(True)
        meta_layout.addRow("원본 프롬프트:", self.lbl_original)
        meta_layout.addRow("최종 프롬프트:", self.lbl_enhanced)
        meta_layout.addRow("Negative:", self.lbl_negative)
        meta_layout.addRow("파라미터:", self.lbl_params)
        right_layout.addWidget(self.metadata_group, 2)

        self.image_preview = QLabel("이미지를 선택해주세요")
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setMinimumSize(220, 180)
        self.image_preview.setStyleSheet("border: 1px solid #444; background: #222; color: #888;")
        right_layout.addWidget(self.image_preview, 3)

        splitter.addWidget(right_panel)
        layout.addWidget(splitter)

        btn_refresh.clicked.connect(self._refresh_list)
        btn_open.clicked.connect(self._open_folder)
        btn_save.clicked.connect(self._save_as)
        btn_delete.clicked.connect(self._delete_selected)
        btn_copy.clicked.connect(self._copy_prompt)
        btn_regen.clicked.connect(self._regenerate)

    # ---------------------------------------------------------------- 트리

    def _refresh_list(self) -> None:
        """세션 + 미분류 출력 목록을 새로고침."""
        self.tree.clear()
        self._current_session = None
        self._current_image = None
        # 트리가 비워졌는데 우측 패널에 삭제된 항목 정보가 남아 있으면 안 된다
        self._clear_metadata()

        for session_path in self.session_manager.list_sessions():
            try:
                metadata, images = self.session_manager.get_session(session_path)
            except Exception:
                continue

            date_item = self._ensure_date_item(session_path.parent.name)
            session_item = QTreeWidgetItem([
                session_path.name,
                str(metadata.seed),
                metadata.created_at,
            ])
            # 세션 노드는 재생성 시 워크플로를 되찾아야 하므로 이름을 함께 실어 둔다
            session_item.setData(0, Qt.UserRole, ("session", str(session_path)))
            session_item.setData(0, Qt.UserRole + 1, metadata.image_model)
            date_item.addChild(session_item)

            for img_path in images:
                img_item = QTreeWidgetItem([img_path.name, "", ""])
                img_item.setData(0, Qt.UserRole, ("image", str(session_path), str(img_path)))
                session_item.addChild(img_item)

        self._add_ungrouped_outputs()

        # 날짜·세션·이미지를 모두 펼친다.
        # 예전에는 여기서 날짜 그룹을 다시 접었다. 그런데 생성이 끝나면
        # done() 이 이 함수를 다시 불러, 방금 만든 세션이 접힌 날짜 안에
        # 숨어 "세션이 안 남는 것"처럼 보였다. 펼친 상태를 유지한다.
        self.tree.expandAll()

    def _ensure_date_item(self, date_str: str) -> QTreeWidgetItem:
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.text(0) == date_str:
                return item
        date_item = QTreeWidgetItem([date_str, "", ""])
        date_item.setData(0, Qt.UserRole, ("date",))
        self.tree.addTopLevelItem(date_item)
        return date_item

    def _add_ungrouped_outputs(self) -> None:
        """세션이 참조하지 않은 outputs/ 이미지를 '미분류' 그룹으로 추가한다.

        생성 도중 세션 기록이 실패했거나 예전 버전에서 만든 이미지처럼
        세션에 속하지 않는 결과도 사라지지 않아야 한다.
        """
        import os

        try:
            referenced = self.session_manager.list_source_outputs()
        except Exception:
            referenced = set()

        loose_by_date: dict[str, list[tuple[Path, object]]] = {}
        for png_path, _ in self.output_manager.list_outputs():
            key = os.path.normcase(os.path.abspath(str(png_path)))
            if key in referenced:
                continue
            try:
                metadata, _ = self.output_manager.get_output(png_path)
            except Exception:
                continue
            loose_by_date.setdefault(png_path.parent.name, []).append((png_path, metadata))

        for date_str, entries in sorted(loose_by_date.items(), reverse=True):
            date_item = self._ensure_date_item(date_str)
            group = QTreeWidgetItem([f"미분류 ({len(entries)})", "", ""])
            group.setData(0, Qt.UserRole, ("loose_group",))
            date_item.addChild(group)
            for png_path, metadata in entries:
                img_item = QTreeWidgetItem([png_path.name, str(metadata.seed), metadata.created_at])
                # (이미지, 세션 경로 없음, 이미지 경로, 워크플로 이름)
                img_item.setData(0, Qt.UserRole, ("loose", "", str(png_path), metadata.model))
                group.addChild(img_item)

    # ---------------------------------------------------------------- 선택

    def _on_item_selected(self, item: QTreeWidgetItem, column: int) -> None:
        """트리 아이템 선택 처리."""
        data = item.data(0, Qt.UserRole)
        kind = data[0] if isinstance(data, tuple) else None

        if kind in (None, "date", "loose_group"):
            self._current_session = None
            self._current_image = None
            return

        if kind == "session":
            self._current_session = Path(data[1])
            self._current_image = None
            self._show_session_metadata(self._current_session)
            self.image_preview.clear()
            self.image_preview.setText("이미지를 선택해주세요")
            return

        # kind == "image" 또는 "loose"
        session_path = Path(data[1]) if data[1] else None
        image_path = Path(data[2])
        self._current_session = session_path
        self._current_image = image_path

        self._show_image_metadata(session_path, image_path)
        self._show_preview(image_path)

    def _clear_metadata(self) -> None:
        """우측 메타데이터/미리보기를 비운다."""
        self.lbl_original.setText("")
        self.lbl_enhanced.setPlainText("")
        self.lbl_negative.setPlainText("")
        self.lbl_params.setText("")
        self.image_preview.clear()
        self.image_preview.setText("이미지를 선택해주세요")

    def _show_session_metadata(self, session_path: Path) -> None:
        try:
            metadata, _ = self.session_manager.get_session(session_path)
        except Exception as e:
            QMessageBox.warning(self, "오류", f"세션을 불러올 수 없습니다: {e}")
            return

        self.lbl_original.setText(metadata.original_prompt)
        self.lbl_enhanced.setPlainText(metadata.enhanced_prompt)
        self.lbl_negative.setPlainText(metadata.negative_prompt)
        self.lbl_params.setText(self._format_params(
            metadata.image_model, metadata.llm_model, metadata
        ))

    def _show_image_metadata(self, session_path: Path | None, image_path: Path) -> None:
        """이미지 선택 시: 세션 정보에 그 이미지의 개별 메타데이터를 얹는다."""
        if session_path is None:
            self._show_loose_metadata(image_path)
            return

        try:
            metadata, _ = self.session_manager.get_session(session_path)
        except Exception as e:
            QMessageBox.warning(self, "오류", f"세션을 불러올 수 없습니다: {e}")
            return

        # 이미지별 JSON 이 있으면 그 값(실제 적용된 파라미터)을 우선한다
        image_meta = None
        json_path = image_path.with_suffix(".json")
        if json_path.exists():
            try:
                import json as _json

                from app.engine.output.manager import OutputMetadata

                image_meta = OutputMetadata.from_dict(
                    _json.loads(json_path.read_text(encoding="utf-8"))
                )
            except Exception:
                image_meta = None

        self.lbl_original.setText(metadata.original_prompt)
        self.lbl_enhanced.setPlainText(
            image_meta.prompt if image_meta else metadata.enhanced_prompt
        )
        self.lbl_negative.setPlainText(
            image_meta.negative_prompt if image_meta else metadata.negative_prompt
        )
        self.lbl_params.setText(self._format_params(
            metadata.image_model, metadata.llm_model,
            image_meta if image_meta else metadata,
            file_name=image_path.name,
        ))

    def _show_loose_metadata(self, image_path: Path) -> None:
        try:
            metadata, _ = self.output_manager.get_output(image_path)
        except Exception as e:
            QMessageBox.warning(self, "오류", f"메타데이터를 불러올 수 없습니다: {e}")
            return

        self.lbl_original.setText("(세션 없음)")
        self.lbl_enhanced.setPlainText(metadata.prompt)
        self.lbl_negative.setPlainText(metadata.negative_prompt)
        self.lbl_params.setText(self._format_params(
            metadata.model, metadata.llm_model, metadata, file_name=image_path.name
        ))

    def _format_params(
        self,
        image_model: str,
        llm_model: str | None,
        source,
        file_name: str | None = None,
    ) -> str:
        text = (
            f"Workflow: {image_model} | "
            f"LLM: {llm_model or 'N/A'}\n"
            f"Seed: {source.seed} | "
            f"{source.width}x{source.height} | "
            f"Steps: {source.steps} | CFG: {source.cfg}\n"
            f"Sampler: {source.sampler} | Scheduler: {getattr(source, 'scheduler', '-')}"
        )
        if file_name:
            text += f"\nFile: {file_name}"
        return text

    def _show_preview(self, image_path: Path) -> None:
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self.image_preview.setText("이미지를 불러올 수 없습니다")
        else:
            self.image_preview.setPixmap(pixmap.scaled(
                self.image_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))

    # ---------------------------------------------------------------- 동작

    def _open_folder(self) -> None:
        """OS 기본 파일 탐색기로 폴더를 연다.

        선택된 세션이 있으면 그 세션 폴더, 없으면 sessions 루트를 연다.
        """
        import subprocess
        import sys

        target = self._current_session or self.sessions_root
        path = str(Path(target).resolve())
        try:
            if sys.platform == "win32":
                import os

                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            # 폴더를 못 여도 프로그램 전체가 멈추면 안 된다
            pass

    def _save_as(self) -> None:
        """선택된 이미지를 다른 이름으로 저장."""
        if not self._current_image:
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "이미지 저장", str(self._current_image),
            "PNG Images (*.png);;All Files (*)"
        )
        if not save_path:
            return
        import shutil

        try:
            shutil.copy2(self._current_image, save_path)
        except Exception as e:
            QMessageBox.warning(self, "오류", f"저장할 수 없습니다: {e}")

    def _delete_selected(self) -> None:
        """이미지 선택이면 그 이미지만, 아니면 세션 전체를 삭제."""
        if self._current_image:
            self._delete_image(self._current_image)
            return
        if self._current_session:
            self._delete_session(self._current_session)

    def _delete_image(self, image_path: Path) -> None:
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"{image_path.name}을(를) 삭제하시겠습니까?\n메타데이터도 함께 삭제됩니다."
        )
        if reply != QMessageBox.Yes:
            return

        if self._current_session:
            self.session_manager.remove_image_from_session(
                self._current_session, image_path.name
            )
        else:
            self.output_manager.delete_output(image_path)
        self._refresh_list()

    def _delete_session(self, session_path: Path) -> None:
        reply = QMessageBox.question(
            self, "삭제 확인",
            f"{session_path.name} 세션을 삭제하시겠습니까?\n"
            "모든 이미지와 메타데이터가 영구 삭제됩니다."
        )
        if reply != QMessageBox.Yes:
            return
        self.session_manager.delete_session(session_path)
        self._refresh_list()

    def _copy_prompt(self) -> None:
        """프롬프트 복사 (세션은 강화 프롬프트, 미분류는 저장된 프롬프트)."""
        from PySide6.QtWidgets import QApplication

        text = ""
        if self._current_image:
            if self._current_session:
                try:
                    metadata, _ = self.session_manager.get_session(self._current_session)
                    text = metadata.enhanced_prompt
                except Exception as e:
                    QMessageBox.warning(self, "오류", f"프롬프트를 복사할 수 없습니다: {e}")
                    return
            else:
                try:
                    metadata, _ = self.output_manager.get_output(self._current_image)
                    text = metadata.prompt
                except Exception as e:
                    QMessageBox.warning(self, "오류", f"프롬프트를 복사할 수 없습니다: {e}")
                    return
        elif self._current_session:
            try:
                metadata, _ = self.session_manager.get_session(self._current_session)
                text = metadata.enhanced_prompt
            except Exception as e:
                QMessageBox.warning(self, "오류", f"프롬프트를 복사할 수 없습니다: {e}")
                return

        if not text:
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.prompt_copied.emit(text)

    def _regenerate(self) -> None:
        """결과 재생성 — 워크플로 이름까지 함께 넘긴다."""
        image_model = None
        prompt = ""
        params: dict = {}

        if self._current_session:
            try:
                metadata, _ = self.session_manager.get_session(self._current_session)
            except Exception as e:
                QMessageBox.warning(self, "오류", f"재생성할 수 없습니다: {e}")
                return
            prompt = metadata.enhanced_prompt
            image_model = metadata.image_model
            params = self._params_of(metadata)
        elif self._current_image:
            try:
                metadata, _ = self.output_manager.get_output(self._current_image)
            except Exception as e:
                QMessageBox.warning(self, "오류", f"재생성할 수 없습니다: {e}")
                return
            prompt = metadata.prompt
            image_model = metadata.model
            params = self._params_of(metadata)
        else:
            return

        self.regenerate_requested.emit(prompt, params, image_model)

    def _params_of(self, metadata) -> dict:
        return {
            "seed": metadata.seed,
            "width": metadata.width,
            "height": metadata.height,
            "steps": metadata.steps,
            "cfg": metadata.cfg,
            "sampler": metadata.sampler,
            "scheduler": metadata.scheduler,
        }