from __future__ import annotations
import sys, logging
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QProgressBar,
    QMessageBox, QGroupBox, QTabWidget, QSizePolicy, QGridLayout,
)
from app.engine.comfy_engine import GeurimGyeolEngine
from app.gui.output_browser import OutputBrowser
from app.gui.session_browser import SessionHistoryBrowser
from app.gui.theme.manager import ThemeManager

ROOT = Path(__file__).resolve().parents[2]


class Worker(QThread):
    progress = Signal(int, str); done = Signal(str, dict); failed = Signal(str, object)
    def __init__(self, engine, req): super().__init__(); self.engine=engine; self.req=req
    def run(self):
        try:
            result = self.engine.generate(
                self.req, on_progress=lambda v,m: self.progress.emit(v,m)
            )
            if result.success:
                self.done.emit(str(result.image_path), result.metadata)
            else:
                self.failed.emit(result.error or "생성 실패", None)
        except Exception as e: self.failed.emit(str(e), None)


class ModelInfoPanel(QGroupBox):
    """선택한 워크플로와 ComfyUI 상태 요약 (v0.2 §11).

    네이티브 모델 파일이 아니라 ComfyUI 워크플로와 서버 상태를 보여준다.
    """

    def __init__(self, engine, parent=None):
        super().__init__("Workflow", parent)
        self.engine = engine
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QGridLayout(self); layout.setHorizontalSpacing(10); layout.setVerticalSpacing(1)
        self.workflow_label = QLabel("-")
        self.nodes_label = QLabel("-")
        self.params_label = QLabel("-")
        self.device_label = QLabel("-")
        self.vram_label = QLabel("-")
        self.status_label = QLabel("-")

        def _cell(caption: str, label: QLabel, row: int, col: int) -> None:
            cap = QLabel(caption)
            cap.setStyleSheet("color:#a0a0a0; font-size:11px;")
            label.setStyleSheet("font-size:12px;")
            layout.addWidget(cap, row * 2, col)
            layout.addWidget(label, row * 2 + 1, col)

        _cell("Workflow", self.workflow_label, 0, 0)
        _cell("Nodes", self.nodes_label, 0, 1)
        _cell("Parameters", self.params_label, 1, 0)
        _cell("Device", self.device_label, 1, 1)
        _cell("VRAM", self.vram_label, 2, 0)
        layout.addWidget(self.status_label, 6, 0, 1, 2)

    def refresh(self) -> None:
        """워크플로 목록과 ComfyUI 상태를 갱신한다."""
        info = self.engine.system_info
        if info.online:
            device = info.device_name or info.device_type or "CPU"
            self.device_label.setText(device)
            if info.vram_total_gb:
                self.vram_label.setText(
                    f"{info.vram_used_gb:.1f} / {info.vram_total_gb:.1f} GB "
                    f"({info.vram_percent:.0f}%)"
                )
            else:
                self.vram_label.setText("없음")
        else:
            self.device_label.setText("-")
            self.vram_label.setText("-")
            self.status_label.setText(f"⚠ ComfyUI 접속 실패 — {info.error or ''}")
            self.status_label.setStyleSheet("color:#ffd93d;")

        wf = self.engine.active_workflow
        if wf is None:
            self.workflow_label.setText("-")
            self.nodes_label.setText("-")
            self.params_label.setText("-")
            if info.online:
                self.status_label.setText("⚠ workflows/ 폴더에 워크플로가 없습니다")
                self.status_label.setStyleSheet("color:#ffd93d;")
            return

        self.workflow_label.setText(wf.name)
        self.nodes_label.setText(f"{len(wf.prompt)}개")
        self.params_label.setText(f"{len(wf.parameters)}개")
        if info.online:
            self.status_label.setText("✅ 준비 완료")
            self.status_label.setStyleSheet("color:#6bcf7f;")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("그려줘 v0.2 — Geuryeojwo")
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
        title=QLabel("그려줘 v0.2"); title.setStyleSheet("font-size:18px;font-weight:700")
        top.addWidget(title)
        top.addWidget(QLabel("Local AI Image Studio · Powered by Geurim-gyeol"))
        top.addStretch()

        # ComfyUI 상태는 refresh_models() 가 채운다 (build_ui 보다 먼저 불릴 수도 있어)
        self.comfy_label=QLabel("ComfyUI 확인 중..."); self.comfy_label.setStyleSheet("color:#7fb3ff;")
        top.addWidget(self.comfy_label)

        self.status_refresh=QPushButton("상태 새로고침"); self.status_refresh.clicked.connect(self.refresh_models)
        self.theme_toggle=QPushButton("테마"); self.theme_toggle.clicked.connect(self._toggle_theme)
        top.addWidget(self.status_refresh); top.addWidget(self.theme_toggle)
        root.addLayout(top)

        # ComfyUI 오프라인 안내 (자동 실행 켜져 있으면 다른 문구를 쓴다)
        if not self.engine.online:
            if self.engine.config.auto_launch:
                warn_text = (
                    "⚠ ComfyUI 에 접속할 수 없어 자동으로 실행을 시도했습니다. "
                    f"사유: {self.engine.system_info.error or '알 수 없음'}\n"
                    "'상태 새로고침'을 누르면 다시 시도합니다."
                )
            else:
                warn_text = (
                    "⚠ ComfyUI 서버에 접속할 수 없습니다. "
                    "ComfyUI를 실행한 뒤 '상태 새로고침'을 눌러주세요.\n"
                    "config/comfyui.json 의 auto_launch 를 켜면 자동으로 실행합니다."
                )
            warn=QLabel(warn_text)
            warn.setWordWrap(True); warn.setStyleSheet("color:#ffd93d; font-size:12px;")
            root.addWidget(warn)

        tabs=QTabWidget(); root.addWidget(tabs, 1)
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
        # 첫 표시를 즉시 채운다 (타이머는 1초 후부터 동작하므로)
        self._update_status_bar()

    def _build_generate_tab(self) -> QWidget:
        """Generate 탭 (v0.2).

        모델 파일 대신 워크플로를 고르고, 그 워크플로가 받는
        파라미터만 입력받는다.
        """
        tab=QWidget(); layout=QVBoxLayout(tab)
        body=QHBoxLayout(); layout.addLayout(body)
        left=QVBoxLayout(); body.addLayout(left,1); right=QVBoxLayout(); body.addLayout(right,1)

        models=QGroupBox("Workflow"); form=QHBoxLayout(models); form.setSpacing(4)
        self.workflow=QComboBox()
        form.addWidget(QLabel("워크플로")); form.addWidget(self.workflow, 1)
        self.reload_wf=QPushButton("불러오기"); self.reload_wf.clicked.connect(self._reload_workflows)
        form.addWidget(self.reload_wf)
        left.addWidget(models)

        self.model_info=ModelInfoPanel(self.engine); left.addWidget(self.model_info)
        self.workflow.currentIndexChanged.connect(lambda _: self._on_workflow_changed())

        promptbox=QGroupBox("Prompt"); pl=QVBoxLayout(promptbox)
        self.prompt=QTextEdit(); self.prompt.setPlaceholderText("무엇을 그리고 싶나요?")
        self.prompt.setMinimumHeight(90); pl.addWidget(self.prompt)
        left.addWidget(promptbox)

        params=QGroupBox("Generation"); pv=QVBoxLayout(params); pv.setSpacing(4)
        pf=QHBoxLayout(); pf.setSpacing(4)
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
        pv.addLayout(pf)

        # Sampler / Scheduler — ComfyUI 가 목록을 알려준다 (KSampler 기준)
        self.sampler=QComboBox(); self.sampler.setMinimumWidth(120)
        self.scheduler=QComboBox(); self.scheduler.setMinimumWidth(120)
        sampler_row=QHBoxLayout(); sampler_row.setSpacing(4)
        sampler_row.addWidget(QLabel("Sampler")); sampler_row.addWidget(self.sampler,1)
        sampler_row.addWidget(QLabel("Scheduler")); sampler_row.addWidget(self.scheduler,1)
        pv.addLayout(sampler_row)
        left.addWidget(params)

        self.neg=QTextEdit(); self.neg.setPlaceholderText("Negative prompt (선택)")
        self.neg.setFixedHeight(46)
        left.addWidget(self.neg)

        buttons=QHBoxLayout()
        self.generate=QPushButton("그려줘"); self.cancel=QPushButton("중지")
        self.refresh=QPushButton("새로고침")
        buttons.addWidget(self.generate); buttons.addWidget(self.cancel); buttons.addWidget(self.refresh)
        left.addLayout(buttons)
        self.progress=QProgressBar(); left.addWidget(self.progress)
        self.status=QLabel("준비됨"); left.addWidget(self.status)

        self.log=QTextEdit(); self.log.setReadOnly(True)
        right.addWidget(QLabel("Result"))
        self.preview=QLabel("생성된 이미지가 여기에 표시됩니다.")
        self.preview.setAlignment(Qt.AlignCenter); self.preview.setStyleSheet("border:1px solid #444")
        self.preview.setMinimumHeight(160); self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        right.addWidget(self.preview,1)
        right.addWidget(QLabel("Engine Log")); self.log.setMaximumHeight(140); right.addWidget(self.log)

        self.generate.clicked.connect(self.start)
        self.cancel.clicked.connect(self.stop)
        self.refresh.clicked.connect(self.refresh_models)
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

    def _update_status_bar(self) -> None:
        """하단 상태창: RAM/CPU/VRAM 실시간 업데이트.

        VRAM 은 네이티브가 아니라 ComfyUI 가 관리하므로, 마지막으로
        조회한 /system_stats 값을 표시한다.
        """
        try:
            import psutil
            ram = psutil.virtual_memory()
            self.status_ram.setText(
                f"RAM: {ram.used/1024**3:.1f}/{ram.total/1024**3:.1f}GB ({ram.percent}%)"
            )
            self.status_cpu.setText(f"CPU: {psutil.cpu_percent(interval=0.1):.1f}%")
        except Exception:
            pass

        info = self.engine.system_info
        if info.online and info.vram_total_gb:
            self.status_vram.setText(
                f"VRAM: {info.vram_used_gb:.1f}/{info.vram_total_gb:.1f}GB "
                f"({info.vram_percent:.0f}%)"
            )
            self.status_gpu.setText(f"GPU: {info.device_name or info.device_type}")
        else:
            self.status_vram.setText("VRAM: -")
            self.status_gpu.setText("GPU: -")

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
        # 기록된 워크플로가 있으면 선택한다 (없으면 현재 선택 유지)
        name = str(image_model)
        for i in range(self.workflow.count()):
            if self.workflow.itemData(i) == name:
                self.workflow.setCurrentIndex(i)
                break
        self.status.setText("세션에서 재생성할 파라미터가 설정되었습니다. 그려줘를 눌러주세요.")

    def refresh_models(self):
        """ComfyUI 상태와 workflows/ 목록을 갱신한다.

        ComfyUI 가 꺼져 있고 자동 실행이 켜져 있으면, 실행에 시간이
        걸리므로 먼저 버튼을 비활성화하고 대기 안내를 띄운다.
        """
        auto = self.engine.config.auto_launch
        offline = not self.engine.online

        if auto and offline:
            self.status_refresh.setEnabled(False)
            self.status.setText("ComfyUI 를 실행하는 중입니다. 잠시만 기다려주세요...")
            QApplication.processEvents()

        try:
            self.engine.refresh_status()
        finally:
            self.status_refresh.setEnabled(True)

        self.comfy_label.setText(self.engine.status_text())
        self.comfy_label.setStyleSheet(
            "color:#7fb3ff;" if self.engine.online else "color:#d9534f;"
        )
        self._reload_workflows()

    def _reload_workflows(self):
        """workflows/ 폴더를 다시 읽어 드롭다운을 채운다."""
        self.workflow.blockSignals(True)
        self.workflow.clear()
        for wf in self.engine.refresh_workflows():
            self.workflow.addItem(wf.name, wf.path.stem)
        self.workflow.blockSignals(False)
        if self.engine.active_workflow is not None:
            for i in range(self.workflow.count()):
                if self.workflow.itemData(i) == self.engine.active_workflow.path.stem:
                    self.workflow.setCurrentIndex(i)
                    break
        self._on_workflow_changed()

    def _on_workflow_changed(self):
        """워크플로 선택을 엔진에 반영하고 입력 가능 여부를 갱신한다."""
        name = self.workflow.currentData()
        if name is not None:
            self.engine.select_workflow(name)
        wf = self.engine.active_workflow
        self.model_info.refresh()
        if wf is None:
            self.generate.setEnabled(False)
            self.status.setText("워크플로가 없습니다. workflows/ 폴더에 JSON을 넣어주세요.")
            return
        self.generate.setEnabled(True)
        params = wf.parameters
        # 워크플로가 받지 않는 입력은 비활성화한다
        for key, widget in (
            ("width", self.w), ("height", self.h),
            ("steps", self.steps), ("cfg", self.cfg), ("seed", self.seed),
        ):
            widget.setEnabled(key in params)
        self.neg.setEnabled("negative" in params)
        # 워크플로 기본값을 입력칸에 반영
        defaults = wf.defaults()
        if "width" in params and isinstance(defaults.get("width"), int):
            self.w.setValue(defaults["width"])
        if "height" in params and isinstance(defaults.get("height"), int):
            self.h.setValue(defaults["height"])
        if "steps" in params and isinstance(defaults.get("steps"), int):
            self.steps.setValue(defaults["steps"])
        if "cfg" in params and isinstance(defaults.get("cfg"), (int, float)):
            self.cfg.setValue(float(defaults["cfg"]))
        self._setup_sampler(params, defaults)
        self.status.setText(
            f"{wf.name} · 파라미터 {len(params)}개 사용 가능"
        )

    def _setup_sampler(self, params: dict, defaults: dict) -> None:
        """Sampler / Scheduler 드롭다운을 워크플로에 맞춘다.

        파라미터 키 이름은 워크플로마다 다르다
        (예: "sampler" 또는 "sampler_name").
        그래서 키가 아니라 실제 ComfyUI 입력 이름(spec.input)으로 판단한다.

        ComfyUI 에서 KSampler 선택지를 받아오지만, 워크플로가 KSampler 계열
        노드를 쓰지 않으면 선택지가 없을 수 있으므로 그때는 워크플로
        기본값만으로 채운다.
        """
        # 워크플로 입력 이름 -> ParameterSpec
        by_input = {spec.input: key for key, spec in params.items()}
        sampler_key = by_input.get("sampler_name")
        scheduler_key = by_input.get("scheduler")

        if sampler_key or scheduler_key:
            options = self.engine.sampler_options()
        else:
            options = {}

        for combo, key, option_key in (
            (self.sampler, sampler_key, "sampler"),
            (self.scheduler, scheduler_key, "scheduler"),
        ):
            combo.blockSignals(True)
            combo.clear()
            enabled = key is not None
            combo.setEnabled(enabled)
            if not enabled:
                combo.addItem("(사용 안 함)")
                combo.blockSignals(False)
                continue

            current = defaults.get(key)
            items = list(options.get(option_key) or [])
            # ComfyUI 응답이 없으면 워크플로 기본값만 넣는다
            if not items:
                items = [current] if current else []
            for item in items:
                combo.addItem(item)

            if current:
                index = combo.findText(str(current))
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def start(self):
        """생성을 시작한다."""
        if self.worker and self.worker.isRunning(): return
        if self.engine.active_workflow is None:
            QMessageBox.warning(self, "워크플로 필요",
                                "workflows/ 폴더에 워크플로 JSON을 넣어주세요."); return
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "입력 필요", "프롬프트를 입력해주세요."); return
        if not self.engine.online:
            QMessageBox.warning(self, "ComfyUI 오프라인",
                                "ComfyUI 서버에 접속할 수 없습니다.\n"
                                "ComfyUI를 실행한 뒤 상태를 새로고침해주세요."); return

        self.progress.setValue(0); self.generate.setEnabled(False)
        try:
            req = self.engine.build_request(
                prompt=prompt,
                negative_prompt=self.neg.toPlainText().strip(),
                width=self.w.value(), height=self.h.value(),
                steps=self.steps.value(), cfg=self.cfg.value(),
                seed=self.seed.value(),
                extra=self._collect_extra(),
            )
        except RuntimeError as exc:
            self.generate.setEnabled(True)
            QMessageBox.warning(self, "워크플로 필요", str(exc)); return

        self.worker = Worker(self.engine, req)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self.done)
        self.worker.failed.connect(self.fail)
        self.worker.start()

    def _collect_extra(self) -> dict:
        """워크플로에 선택적 파라미터 값을 모아서 반환한다.

        키는 워크플로의 parameters 맵에 있는 이름이어야 한다
        (워크플로마다 "sampler" 또는 "sampler_name" 처럼 다를 수 있다).
        비활성화된 항목은 보내지 않는다 — 그래야 워크플로 기본값이 유지된다.
        """
        params = (self.engine.active_workflow.parameters
                  if self.engine.active_workflow else {})
        # ComfyUI 입력 이름 -> 파라미터 키
        by_input = {spec.input: key for key, spec in params.items()}

        extra: dict = {}
        if self.sampler.isEnabled():
            key = by_input.get("sampler_name")
            if key and self.sampler.currentText():
                extra[key] = self.sampler.currentText()
        if self.scheduler.isEnabled():
            key = by_input.get("scheduler")
            if key and self.scheduler.currentText():
                extra[key] = self.scheduler.currentText()
        return extra

    def _on_progress(self, percent, message):
        """진행률 콜백 (Worker 스레드에서 호출)."""
        if percent is not None:
            self.progress.setValue(percent)
        self.status.setText(message)
        self.log.append(message)

    def stop(self):
        """생성을 중지한다."""
        self.engine.cancel()
        self.status.setText("중지 요청됨")

    def done(self,path,meta):
        self.generate.setEnabled(True)
        pixmap=QPixmap(path)
        if not pixmap.isNull():
            self.preview.setPixmap(pixmap.scaled(
                self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.status.setText(f"완료: {Path(path).name}")
        self.log.append(f"저장: {path}\nPrompt: {meta.get('prompt','')}")
        if hasattr(self, 'output_browser'): self.output_browser._refresh_list()
        if hasattr(self, 'session_browser'): self.session_browser._refresh_list()

    def fail(self, msg, suggestion=None):
        """실패 처리.

        v0.2 에서는 메모리 부족 복구 제안(VRAM 하향 등)을 하지 않는다.
        VRAM 관리는 ComfyUI 가 하고, 이 프로그램은 파라미터만 넘기기
        때문이다. 오류 원인은 워크플로/노드/모델 쪽에 있으므로 로그로 남긴다.
        """
        self.generate.setEnabled(True)
        self.status.setText("실패")
        self.log.append("ERROR: " + msg)
        QMessageBox.critical(self, "생성 실패", msg)

    def closeEvent(self, event):
        self._mem_timer.stop()
        self.engine.shutdown()
        super().closeEvent(event)


def run():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    app=QApplication(sys.argv); win=MainWindow(); win.show(); return app.exec()
