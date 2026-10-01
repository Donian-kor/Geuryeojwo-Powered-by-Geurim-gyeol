from __future__ import annotations
import sys, logging, atexit
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QProgressBar,
    QMessageBox, QGroupBox, QTabWidget, QSizePolicy, QGridLayout, QSlider, QCheckBox,
)
from app.engine.comfy_engine import GeurimGyeolEngine, _is_enhancer
from app.gui.output_browser import OutputBrowser
from app.gui.session_browser import SessionHistoryBrowser
from app.gui.theme.manager import ThemeManager

ROOT = Path(__file__).resolve().parents[2]

# 파라미터 키 -> ComfyUI 입력 이름 (모델 선택 위젯 매핑용)
_MODEL_INPUT_BY_KEY = {
    "unet": "unet_name", "checkpoint": "ckpt_name", "clip": "clip_name",
    "vae": "vae_name", "lora": "lora_name",
}


def combo_of_input(params: dict, key: str) -> str:
    """파라미터 키에 대응하는 ComfyUI 입력 이름을 돌려준다."""
    return _MODEL_INPUT_BY_KEY.get(key, key)


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
            # free 값이 없으면 used 도 None 이므로 함께 확인한다.
            used = info.vram_used_gb
            if info.vram_total_gb and used is not None:
                self.vram_label.setText(
                    f"{used:.1f} / {info.vram_total_gb:.1f} GB "
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

        # 모델 선택 — ComfyUI 의 폴더별 목록에서 고른다 (v0.2 §5.3)
        self.model_boxes=QGroupBox("Models"); ml=QGridLayout(models_box:=self.model_boxes)
        ml.setHorizontalSpacing(4); ml.setVerticalSpacing(2)
        # (파라미터 키, 라벨) — 워크플로가 LoRA/확산모델을 쓸 때만 활성화된다
        self.model_combos: dict[str, QComboBox] = {}
        for row, (key, caption) in enumerate(
            (("unet", "확산 모델"), ("clip", "텍스트 인코더"),
             ("vae", "VAE"), ("lora", "LoRA"))
        ):
            combo=QComboBox(); combo.setMinimumWidth(120)
            self.model_combos[key]=combo
            ml.addWidget(QLabel(caption), row, 0)
            ml.addWidget(combo, row, 1)
        left.addWidget(self.model_boxes)

        # LoRA 강도 슬라이더 — 자주 바꾸므로 슬라이더가 편하다
        self.lora_strength=QSlider(Qt.Horizontal); self.lora_strength.setRange(0,150)
        self.lora_strength.setValue(100); self.lora_strength.setSingleStep(5)
        self.lora_strength_label=QLabel("LoRA 강도 1.00")
        self.lora_strength_label.setStyleSheet("color:#a0a0a0; font-size:11px;")
        self.lora_strength.valueChanged.connect(
            lambda v: self.lora_strength_label.setText(f"LoRA 강도 {v / 100:.2f}")
        )
        lora_row=QHBoxLayout(); lora_row.setSpacing(4)
        lora_row.addWidget(self.lora_strength_label)
        lora_row.addWidget(self.lora_strength, 1)
        lora_box=QGroupBox("LoRA"); lora_lay=QVBoxLayout(lora_box); lora_lay.setSpacing(1)
        lora_lay.addLayout(lora_row)
        left.addWidget(lora_box)
        self.lora_box=lora_box

        self.model_info=ModelInfoPanel(self.engine); left.addWidget(self.model_info)
        self.workflow.currentIndexChanged.connect(lambda _: self._on_workflow_changed())

        promptbox=QGroupBox("Prompt"); pl=QVBoxLayout(promptbox)
        self.prompt=QTextEdit(); self.prompt.setPlaceholderText("무엇을 그리고 싶나요?")
        self.prompt.setMinimumHeight(90); pl.addWidget(self.prompt)
        # 프롬프트 인핸서 — ComfyUI 안의 LLM 노드가 프롬프트를 다듬는다.
        # 느릴 수 있어 끌 수 있어야 한다.
        self.enhance=QCheckBox("프롬프트 인핸서 사용 (더 정확해지지만 느림)")
        self.enhance.setChecked(True)
        pl.addWidget(self.enhance)
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
        # vram_total_gb 이 있어도 vram_used_gb 이 None 일 수 있다( free 미제공 ).
        used = info.vram_used_gb
        if info.online and info.vram_total_gb and used is not None:
            self.status_vram.setText(
                f"VRAM: {used:.1f}/{info.vram_total_gb:.1f}GB "
                f"({info.vram_percent:.0f}%)"
            )
            self.status_gpu.setText(f"GPU: {info.device_name or info.device_type}")
        else:
            self.status_vram.setText("VRAM: -")
            self.status_gpu.setText("GPU: -")

    def _apply_regenerated(self, prompt: str, params: dict) -> None:
        """저장된 파라미터를 입력칸에 되돌린다 (Output/Session 공통)."""
        self.prompt.setPlainText(prompt)
        for key, widget, cast in (
            ("width", self.w, int), ("height", self.h, int),
            ("steps", self.steps, int), ("cfg", self.cfg, float),
        ):
            value = params.get(key)
            if isinstance(value, (int, float)):
                widget.setValue(cast(value))
        for field, combo in (
            ("sampler", self.sampler), ("scheduler", self.scheduler),
        ):
            if field in params and combo.findText(str(params[field])) >= 0:
                combo.setCurrentIndex(combo.findText(str(params[field])))
        # LoRA 강도 복원 (없으면 기본값 유지)
        value = params.get("lora_strength", params.get("strength_model"))
        if isinstance(value, (int, float)):
            self.lora_strength.setValue(int(round(float(value) * 100)))

    def _on_regenerate_from_output(self, prompt: str, params: dict) -> None:
        """Output Browser에서 재생성 요청."""
        self._apply_regenerated(prompt, params)
        self.status.setText("파라미터를 불러왔습니다. 그려줘를 눌러주세요.")

    def _on_regenerate_from_session(self, prompt: str, params: dict, image_model: str) -> None:
        """Session History에서 재생성 요청."""
        self._apply_regenerated(prompt, params)

        # 세션에는 워크플로 이름이 저장되어 있다 (v0.2 에서는 모델 경로가 아니다)
        name = str(image_model)
        index = self._find_workflow_index(name)
        if index >= 0:
            self.workflow.setCurrentIndex(index)
            self.status.setText("세션의 워크플로와 파라미터를 불러왔습니다. 그려줘를 눌러주세요.")
        else:
            self.status.setText(
                f"파라미터를 불러왔습니다. (워크플로 '{name}' 을 찾을 수 없어 "
                "현재 선택을 유지합니다.) 그려줘를 눌러주세요."
            )

    def _find_workflow_index(self, name: str) -> int:
        """이름 또는 파일명으로 워크플로 인덱스를 찾는다.

        세션에 저장되는 값은 워크플로 표시 이름이고, 드롭다운의 data 는
        파일명이므로 둘 다 확인해야 한다.
        """
        stem = name if name.endswith(".json") else f"{name}.json"
        for i in range(self.workflow.count()):
            if name in (self.workflow.itemText(i), self.workflow.itemData(i)):
                return i
            if stem == f"{self.workflow.itemData(i)}.json":
                return i
        return -1

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
        self._setup_models(params, defaults)
        self._setup_lora_strength(params, defaults)
        self._setup_enhancer(params, defaults)
        self.status.setText(
            f"{wf.name} · 파라미터 {len(params)}개 사용 가능"
        )

    def _setup_enhancer(self, params: dict, defaults: dict) -> None:
        """프롬프트 인핸서 스위치를 워크플로에 맞춘다.

        인핸서 노드가 없는 워크플로에서는 의미가 없으므로 숨긴다.
        """
        has_enhancer = any(
            _is_enhancer((node.get("class_type") or ""))
            for node in (self.engine.active_workflow.prompt or {}).values()
            if isinstance(node, dict)
        )
        self.enhance.setVisible(has_enhancer)

    def _setup_models(self, params: dict, defaults: dict) -> None:
        """모델 선택 드롭다운을 워크플로에 맞춘다.

        워크플로에 없는 모델 종류는 비활성화한다.
        ComfyUI 오프라인이면 워크플로 기본값만 보여준다.
        """
        options = self.engine.model_options()
        for key, combo in self.model_combos.items():
            combo.blockSignals(True)
            combo.clear()
            spec = params.get(key)
            if spec is None:
                # 이 워크플로는 이 모델을 쓰지 않는다
                combo.addItem("(사용 안 함)")
                combo.setEnabled(False)
                combo.blockSignals(False)
                continue

            combo.setEnabled(True)
            folder = spec.kind.split(":", 1)[1] if ":" in spec.kind else ""
            items = list(options.get(folder) or [])
            current = defaults.get(key)
            if not items:
                # ComfyUI 응답이 없으면 워크플로 기본값만
                items = [current] if current else []
            for item in items:
                combo.addItem(item)
            if current:
                index = combo.findText(str(current))
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def _setup_lora_strength(self, params: dict, defaults: dict) -> None:
        """LoRA 강도 슬라이더를 워크플로에 맞춘다.

        워크플로마다 키가 "lora_strength" 또는 "strength_model" 처럼 다를 수
        있으므로 실제 ComfyUI 입력 이름(spec.input)으로 판단한다.
        """
        by_input = {spec.input: key for key, spec in params.items()}
        key = by_input.get("strength_model")
        self._lora_strength_key = key
        enabled = key is not None
        self.lora_box.setVisible(enabled)
        if not enabled:
            return
        value = defaults.get(key)
        if isinstance(value, (int, float)):
            self.lora_strength.setValue(int(round(float(value) * 100)))

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
                enhance_prompt=self.enhance.isChecked(),
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
        # 모델 선택 (확산 모델/텍스트 인코더/VAE/LoRA)
        for model_key, combo in self.model_combos.items():
            if not combo.isEnabled():
                continue
            key = by_input.get(combo_of_input(params, model_key))
            if key and combo.currentText():
                extra[key] = combo.currentText()
        # LoRA 강도
        key = getattr(self, "_lora_strength_key", None)
        if key:
            extra[key] = round(self.lora_strength.value() / 100, 2)
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
    app=QApplication(sys.argv); win=MainWindow(); win.show()

    # 창을 닫지 않고 프로그램이 끝나는 경로에서도 ComfyUI 를 정리한다.
    # (Ctrl+C, aboutToQuit 등 closeEvent 가 호출되지 않을 수 있다)
    atexit.register(win.engine.shutdown)
    app.aboutToQuit.connect(win.engine.shutdown)

    return app.exec()
