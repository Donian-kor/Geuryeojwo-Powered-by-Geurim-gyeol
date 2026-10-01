from __future__ import annotations
import sys, logging
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QProgressBar,
    QMessageBox, QFormLayout, QGroupBox, QTabWidget,
)
from app.engine import GeurimGyeolEngine
from app.engine.generation.controller import GenerationRequest, GenerationResult
from app.gui.output_browser import OutputBrowser
from app.gui.session_browser import SessionHistoryBrowser
from app.gui.prompt_preview import PromptPreviewWidget
from app.gui.theme.manager import ThemeManager

ROOT = Path(__file__).resolve().parents[2]


class Worker(QThread):
    progress = Signal(int, str); done = Signal(str, dict); failed = Signal(str)
    def __init__(self, controller, req): super().__init__(); self.controller=controller; self.req=req
    def run(self):
        try:
            result: GenerationResult = self.controller.run(self.req, lambda v,m: self.progress.emit(v,m))
            self.done.emit(str(result.image_path), result.metadata)
        except Exception as e: self.failed.emit(str(e))


class MainWindow(QWidget):
    def __init__(self):
        super().__init__(); self.setWindowTitle("그려줘 v0.1 — Geuryeojwo"); self.resize(1180, 820)
        self.engine=GeurimGyeolEngine(ROOT); self.engine.initialize(); self.worker=None
        self.theme_manager=ThemeManager(QApplication.instance(), ROOT / "config" / "theme_config.json"); self.theme_manager.apply_theme()
        self.build_ui(); self.refresh_models()

    def build_ui(self):
        root=QVBoxLayout(self)
        title=QLabel("그려줘 v0.1"); title.setStyleSheet("font-size:28px;font-weight:700"); root.addWidget(title)
        sub=QLabel("Local AI Image Studio  ·  Powered by Geurim-gyeol"); root.addWidget(sub)
        
        hw_box=QGroupBox("System Information"); hw_layout=QFormLayout(hw_box)
        self.hw_label=QLabel(f"Backend: {self.engine.hardware.backend}"); hw_layout.addRow("Backend:",self.hw_label)
        self.hw_name=QLabel(f"Device: {self.engine.hardware.name}"); hw_layout.addRow("Device:",self.hw_name)
        self.hw_dtype=QLabel(f"Precision: {self.engine.hardware.dtype}"); hw_layout.addRow("Precision:",self.hw_dtype)
        self.hw_vram=QLabel(f"VRAM: {f'{self.engine.hardware.vram_gb:.1f} GB' if self.engine.hardware.vram_gb else 'N/A'}"); hw_layout.addRow("VRAM:",self.hw_vram)
        self.llm_count=QLabel(f"LLM: {len(self.engine.registry.scan_llm())} found"); hw_layout.addRow("Models:",self.llm_count)
        self.image_count=QLabel(f"Image: {len(self.engine.registry.scan_image())} found"); hw_layout.addRow("",self.image_count)
        root.addWidget(hw_box)
        
        btns=QHBoxLayout()
        self.theme_toggle=QPushButton("다크/라이트 전환"); self.theme_toggle.clicked.connect(self._toggle_theme)
        self.dry_run_btn=QPushButton("환경 검사 (Dry Run)"); self.dry_run_btn.clicked.connect(self._run_dry_run)
        btns.addWidget(self.theme_toggle); btns.addWidget(self.dry_run_btn); btns.addStretch()
        root.addLayout(btns)

        tabs=QTabWidget(); root.addWidget(tabs)
        tabs.addTab(self._build_preview_tab(), "Prompt Preview")
        tabs.addTab(self._build_generate_tab(), "Generate")
        tabs.addTab(self._build_output_tab(), "Output Browser")
        tabs.addTab(self._build_session_tab(), "Session History")

        status_bar=QHBoxLayout()
        self.status_ram=QLabel("RAM: -"); status_bar.addWidget(self.status_ram)
        self.status_vram=QLabel("VRAM: -"); status_bar.addWidget(self.status_vram)
        self.status_cpu=QLabel("CPU: -"); status_bar.addWidget(self.status_cpu)
        self.status_gpu=QLabel("GPU: -"); status_bar.addWidget(self.status_gpu)
        status_bar.addStretch()
        self.status_msg=QLabel("준비됨"); status_bar.addWidget(self.status_msg)
        root.addLayout(status_bar)
        self._mem_timer=QTimer(); self._mem_timer.timeout.connect(self._update_status_bar); self._mem_timer.start(1000)

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
        models=QGroupBox("Models"); form=QFormLayout(models)
        self.llm=QComboBox(); self.image=QComboBox(); form.addRow("Local LLM (GGUF)",self.llm); form.addRow("Image Model",self.image); left.addWidget(models)
        promptbox=QGroupBox("Prompt"); pl=QVBoxLayout(promptbox); self.prompt=QTextEdit(); self.prompt.setPlaceholderText("무엇을 그리고 싶나요?"); self.prompt.setMinimumHeight(150); pl.addWidget(self.prompt); left.addWidget(promptbox)
        params=QGroupBox("Generation"); pf=QFormLayout(params)
        self.w=QSpinBox(); self.w.setRange(64,4096); self.w.setValue(1024); self.w.setSingleStep(64)
        self.h=QSpinBox(); self.h.setRange(64,4096); self.h.setValue(1024); self.h.setSingleStep(64)
        self.steps=QSpinBox(); self.steps.setRange(1,100); self.steps.setValue(20)
        self.cfg=QDoubleSpinBox(); self.cfg.setRange(0,30); self.cfg.setValue(7); self.cfg.setSingleStep(.1)
        self.seed=QSpinBox(); self.seed.setRange(-1,2147483647); self.seed.setValue(-1)
        self.neg=QTextEdit(); self.neg.setMaximumHeight(70)
        pf.addRow("Width",self.w); pf.addRow("Height",self.h); pf.addRow("Steps",self.steps); pf.addRow("CFG",self.cfg); pf.addRow("Seed",self.seed); pf.addRow("Negative (optional)",self.neg); left.addWidget(params)
        buttons=QHBoxLayout(); self.generate=QPushButton("그려줘"); self.cancel=QPushButton("중지"); self.refresh=QPushButton("모델 새로고침"); buttons.addWidget(self.generate); buttons.addWidget(self.cancel); buttons.addWidget(self.refresh); left.addLayout(buttons)
        self.progress=QProgressBar(); left.addWidget(self.progress); self.status=QLabel("준비됨"); left.addWidget(self.status)
        self.log=QTextEdit(); self.log.setReadOnly(True)
        right.addWidget(QLabel("Result")); self.preview=QLabel("생성된 이미지가 여기에 표시됩니다."); self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumSize(500,500); self.preview.setStyleSheet("border:1px solid #444"); right.addWidget(self.preview,1); right.addWidget(QLabel("Engine Log")); right.addWidget(self.log,1)
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
            msg += f"VRAM: {result.available_vram_gb}GB available / {result.total_vram_gb}GB total\n"
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
            if snap.vram_allocated_gb is not None:
                self.status_gpu.setText(f"GPU alloc: {snap.vram_allocated_gb:.1f}GB")
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
            QMessageBox.warning(self,"모델 필요","models/checkpoints에 이미지 모델을 넣어주세요."); return
        self.progress.setValue(0); self.generate.setEnabled(False)
        llm_data = self.llm.currentData()
        req=GenerationRequest(original, Path(llm_data) if llm_data else None, Path(self.image.currentData()), negative, self.w.value(), self.h.value(), self.steps.value(), self.cfg.value(), self.seed.value())
        req.prompt = enhanced
        self.worker=Worker(self.engine.generation, req); self.worker.progress.connect(lambda v,m:(self.progress.setValue(v),self.status.setText(m),self.log.append(m))); self.worker.done.connect(self.done); self.worker.failed.connect(self.fail); self.worker.start()

    def refresh_models(self):
        self.llm.clear(); self.image.clear(); llms, images=self.engine.scan_models()
        for p in llms: self.llm.addItem(p.name, str(p))
        self.llm.addItem("사용 안 함 (fallback)", None)
        for p in images: self.image.addItem(p.name, str(p))
        self.status.setText(f"LLM {len(llms)}개 / 이미지 모델 {len(images)}개 발견")
        self.llm_count.setText(f"LLM: {len(llms)} found")
        self.image_count.setText(f"Image: {len(images)} found")
        if images:
            arch = "sdxl" if "sdxl" in images[0].name.lower() else ("flux" if "flux" in images[0].name.lower() else "sd15")
            self.prompt_preview.set_model(arch, self.llm.currentData() if self.llm.currentData() else None)

    def start(self):
        if self.worker and self.worker.isRunning(): return
        if self.image.currentData() is None:
            QMessageBox.warning(self,"모델 필요","models/checkpoints에 이미지 모델을 넣어주세요."); return
        prompt=self.prompt.toPlainText().strip()
        if not prompt: QMessageBox.warning(self,"입력 필요","프롬프트를 입력해주세요."); return
        self.progress.setValue(0); self.generate.setEnabled(False)
        req=GenerationRequest(prompt, Path(self.llm.currentData()) if self.llm.currentData() else None, Path(self.image.currentData()), self.neg.toPlainText(), self.w.value(), self.h.value(), self.steps.value(), self.cfg.value(), self.seed.value())
        self.worker=Worker(self.engine.generation, req); self.worker.progress.connect(lambda v,m:(self.progress.setValue(v),self.status.setText(m),self.log.append(m))); self.worker.done.connect(self.done); self.worker.failed.connect(self.fail); self.worker.start()

    def stop(self): self.engine.generation.cancel(); self.status.setText("중지 요청됨")
    def done(self,path,meta):
        self.generate.setEnabled(True); self.preview.setPixmap(QPixmap(path).scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)); self.status.setText(f"완료: {path}"); self.log.append(f"저장: {path}\nPrompt: {meta['prompt']}")
        if hasattr(self, 'output_browser'): self.output_browser._refresh_list()
        if hasattr(self, 'session_browser'): self.session_browser._refresh_list()

    def fail(self,msg): self.generate.setEnabled(True); self.status.setText("실패"); self.log.append("ERROR: "+msg); QMessageBox.critical(self,"생성 실패",msg)

    def closeEvent(self, event):
        self._mem_timer.stop()
        self.engine.shutdown()
        super().closeEvent(event)


def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    app=QApplication(sys.argv); win=MainWindow(); win.show(); return app.exec()
