from __future__ import annotations
import sys, logging
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QProgressBar,
    QMessageBox, QFormLayout, QGroupBox, QTabWidget, QDialog, QSizePolicy,
    QGridLayout,
)
from app.engine import GeurimGyeolEngine
from app.engine.generation.controller import GenerationRequest, GenerationResult
from app.gui.output_browser import OutputBrowser
from app.gui.session_browser import SessionHistoryBrowser
from app.gui.prompt_preview import PromptPreviewWidget
from app.gui.theme.manager import ThemeManager

ROOT = Path(__file__).resolve().parents[2]


class Worker(QThread):
    progress = Signal(int, str); done = Signal(str, dict); failed = Signal(str, object)
    def __init__(self, controller, req): super().__init__(); self.controller=controller; self.req=req
    def run(self):
        try:
            result: GenerationResult = self.controller.run(self.req, lambda v,m: self.progress.emit(v,m))
            if result.success:
                self.done.emit(str(result.image_path), result.metadata)
            else:
                self.failed.emit(result.error or "생성 실패", result.suggestion)
        except Exception as e: self.failed.emit(str(e), None)


class RecoveryDialog(QDialog):
    """에러 복구 제안을 사용자에게 제시하고 적용 여부를 묻는다 (v0.1 §29)."""

    APPLY = 1
    DISCARD = 0

    def __init__(self, error: str, suggestion, parent=None):
        super().__init__(parent)
        self.setWindowTitle("생성 실패 - 복구 제안")
        self.setMinimumWidth(420)
        self.suggestion = suggestion

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>오류:</b> {error}"))
        layout.addWidget(QLabel(
            "<br>".join(f"{k}: {v}" for k, v in (suggestion.changes or {}).items())
        ))
        if suggestion.estimated_vram_save:
            layout.addWidget(QLabel(f"예상 VRAM 절약: {suggestion.estimated_vram_save:.1f} GB"))

        layout.addWidget(QLabel("제언된 설정을 적용한 뒤 다시 생성하시겠습니까?"))
        buttons = QHBoxLayout()
        self.apply_btn = QPushButton("설정 적용")
        self.discard_btn = QPushButton("그대로 닫기")
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(self.discard_btn)
        layout.addLayout(buttons)
        self.apply_btn.clicked.connect(lambda: self.done(self.APPLY))
        self.discard_btn.clicked.connect(lambda: self.done(self.DISCARD))


class ModelInfoPanel(QGroupBox):
    """선택된 이미지 모델의 상세 정보 표시 (v0.1 §26).

    Model / Architecture / Prompt Style / Negative Prompt /
    Estimated VRAM / Available VRAM / Device / Status 를 표시한다.
    """

    def __init__(self, engine, parent=None):
        super().__init__("Model Information", parent)
        self.engine = engine
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QGridLayout(self); layout.setHorizontalSpacing(10); layout.setVerticalSpacing(1)
        self.model_label = QLabel("-")
        self.arch_label = QLabel("-")
        self.style_label = QLabel("-")
        self.negative_label = QLabel("-")
        self.est_vram_label = QLabel("-")
        self.avail_vram_label = QLabel("-")
        self.budget_label = QLabel(self.engine.vram_budget.describe())
        self.ram_label = QLabel("-")
        self.strategy_label = QLabel("-")
        self.device_label = QLabel("-")
        self.status_label = QLabel("-")
        self.device_label.setVisible(False)  # 상단 요약줄에 표시됨

        def _cell(caption: str, label: QLabel, row: int, col: int) -> None:
            cap = QLabel(caption)
            cap.setStyleSheet("color:#a0a0a0; font-size:11px;")
            label.setStyleSheet("font-size:12px;")
            layout.addWidget(cap, row * 2, col)
            layout.addWidget(label, row * 2 + 1, col)

        _cell("Model", self.model_label, 0, 0)
        _cell("Arch", self.arch_label, 0, 1)
        _cell("Style", self.style_label, 1, 0)
        _cell("Negative", self.negative_label, 1, 1)
        _cell("Est. VRAM", self.est_vram_label, 2, 0)
        _cell("Avail. VRAM", self.avail_vram_label, 2, 1)
        _cell("RAM", self.ram_label, 3, 0)
        _cell("Budget", self.budget_label, 3, 1)
        _cell("Strategy", self.strategy_label, 4, 0)
        layout.addWidget(self.status_label, 9, 0, 1, 2)

    def refresh(self, model_path: str | None = None) -> None:
        """모델 정보를 갱신한다. model_path가 없으면 현재 메모리만 갱신한다."""
        snap = self.engine.memory.take_snapshot("model_info")

        # 시스템 RAM (실측)
        if snap.ram_free_gb is not None and snap.ram_total_gb is not None:
            self.ram_label.setText(
                f"{snap.ram_free_gb:.1f} GB 사용 가능 / {snap.ram_total_gb:.1f} GB"
            )
        else:
            self.ram_label.setText("N/A")

        if model_path is None:
            self.avail_vram_label.setText(self._vram_text(snap))
            return

        path = Path(model_path)
        profile = self.engine.registry.profile_for(path)
        supported = self.engine.image.can_handle(profile.architecture)

        # 메모리 전략 미리보기
        strategy = self.engine.image.plan_strategy(profile.architecture)
        self.strategy_label.setText(strategy.describe())
        self.strategy_label.setStyleSheet(
            "color:#6bcf7f;" if strategy.tier.value == "full" else "color:#ffd93d;"
        )

        self.model_label.setText(path.name)
        self.arch_label.setText(profile.architecture)
        self.style_label.setText(profile.prompt_style)
        self.negative_label.setText(
            "Supported" if profile.use_negative else "Not supported"
        )
        estimated = profile.estimated_vram or self.engine.image.estimate_memory(
            profile.architecture
        )
        self.est_vram_label.setText(f"{estimated:.1f} GB" if estimated else "-")
        self.avail_vram_label.setText(self._vram_text(snap))
        budget = self.engine.vram_budget
        self.budget_label.setText(budget.describe())
        self.device_label.setText(f"{self.engine.hardware.backend} ({self.engine.hardware.name})")

        if not supported:
            self.status_label.setText("⚠ Unsupported architecture")
            return

        if strategy.tier.value == "impossible":
            self.status_label.setText("❌ 메모리 부족 — 더 작은 모델 필요")
        elif strategy.tier.value == "full":
            if snap.vram_free_gb is not None and estimated and estimated + 0.5 > snap.vram_free_gb:
                self.status_label.setText("⚠ VRAM 부족 — 설정 하향 권장")
            else:
                self.status_label.setText("✅ Ready")
        else:
            self.status_label.setText(f"✅ Ready ({strategy.speed_hint})")

    def _vram_text(self, snap) -> str:
        if snap.vram_free_gb is None or snap.vram_total_gb is None:
            return "N/A (CPU mode)"
        return f"{snap.vram_free_gb:.1f} GB / {snap.vram_total_gb:.1f} GB"


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("그려줘 v0.1 — Geuryeojwo")
        self._fit_to_screen()
        self.setMinimumSize(900, 520)
        self.engine=GeurimGyeolEngine(ROOT); self.engine.initialize(); self.worker=None
        self.theme_manager=ThemeManager(QApplication.instance(), ROOT / "config" / "theme_config.json"); self.theme_manager.apply_theme()
        self.build_ui(); self.refresh_models()

    def _fit_to_screen(self):
        """창이 화면보다 크지 않도록 초기 크기를 정한다."""
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1180, 800)
            return
        available = screen.availableGeometry()
        width = min(1280, int(available.width() * 0.92))
        height = min(860, int(available.height() * 0.90))
        self.resize(max(900, width), max(520, height))

    def build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(8,6,8,6); root.setSpacing(6)

        # 상단: 제목 + 상태 요약 + 버튼을 한 줄로 압축
        top=QHBoxLayout(); top.setSpacing(10)
        title=QLabel("그려줘 v0.1"); title.setStyleSheet("font-size:18px;font-weight:700")
        top.addWidget(title)
        top.addWidget(QLabel("Local AI Image Studio · Powered by Geurim-gyeol"))
        top.addStretch()

        vram=self.engine.hardware.vram_gb
        hw_summary=(f"{self.engine.hardware.backend} · {self.engine.hardware.name} · "
                    f"float16" if self.engine.hardware.dtype=="float16" else
                    f"{self.engine.hardware.backend} · {self.engine.hardware.name} · float32")
        if vram: hw_summary += f" · VRAM {vram:.1f}GB"
        hw_label=QLabel(hw_summary); hw_label.setStyleSheet("color:#a0a0a0;")
        top.addWidget(hw_label)

        self.dry_run_btn=QPushButton("환경 검사"); self.dry_run_btn.clicked.connect(self._run_dry_run)
        self.theme_toggle=QPushButton("테마"); self.theme_toggle.clicked.connect(self._toggle_theme)
        top.addWidget(self.dry_run_btn); top.addWidget(self.theme_toggle)
        root.addLayout(top)

        # VRAM 한도: 같은 줄에 인라인으로 배치
        root.addLayout(self._build_vram_row())

        # 하드웨어 경고가 있을 때만 표시 (평소에는 공간 안 차지 않음)
        hw_warning=self.engine.hardware.warning
        if hw_warning:
            warn=QLabel("⚠ " + hw_warning.replace("\n"," "))
            warn.setWordWrap(True); warn.setStyleSheet("color:#ffd93d; font-size:12px;")
            root.addWidget(warn)
            self.log_warning=hw_warning

        # 모델 수를 상태바로 이동 (별도 GroupBox 제거)
        self.llm_count=QLabel(""); self.image_count=QLabel("")

        tabs=QTabWidget(); root.addWidget(tabs, 1)
        tabs.addTab(self._build_preview_tab(), "Prompt Preview")
        tabs.addTab(self._build_generate_tab(), "Generate")
        tabs.addTab(self._build_output_tab(), "Output Browser")
        tabs.addTab(self._build_session_tab(), "Session History")

        status_bar=QHBoxLayout()
        self.status_ram=QLabel("RAM: -"); status_bar.addWidget(self.status_ram)
        self.status_vram=QLabel("VRAM: -"); status_bar.addWidget(self.status_vram)
        self.status_cpu=QLabel("CPU: -"); status_bar.addWidget(self.status_cpu)
        self.status_gpu=QLabel("GPU: -"); status_bar.addWidget(self.status_gpu)
        self.status_strategy=QLabel("메모리: -"); self.status_strategy.setStyleSheet("color:#7fb3ff;")
        status_bar.addWidget(self.status_strategy)
        status_bar.addStretch()
        self.status_msg=QLabel("준비됨"); status_bar.addWidget(self.status_msg)
        root.addLayout(status_bar)
        self._mem_timer=QTimer(); self._mem_timer.timeout.connect(self._update_status_bar); self._mem_timer.start(1000)

    def _build_vram_row(self) -> QHBoxLayout:
        """VRAM 한도 설정을 한 줄로 배치한다 (v0.1 §8.4)."""
        row=QHBoxLayout(); row.setSpacing(6)
        label=QLabel("VRAM 한도:"); label.setStyleSheet("font-weight:bold;")
        row.addWidget(label)

        self.vram_mode=QComboBox()
        self.vram_mode.addItem("기본값 (8 GB, 보수적)", "default")
        self.vram_mode.addItem("자동 감지 (내 GPU)", "auto")
        self.vram_mode.addItem("사용자 지정", "custom")
        self.vram_mode.addItem("제한 없음", "unlimited")

        current=self.engine.vram_budget.mode
        self.vram_mode.setCurrentIndex(max(0, self.vram_mode.findData(current)))

        self.vram_value=QDoubleSpinBox()
        self.vram_value.setRange(1.0, 128.0); self.vram_value.setSingleStep(0.5)
        self.vram_value.setValue(self.engine.vram_budget.custom_gb or 8.0)
        self.vram_value.setSuffix(" GB")
        self.vram_value.setFixedWidth(80)
        self.vram_value.setEnabled(current == "custom")

        self.vram_info=QLabel(self.engine.vram_budget.describe())
        self.vram_info.setStyleSheet("color:#a0a0a0; font-size:12px;")

        row.addWidget(self.vram_mode)
        row.addWidget(self.vram_value)
        row.addWidget(self.vram_info, 1)

        self.vram_mode.currentIndexChanged.connect(self._on_vram_mode_changed)
        self.vram_value.valueChanged.connect(self._apply_vram_limit)
        return row

    def _on_vram_mode_changed(self) -> None:
        """모드 변경 시 custom 입력란을 활성화한다."""
        self.vram_value.setEnabled(self.vram_mode.currentData() == "custom")
        self._apply_vram_limit()

    def _apply_vram_limit(self) -> None:
        """VRAM 한도 설정을 저장한다 (v0.1 §3.4)."""
        mode = self.vram_mode.currentData()
        budget = self.engine.set_vram_limit(mode, self.vram_value.value())
        self.vram_info.setText(budget.describe())
        if hasattr(self, 'model_info'):
            self.model_info.refresh(self.image.currentData())

    def _build_preview_tab(self) -> QWidget:
        """Prompt Preview 탭 (v0.1 §25)."""
        self.prompt_preview = PromptPreviewWidget(self.engine.prompt)
        self.prompt_preview.set_model("sdxl")
        self.prompt_preview.generate_requested.connect(self._on_preview_generate)
        return self.prompt_preview

    def _build_generate_tab(self) -> QWidget:
        """Generation 탭 (기존 UI 유지)."""
        tab=QWidget(); layout=QVBoxLayout(tab)
        body=QHBoxLayout(); layout.addLayout(body)
        left=QVBoxLayout(); body.addLayout(left,1); right=QVBoxLayout(); body.addLayout(right,1)
        models=QGroupBox("Models"); form=QHBoxLayout(models); form.setSpacing(4)
        self.llm=QComboBox(); self.image=QComboBox()
        form.addWidget(QLabel("LLM")); form.addWidget(self.llm, 1)
        form.addWidget(QLabel("Image")); form.addWidget(self.image, 1)
        left.addWidget(models)
        self.model_info=ModelInfoPanel(self.engine); left.addWidget(self.model_info)
        self.image.currentIndexChanged.connect(lambda _: self.model_info.refresh(self.image.currentData()))
        promptbox=QGroupBox("Prompt"); pl=QVBoxLayout(promptbox); self.prompt=QTextEdit(); self.prompt.setPlaceholderText("무엇을 그리고 싶나요?"); self.prompt.setMinimumHeight(90); pl.addWidget(self.prompt); left.addWidget(promptbox)
        params=QGroupBox("Generation"); pf=QHBoxLayout(params); pf.setSpacing(4)
        self.w=QSpinBox(); self.w.setRange(64,4096); self.w.setValue(1024); self.w.setSingleStep(64)
        self.h=QSpinBox(); self.h.setRange(64,4096); self.h.setValue(1024); self.h.setSingleStep(64)
        self.steps=QSpinBox(); self.steps.setRange(1,100); self.steps.setValue(20)
        self.cfg=QDoubleSpinBox(); self.cfg.setRange(0,30); self.cfg.setValue(7); self.cfg.setSingleStep(.1)
        self.seed=QSpinBox(); self.seed.setRange(-1,2147483647); self.seed.setValue(-1)

        def _field(caption, widget):
            """라벨 위 입력칸 세로 배치."""
            box=QVBoxLayout(); box.setSpacing(1)
            lbl=QLabel(caption); lbl.setStyleSheet("color:#a0a0a0; font-size:11px;")
            box.addWidget(lbl); box.addWidget(widget); return box

        for cap, wdg in (("W",self.w),("H",self.h),("Steps",self.steps),("CFG",self.cfg),("Seed",self.seed)):
            pf.addLayout(_field(cap,wdg))
        left.addWidget(params)
        self.neg=QTextEdit(); self.neg.setPlaceholderText("Negative prompt (선택)"); self.neg.setFixedHeight(46)
        left.addWidget(self.neg)
        buttons=QHBoxLayout(); self.generate=QPushButton("그려줘"); self.cancel=QPushButton("중지"); self.refresh=QPushButton("모델 새로고침"); buttons.addWidget(self.generate); buttons.addWidget(self.cancel); buttons.addWidget(self.refresh); left.addLayout(buttons)
        self.progress=QProgressBar(); left.addWidget(self.progress); self.status=QLabel("준비됨"); left.addWidget(self.status)
        self.log=QTextEdit(); self.log.setReadOnly(True)
        right.addWidget(QLabel("Result")); self.preview=QLabel("생성된 이미지가 여기에 표시됩니다."); self.preview.setAlignment(Qt.AlignCenter); self.preview.setStyleSheet("border:1px solid #444"); self.preview.setMinimumHeight(160); self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored); right.addWidget(self.preview,1); right.addWidget(QLabel("Engine Log")); self.log.setMaximumHeight(140); right.addWidget(self.log)
        self.generate.clicked.connect(self.start); self.cancel.clicked.connect(self.stop); self.refresh.clicked.connect(self.refresh_models)
        return tab

    def _build_output_tab(self) -> QWidget:
        """Output Browser 탭."""
        self.output_browser=OutputBrowser(ROOT / "outputs")
        self.output_browser.regenerate_requested.connect(self._on_regenerate_from_output)
        return self.output_browser

    def _build_session_tab(self) -> QWidget:
        """Session History 탭."""
        self.session_browser=SessionHistoryBrowser(ROOT / "sessions")
        self.session_browser.regenerate_requested.connect(self._on_regenerate_from_session)
        return self.session_browser

    def _toggle_theme(self) -> None:
        """다크/라이트 테마 토글 (§24)."""
        theme = self.theme_manager.toggle_theme()
        self.log.append(f"Theme switched to: {theme}")

    def _run_dry_run(self) -> None:
        """Dry Run Mode 실행 (§27)."""
        from app.engine.validation.dry_run import DryRunResult
        image_path = Path(self.image.currentData()) if self.image.currentData() else None
        llm_path = Path(self.llm.currentData()) if self.llm.currentData() else None
        if not image_path or not image_path.exists():
            QMessageBox.warning(self, "모델 필요", "이미지 모델을 먼저 선택해주세요.")
            return
        try:
            result: DryRunResult = self.engine.dry_runner.run(
                image_path, llm_path,
                self.w.value(), self.h.value(),
                self.steps.value(), self.cfg.value(), self.seed.value(),
            )
            msg = f"준비 상태: {'✅ 준비 완료' if result.ready else '❌ 준비 안됨'}\n\n"
            if result.warnings:
                msg += "경고:\n" + "\n".join(result.warnings) + "\n\n"
            if result.errors:
                msg += "오류:\n" + "\n".join(result.errors) + "\n\n"
            msg += f"VRAM 예산: {result.vram_budget}\n" if result.vram_budget else ""
            if result.memory_strategy:
                msg += f"메모리 전략: {result.memory_strategy}\n"
            if result.suggested_resolution:
                msg += f"적용 해상도: {result.suggested_resolution}\n"
            msg += f"VRAM: {result.available_vram_gb}GB 사용 가능 / {result.total_vram_gb}GB 전체\n"
            if result.available_ram_gb is not None:
                msg += f"RAM: {result.available_ram_gb}GB 사용 가능 / {result.total_ram_gb}GB 전체\n"
            msg += f"예상 이미지 메모리: {result.estimated_image_memory_gb}GB"
            QMessageBox.information(self, "환경 검사 결과", msg)
        except Exception as e:
            QMessageBox.critical(self, "Dry Run 오류", str(e))

    def _update_status_bar(self) -> None:
        """하단 상태창: RAM/VRAM/CPU/GPU 사용률 실시간 업데이트 (§26)."""
        try:
            import psutil
            ram = psutil.virtual_memory()
            self.status_ram.setText(f"RAM: {ram.used/1024**3:.1f}/{ram.total/1024**3:.1f}GB ({ram.percent}%)")
            self.status_cpu.setText(f"CPU: {psutil.cpu_percent(interval=0.1):.1f}%")
        except Exception:
            pass
        try:
            snap = self.engine.memory.take_snapshot("status_bar")
            if snap.vram_free_gb is not None and snap.vram_total_gb is not None:
                used = (snap.vram_total_gb - snap.vram_free_gb)
                pct = (used / snap.vram_total_gb * 100) if snap.vram_total_gb > 0 else 0
                self.status_vram.setText(f"VRAM: {used:.1f}/{snap.vram_total_gb:.1f}GB ({pct:.0f}%)")
            else:
                self.status_vram.setText("VRAM: 없음 (CPU 모드)")
            if snap.vram_allocated_gb is not None:
                self.status_gpu.setText(f"GPU alloc: {snap.vram_allocated_gb:.1f}GB")
            self.model_info.avail_vram_label.setText(
                self.model_info._vram_text(snap)
            )
        except Exception:
            pass

    def _on_regenerate_from_output(self, prompt: str, params: dict) -> None:
        """Output Browser에서 재생성 요청."""
        self.prompt.setPlainText(prompt)
        if "width" in params: self.w.setValue(params["width"])
        if "height" in params: self.h.setValue(params["height"])
        if "steps" in params: self.steps.setValue(params["steps"])
        if "cfg" in params: self.cfg.setValue(params["cfg"])
        self.status.setText("재생성할 파라미터가 설정되었습니다. Generate 버튼을 클릭하세요.")

    def _on_regenerate_from_session(self, prompt: str, params: dict, image_model: Path) -> None:
        """Session History에서 재생성 요청."""
        self.prompt.setPlainText(prompt)
        if "width" in params: self.w.setValue(params["width"])
        if "height" in params: self.h.setValue(params["height"])
        if "steps" in params: self.steps.setValue(params["steps"])
        if "cfg" in params: self.cfg.setValue(params["cfg"])
        for i in range(self.image.count()):
            if self.image.itemData(i) == str(image_model):
                self.image.setCurrentIndex(i)
                break
        self.status.setText("세션에서 재생성할 파라미터가 설정되었습니다. Generate 버튼을 클릭하세요.")

    def _on_preview_generate(self, enhanced: str, negative: str, original: str) -> None:
        """Prompt Preview에서 Generate 요청."""
        if self.worker and self.worker.isRunning(): return
        if self.image.currentData() is None:
            QMessageBox.warning(self,"모델 필요","models 폴더에 모델을 하나 폴더째 넣어주세요."); return
        self.progress.setValue(0); self.generate.setEnabled(False)
        llm_data = self.llm.currentData()
        req=GenerationRequest(original, Path(llm_data) if llm_data else None, Path(self.image.currentData()), negative, self.w.value(), self.h.value(), self.steps.value(), self.cfg.value(), self.seed.value())
        req.prompt = enhanced
        self.worker=Worker(self.engine.generation, req); self.worker.progress.connect(lambda v,m:(self.progress.setValue(v),self.status.setText(m),self.log.append(m))); self.worker.done.connect(self.done); self.worker.failed.connect(self.fail); self.worker.start()

    def refresh_models(self):
        """models/ 폴더를 스캔해 드롭다운을 채운다 (v0.1 §9)."""
        self.llm.clear(); self.image.clear()
        llms, images = self.engine.scan_models()
        for bundle in llms:
            if bundle.load_target:
                self.llm.addItem(f"{bundle.name} (LLM)", str(bundle.load_target))
        self.llm.addItem("사용 안 함 (fallback)", None)
        for bundle in images:
            if bundle.load_target:
                self.image.addItem(bundle.describe(), str(bundle.load_target))
        self.status.setText(f"LLM {len(llms)}개 / 이미지 모델 {len(images)}개 발견")
        self.llm_count.setText(f"LLM: {len(llms)} found")
        self.image_count.setText(f"Image: {len(images)} found")
        if images:
            # 프로필로 아키텍처를 정확히 조회 (파일명 추정이 아님)
            target = images[0].load_target
            if target:
                arch = self.engine.registry.profile_for(target).architecture
                self.prompt_preview.set_model(
                    arch, self.llm.currentData() if self.llm.currentData() else None
                )
        self.model_info.refresh(self.image.currentData())

    def start(self):
        if self.worker and self.worker.isRunning(): return
        if self.image.currentData() is None:
            QMessageBox.warning(self,"모델 필요","models 폴더에 모델을 하나 폴더째 넣어주세요."); return
        prompt=self.prompt.toPlainText().strip()
        if not prompt: QMessageBox.warning(self,"입력 필요","프롬프트를 입력해주세요."); return
        self.progress.setValue(0); self.generate.setEnabled(False)
        req=GenerationRequest(prompt, Path(self.llm.currentData()) if self.llm.currentData() else None, Path(self.image.currentData()), self.neg.toPlainText(), self.w.value(), self.h.value(), self.steps.value(), self.cfg.value(), self.seed.value())
        self.worker=Worker(self.engine.generation, req); self.worker.progress.connect(lambda v,m:(self.progress.setValue(v),self.status.setText(m),self.log.append(m))); self.worker.done.connect(self.done); self.worker.failed.connect(self.fail); self.worker.start()

    def stop(self): self.engine.generation.cancel(); self.status.setText("중지 요청됨")
    def done(self,path,meta):
        self.generate.setEnabled(True)
        pixmap=QPixmap(path)
        if not pixmap.isNull():
            self.preview.setPixmap(pixmap.scaled(
                self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.status.setText(f"완료: {Path(path).name}")
        self.log.append(f"저장: {path}\nPrompt: {meta['prompt']}")
        if hasattr(self, 'output_browser'): self.output_browser._refresh_list()
        if hasattr(self, 'session_browser'): self.session_browser._refresh_list()

    def fail(self,msg,suggestion=None):
        """실패 처리 — 복구 제안이 있으면 제시한다 (v0.1 §29)."""
        self.generate.setEnabled(True); self.status.setText("실패"); self.log.append("ERROR: "+msg)
        if suggestion is None:
            QMessageBox.critical(self,"생성 실패",msg); return
        dialog = RecoveryDialog(msg, suggestion, self)
        dialog.exec()
        if dialog.result() != RecoveryDialog.APPLY:
            QMessageBox.warning(self,"생성 실패",msg); return
        changes = suggestion.changes or {}
        if "width" in changes: self.w.setValue(changes["width"])
        if "height" in changes: self.h.setValue(changes["height"])
        if "steps" in changes: self.steps.setValue(changes["steps"])
        if "cfg" in changes: self.cfg.setValue(changes["cfg"])
        self.status.setText("안전한 설정이 적용되었습니다. '그려줘'를 다시 눌러주세요.")
        self.log.append(f"복구 설정 적용: {changes}")

    def closeEvent(self, event):
        self._mem_timer.stop()
        self.engine.shutdown()
        super().closeEvent(event)


def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    app=QApplication(sys.argv); win=MainWindow(); win.show(); return app.exec()
