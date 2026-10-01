from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QGroupBox, QFormLayout, QComboBox,
    QMessageBox,
)
from app.engine.prompt.engine import PromptEngine


class PromptPreviewWidget(QWidget):
    """Prompt Preview 위젯 (v0.1 §25).

    흐름:
        1. Auto Generate - LLM이 프롬프트 생성
        2. Preview - 사용자가 생성된 프롬프트 확인
        3. User Edit - 사용자 수정 가능
        4. Generate - 최종 이미지 생성
    """

    generate_requested = Signal(str, str, str)

    def __init__(self, prompt_engine: PromptEngine, parent=None):
        super().__init__(parent)
        self.prompt_engine = prompt_engine
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.info_label = QLabel("1단계: 프롬프트를 입력하고 '강화' 버튼을 클릭하세요.")
        layout.addWidget(self.info_label)

        preview_box = QGroupBox("Prompt Preview")
        preview_layout = QFormLayout(preview_box)

        self.original_prompt = QTextEdit()
        self.original_prompt.setPlaceholderText("원본 프롬프트를 입력하세요...")
        self.original_prompt.setMinimumHeight(80)
        preview_layout.addRow("Original Prompt:", self.original_prompt)

        self.enhanced_prompt = QTextEdit()
        self.enhanced_prompt.setPlaceholderText("강화된 프롬프트가 여기에 표시됩니다...")
        self.enhanced_prompt.setMinimumHeight(100)
        preview_layout.addRow("Enhanced Prompt:", self.enhanced_prompt)

        self.negative_prompt = QTextEdit()
        self.negative_prompt.setReadOnly(True)
        self.negative_prompt.setMaximumHeight(70)
        preview_layout.addRow("Negative Prompt:", self.negative_prompt)

        self.target_model = QLabel("없음")
        preview_layout.addRow("Target Model:", self.target_model)

        self.prompt_style = QLabel("없음")
        preview_layout.addRow("Prompt Style:", self.prompt_style)

        layout.addWidget(preview_box)

        button_row = QHBoxLayout()
        self.enhance_btn = QPushButton("프롬프트 강화 (Auto Generate)")
        self.generate_btn = QPushButton("생성 (Generate)")
        self.generate_btn.setEnabled(False)
        button_row.addWidget(self.enhance_btn)
        button_row.addStretch()
        button_row.addWidget(self.generate_btn)
        layout.addLayout(button_row)

        self.enhance_btn.clicked.connect(self._enhance_prompt)
        self.generate_btn.clicked.connect(self._on_generate)

        self._current_architecture = "sdxl"
        self._current_llm = None

    def set_model(self, architecture: str, llm_path: str | None = None) -> None:
        """타겟 모델 및 LLM 설정."""
        self._current_architecture = architecture
        self._current_llm_path = llm_path
        self.target_model.setText(architecture)
        self.prompt_style.setText(
            self.prompt_engine.policy.get_prompt_style(architecture)
        )
        self._update_negative()

    def set_llm(self, llm_path: str | None) -> None:
        """LLM 경로 설정 (프롬프트 강화용)."""
        self._current_llm_path = llm_path

    def _update_negative(self) -> None:
        """Negative prompt 자동 업데이트."""
        negative = self.prompt_engine.negative(self._current_architecture)
        self.negative_prompt.setPlainText(negative)

    def _enhance_prompt(self) -> None:
        """Auto Generate 단계: LLM으로 프롬프트 강화."""
        user_prompt = self.original_prompt.toPlainText().strip()
        if not user_prompt:
            QMessageBox.warning(self, "입력 필요", "프롬프트를 입력해주세요.")
            return

        validation = self.prompt_engine.validate_prompt(user_prompt)
        if not validation.valid:
            msg = "\n".join(validation.errors)
            if validation.warnings:
                msg += "\n\n경고:\n" + "\n".join(validation.warnings)
            QMessageBox.warning(self, "프롬프트 오류", msg)
            return

        if self._current_llm_path:
            try:
                from app.engine.llm.manager import LocalLLM
                from app.engine.hardware.detector import detect_hardware
                hardware = detect_hardware()
                llm = LocalLLM(self._current_llm_path, hardware.device, self.prompt_engine.logger)
                llm = llm.load()

                system_prompt = self.prompt_engine.system_prompt(self._current_architecture)
                enhanced = llm.generate(system_prompt, user_prompt)
                llm.unload()

                self.enhanced_prompt.setPlainText(enhanced.strip())
                self.info_label.setText("2단계: Enhanced Prompt을 확인/수정하세요.")
                self.generate_btn.setEnabled(True)
                return
            except Exception as e:
                QMessageBox.warning(self, "LLM 오류", f"LLM 강화 실패: {e}\nFallback을 사용합니다.")
                self.prompt_engine.logger.warning("LLM enhancement failed: %s", e)

        enhanced = self.prompt_engine.fallback(user_prompt, self._current_architecture)
        self.enhanced_prompt.setPlainText(enhanced.strip())
        self.info_label.setText("2단계: Enhanced Prompt을 확인/수정하세요.")
        self.generate_btn.setEnabled(True)

    def _on_generate(self) -> None:
        """Generate 단계: 최종 프롬프트로 이미지 생성 요청."""
        enhanced = self.enhanced_prompt.toPlainText().strip()
        if not enhanced:
            QMessageBox.warning(self, "입력 필요", "강화된 프롬프트가 비어 있습니다.")
            return

        negative = self.negative_prompt.toPlainText().strip()
        self.generate_requested.emit(enhanced, negative, self.original_prompt.toPlainText())
        self.info_label.setText("3단계: 이미지 생성 중...")

    def get_final_prompt(self) -> str:
        """사용자가 수정한 최종 프롬프트 반환."""
        return self.enhanced_prompt.toPlainText().strip()

    def get_negative_prompt(self) -> str:
        """Negative prompt 반환."""
        return self.negative_prompt.toPlainText().strip()

    def reset(self) -> None:
        """상태 초기화."""
        self.enhanced_prompt.clear()
        self.generate_btn.setEnabled(False)
        self.info_label.setText("1단계: 프롬프트를 입력하고 '강화' 버튼을 클릭하세요.")
