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
    목록은 이미지 한 장이 한 줄이다 (썸네일 + 프롬프트 + seed + 시각).
    여러 장을 뽑은 세션만 첫 줄 아래에 자식 행이 생긴다.

    - sessions/YYYY-MM-DD/세션이름/ 의 이미지를 최신순으로 브라우징한다
    - 세션에 들어가지 않은 outputs/ 이미지도 같은 목록 끝에 보여준다
    - 세션 메타데이터 (원본/강화 프롬프트, LLM, 워크플로) 확인
    - 프롬프트 복사 / 결과 재생성 (워크플로 자동 선택)
    - 이미지 삭제 / 세션 삭제
    - 폴더 열기 / 다른 이름으로 저장
    """

    # 목록 한 줄에 붙는 썸네일 크기(px)
    _THUMB_SIZE = 40

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
        # 썸네일이 붙으므로 첫 열을 넓히고, Seed 는 잘리지 않게 고정폭을 준다
        self.tree.setColumnWidth(0, 380)
        self.tree.setColumnWidth(1, 150)
        header = self.tree.header()
        header.setStretchLastSection(True)
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
        """기록을 한 줄짜리 목록으로 다시 만든다.

        세션 하나가 이미지를 한 장만 가지므로 (batch_size 기본 1)
        '날짜 > 세션 > 이미지' 3단계는 정보가 겹친다. 이미지가 1장이면
        세션 행이 곧 이미지 행이므로 한 줄로 펴고, 첫 칸에 썸네일과
        프롬프트를 함께 보여준다. 여러 장인 세션만 자식 행을 둔다.
        """
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

            prompt = metadata.original_prompt or metadata.enhanced_prompt
            parent_item = None
            for image_path in images:
                item = self._make_item(
                    text=self._row_text(prompt, image_path, first=parent_item is None),
                    seed=metadata.seed,
                    created_at=metadata.created_at,
                    payload=("session", str(session_path), str(image_path)),
                    image_path=image_path,
                )
                if parent_item is None:
                    parent_item = item
                    self.tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)

        self._add_ungrouped_outputs()

    def _make_item(self, text: str, seed, created_at: str, payload: tuple,
                   image_path: Path) -> QTreeWidgetItem:
        """목록 한 줄을 만든다 (썸네일 + 텍스트 + seed + 시각)."""
        item = QTreeWidgetItem([text, str(seed), created_at])
        item.setData(0, Qt.UserRole, payload)
        icon = self._thumbnail(image_path)
        if icon is not None:
            item.setIcon(0, icon)
        return item

    def _row_text(self, prompt: str, image_path: Path, first: bool) -> str:
        """첫 줄은 프롬프트, 이후 줄(다중 이미지)은 파일명으로 구분한다."""
        if not first:
            return image_path.name
        text = " ".join((prompt or "").split())
        if not text:
            return image_path.name
        if len(text) > 60:
            text = text[:60].rstrip() + "…"
        return text

    def _thumbnail(self, image_path: Path) -> QPixmap | None:
        """목록용 작은 썸네일. 읽을 수 없으면 None (텍스트만 표시)."""
        if not image_path or not image_path.exists():
            return None
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            return None
        return pixmap.scaled(
            self._THUMB_SIZE, self._THUMB_SIZE,
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )

    def _add_ungrouped_outputs(self) -> None:
        """세션이 참조하지 않은 outputs/ 이미지를 목록 끝에 추가한다.

        생성 도중 세션 기록이 실패했거나 예전 버전에서 만든 이미지처럼
        세션에 속하지 않는 결과도 사라지지 않아야 한다.
        """
        import os

        try:
            referenced = self.session_manager.list_source_outputs()
        except Exception:
            referenced = set()

        loose: list[tuple[Path, object]] = []
        for png_path, _ in self.output_manager.list_outputs():
            key = os.path.normcase(os.path.abspath(str(png_path)))
            if key in referenced:
                continue
            try:
                metadata, _ = self.output_manager.get_output(png_path)
            except Exception:
                continue
            loose.append((png_path, metadata))

        # 최신순으로 섞어 넣는다
        for png_path, metadata in loose:
            prompt = getattr(metadata, "original_prompt", "") or metadata.prompt
            self.tree.addTopLevelItem(self._make_item(
                text=self._row_text(prompt, png_path, first=True),
                seed=metadata.seed,
                created_at=metadata.created_at,
                payload=("loose", "", str(png_path)),
                image_path=png_path,
            ))

    # ---------------------------------------------------------------- 선택

    def _on_item_selected(self, item: QTreeWidgetItem, column: int) -> None:
        """목록 한 줄을 선택하면 곧바로 메타데이터와 미리보기를 보여준다.

        한 줄짜리 목록이라 세션 행/이미지 행 구분이 없다. 한 줄이 곧
        이미지 한 장이므로 클릭 1번으로 결과를 볼 수 있다.
        """
        data = item.data(0, Qt.UserRole)
        kind = data[0] if isinstance(data, tuple) else None

        if kind in ("session", "loose") and len(data) >= 3 and data[2]:
            session_path = Path(data[1]) if data[1] else None
            image_path = Path(data[2])
            self._current_session = session_path
            self._current_image = image_path
            self._show_image_metadata(session_path, image_path)
            self._show_preview(image_path)
            return

        self._current_session = None
        self._current_image = None

    def _clear_metadata(self) -> None:
        """우측 메타데이터/미리보기를 비운다."""
        self.lbl_original.setText("")
        self.lbl_enhanced.setPlainText("")
        self.lbl_negative.setPlainText("")
        self.lbl_params.setText("")
        self.image_preview.clear()
        self.image_preview.setText("이미지를 선택해주세요")

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