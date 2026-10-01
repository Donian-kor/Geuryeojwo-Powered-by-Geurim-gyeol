from __future__ import annotations
import sys, logging, time
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QProgressBar, QFileDialog, QMessageBox, QFormLayout, QGroupBox
from app.engine import GeurimGyeolEngine
from app.engine.generation.controller import GenerationRequest, GenerationResult

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
        self.build_ui(); self.refresh_models()

    def build_ui(self):
        root=QVBoxLayout(self); title=QLabel("그려줘 v0.1"); title.setStyleSheet("font-size:28px;font-weight:700"); root.addWidget(title)
        sub=QLabel("Local AI Image Studio  ·  Powered by Geurim-gyeol"); root.addWidget(sub)
        hw=QLabel(f"Hardware: {self.engine.hardware.backend} / {self.engine.hardware.name} / {self.engine.hardware.dtype}"); root.addWidget(hw)
        body=QHBoxLayout(); root.addLayout(body)
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
        self.neg=QTextEdit(); self.neg.setMaximumHeight(70); pf.addRow("Width",self.w); pf.addRow("Height",self.h); pf.addRow("Steps",self.steps); pf.addRow("CFG",self.cfg); pf.addRow("Seed",self.seed); pf.addRow("Negative (optional)",self.neg); left.addWidget(params)
        buttons=QHBoxLayout(); self.generate=QPushButton("그려줘"); self.cancel=QPushButton("중지"); self.refresh=QPushButton("모델 새로고침"); buttons.addWidget(self.generate); buttons.addWidget(self.cancel); buttons.addWidget(self.refresh); left.addLayout(buttons)
        self.progress=QProgressBar(); left.addWidget(self.progress); self.status=QLabel("준비됨"); left.addWidget(self.status)
        self.log=QTextEdit(); self.log.setReadOnly(True); right.addWidget(QLabel("Result")); self.preview=QLabel("생성된 이미지가 여기에 표시됩니다."); self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumSize(500,500); self.preview.setStyleSheet("border:1px solid #444"); right.addWidget(self.preview,1); right.addWidget(QLabel("Engine Log")); right.addWidget(self.log,1)
        self.generate.clicked.connect(self.start); self.cancel.clicked.connect(self.stop); self.refresh.clicked.connect(self.refresh_models)

    def refresh_models(self):
        self.llm.clear(); self.image.clear(); llms, images=self.engine.scan_models()
        for p in llms: self.llm.addItem(p.name, str(p))
        self.llm.addItem("사용 안 함 (fallback)", None)
        for p in images: self.image.addItem(p.name, str(p))
        self.status.setText(f"LLM {len(llms)}개 / 이미지 모델 {len(images)}개 발견")

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
    def fail(self,msg): self.generate.setEnabled(True); self.status.setText("실패"); self.log.append("ERROR: "+msg); QMessageBox.critical(self,"생성 실패",msg)

    def closeEvent(self, event):
        self.engine.shutdown()
        super().closeEvent(event)

def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    app=QApplication(sys.argv); win=MainWindow(); win.show(); return app.exec()
