from __future__ import annotations
import sys, logging, atexit
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QPixmap, QBrush, QColor, QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QProgressBar,
    QMessageBox, QGroupBox, QTabWidget, QSizePolicy, QGridLayout, QSlider, QCheckBox,
    QListWidget, QFrame,
)
from app.comfy.workflow import (
    collect_extra, installed_models, missing_models,
)
from app.engine.comfy_engine import (
    GeurimGyeolEngine, _find_enhancer_node, injection_block_reason,
)
from app.engine.health import (
    UsageLevel, cpu_level, format_usage, gpu_level, ram_level, vram_level,
)
from app.gui.gpu_usage import GpuUsageReader
from app.gui.session_browser import HistoryBrowser
from app.gui.theme.manager import ThemeManager

ROOT = Path(__file__).resolve().parents[2]

GB = 1024 ** 3

# 단계별 색. 판정은 app/engine/health.py 가 하고, 색은 여기서 정한다.
# (engine 은 PySide6 를 모르므로 색을 알 수 없다)
_LEVEL_QSS = {
    UsageLevel.OK: "",
    UsageLevel.WARN: "color:#ffd93d;",
    UsageLevel.DANGER: "color:#ff6b6b;",
}


def _paint_usage(label: QLabel, text: str, level: UsageLevel) -> None:
    """상태바(와 ModelInfo) 한 칸에 글자와 단계 색을 함께 칠한다.

    상태바와 ModelInfo 가 같은 판단을 보여야 하므로 색칠은 반드시 이
    함수를 통한다. 각자 칠하면 언젠가 한쪽만 색이 어긋난다.
    """
    label.setText(text)
    label.setStyleSheet(_LEVEL_QSS[level])


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


class ComfyInfoWorker(QThread):
    """ComfyUI 상태·모델·샘플러 목록을 백그라운드에서 가져온다.

    이 호출들은 전부 네트워크 I/O 다. GUI 스레드에서 직접 부르면 창이
    그만큼 멈춘다 (ComfyUI 가 꺼져 있으면 연결 실패로 수 초,
    자동 실행 대기라면 launch_wait_seconds 만큼).

    네 가지를 한 번에 모아 emit 하므로 요청이 늘어나지 않는다.
    """

    # SystemInfo, models, samplers, enhancer_status
    fetched = Signal(object, object, object, object)

    def __init__(self, engine, allow_launch: bool = True):
        super().__init__()
        self.engine = engine
        self.allow_launch = allow_launch

    def run(self) -> None:
        info = self.engine.refresh_status(allow_launch=self.allow_launch)
        models = self.engine.model_options()
        samplers = self.engine.sampler_options()
        enhancer = self.engine.enhancer_status()
        self.fetched.emit(info, models, samplers, enhancer)


def _describe_parameters(parameters: dict) -> str:
    """워크플로가 받는 파라미터 이름을 한 줄로 요약한다.

    "7개" 는 사용자에게 아무 정보도 주지 않는다. 이름을 보여줘야
    "이 워크플로로 무엇을 조절할 수 있는가" 에 답할 수 있다.

    개행이 아니라 ' · ' 로 이어 붙인다. 13개 항목을 개행하면 세로로
    13줄이 되어 ModelInfo 높이 전체를 차지하고, 옆 칸이 빈 공간이 된다.
    (이것이 403px 를 만들던 원인이었다)

    Returns:
        파라미터가 없으면 "없음".
    """
    if not parameters:
        return "없음"
    # label 이 없으면 spec.name 이 곧 파라미터 키다. 빈칸으로 두면 의미가 없다.
    return " · ".join(
        spec.label or spec.name for spec in parameters.values()
    )


class ModelInfoPanel(QGroupBox):
    """선택한 워크플로와 ComfyUI 상태 요약 (v0.2 §11).

    네이티브 모델 파일이 아니라 ComfyUI 워크플로와 서버 상태를 보여준다.
    """

    def __init__(self, engine, parent=None):
        super().__init__("ModelInfo", parent)
        self.engine = engine
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        """워크플로 / 서버 두 구역으로 나눠 세로로 쌓는다.

        예전 2열 격자는 파라미터 목록(13~14줄) 하나가 행 높이를 통째로
        잡아서, 반대편 칸에 10줄 넘게 빈 공간이 생겼다. 403px 가 239px 로
        줄었다.

        구역을 나눈 이유는 값의 성격이 다르기 때문이다. RAM 이 빨개지는
        것은 워크플로 문제가 아니라 서버 문제인데, 같은 평면에 두면
        어느 쪽 때문인지 알 수 없다.

        배치:
            워크플로 — 이름 / 설명 / 노드 (3열) + 조절 가능 (전체 폭)
            ─────────
            서버     — ComfyUI / GPU / VRAM / RAM (4열) + 상태
        """
        outer = QVBoxLayout(self)
        outer.setSpacing(3)

        self.workflow_label = QLabel("-")
        self.description_label = QLabel("-")
        self.nodes_label = QLabel("-")
        self.params_label = QLabel("-")
        self.device_label = QLabel("-")
        self.vram_label = QLabel("-")
        self.ram_label = QLabel("-")
        self.comfy_label = QLabel("-")
        self.status_label = QLabel("-")
        self.status_label.setWordWrap(True)

        def _fit(label: QLabel) -> QLabel:
            """라벨이 세로로 꾹 눌려 글자가 겹치지 않게 최소 높이를 준다.

            회귀: wordWrap 을 켠 QLabel 의 minimumSizeHint 높이는 거의 0 이다.
            (아무리 좁아도 한 줄로 쪼갤 수 있다고 생각하기 때문)
            그래서 상위 레이아웃이 높이가 모자란 만큼 행을 눌러 버리고,
            14px 글자가 9px 칸에 들어가 항목 이름과 값이 겹쳤다.
            """
            label.setWordWrap(True)
            label.setMinimumHeight(QFontMetrics(label.font()).height())
            return label

        def _caption(text: str) -> QLabel:
            lb = QLabel(text)
            # font-size 를 지정하지 않는다. Models 탭의 라벨처럼 앱 기본
            # 폰트를 상속받아야 크기가 언제나 맞는다.
            lb.setStyleSheet("color:#a0a0a0;")
            return _fit(lb)

        def _value(label: QLabel) -> QLabel:
            # 색은 기본 검정을 유지한다.
            # 줄바꿈과 최소 높이가 있어야 창을 줄여도 글자가
            # 잘리지도 겹치지도 않는다.
            return _fit(label)

        def _section(text: str) -> QLabel:
            lb = QLabel(text)
            lb.setStyleSheet("color:#7a7a7a;")
            return _fit(lb)

        # ── 구역 1: 워크플로 ──────────────────────────────────
        outer.addWidget(_section("워크플로"))
        g1 = QGridLayout()
        g1.setHorizontalSpacing(10)
        g1.setVerticalSpacing(1)
        for col, (caption, label) in enumerate((
            ("Workflow", self.workflow_label),
            ("설명", self.description_label),
            ("노드", self.nodes_label),
        )):
            g1.addWidget(_caption(caption), 0, col)
            g1.addWidget(_value(label), 1, col)
        # 조절 가능은 13개 이름이 들어가므로 전체 폭을 한 줄로 쓴다
        g1.addWidget(_caption("조절 가능"), 2, 0)
        g1.addWidget(_value(self.params_label), 3, 0, 1, 3)
        outer.addLayout(g1)

        # ── 구역 경계 ────────────────────────────────────────
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#c8c8c8;")
        outer.addWidget(line)

        # ── 구역 2: 서버 ──────────────────────────────────────
        outer.addWidget(_section("서버"))
        g2 = QGridLayout()
        g2.setHorizontalSpacing(10)
        g2.setVerticalSpacing(1)
        for col, (caption, label) in enumerate((
            ("ComfyUI", self.comfy_label),
            ("GPU", self.device_label),
            ("VRAM", self.vram_label),
            ("RAM", self.ram_label),
        )):
            g2.addWidget(_caption(caption), 0, col)
            g2.addWidget(_value(label), 1, col)
        g2.addWidget(self.status_label, 2, 0, 1, 4)
        outer.addLayout(g2)

    def refresh_resources(
        self,
        vram_used_gb: float | None = None,
        vram_total_gb: float | None = None,
    ) -> None:
        """실시간 자원(RAM, VRAM)만 갱신한다.

        상태바의 느린 타이머(3초)에서 부른다. 워크플로가 그대로여도
        RAM 은 계속 오르므로, 워크플로 변경 때만 갱신하면 값이 멈춘다.

        VRAM 을 인자로 받는 이유는 값의 출처를 하나로 맞추기 위해서다.
        ComfyUI 의 system_info 는 '새로고침' 을 누를 때만 갱신되므로
        옛 값이다. nvidia-smi 값을 그대로 넘기면 상태바와 숫자가 어긋나지 않는다.
        """
        try:
            import psutil

            vm = psutil.virtual_memory()
            used_gb = (vm.total - vm.available) / GB
            total_gb = vm.total / GB
        except Exception:
            _paint_usage(self.ram_label, "-", UsageLevel.OK)
        else:
            _paint_usage(
                self.ram_label,
                format_usage("", vm.percent, used_gb, total_gb),
                ram_level(vm.percent),
            )

        if vram_used_gb is not None and vram_total_gb and vram_total_gb > 0:
            percent = vram_used_gb / vram_total_gb * 100
            _paint_usage(
                self.vram_label,
                format_usage("", percent, vram_used_gb, vram_total_gb),
                vram_level(percent),
            )
        elif self.engine.system_info.online:
            # nvidia-smi 가 없는 기기: ComfyUI 값을 그대로 쓴다
            self._paint_vram_from_comfyui()

    def _paint_vram_from_comfyui(self) -> None:
        """nvidia-smi 가 없을 때 ComfyUI 의 마지막 조회값으로 대신한다."""
        info = self.engine.system_info
        used = info.vram_used_gb
        if info.vram_total_gb and used is not None:
            _paint_usage(
                self.vram_label,
                format_usage("", info.vram_percent, used, info.vram_total_gb),
                vram_level(info.vram_percent),
            )
        else:
            _paint_usage(self.vram_label, "없음", UsageLevel.OK)

    def _set_status(self, text: str, color: str) -> None:
        """상태 문구와 색을 설정한다.

        font-size 는 넣지 않는다. setStyleSheet 는 기존 내용을 통째로
        덮어쓰므로 크기를 여기서 지정하면 값 라벨과 크기가 어긋난다.
        """
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color:{color};")

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
            # 워크플로가 특정 노드를 쓰는데 내 버전엔 그 노드가 없으면
            # 생성이 실패한다. 버전 한 줄이 그 원인을 설명해 준다.
            self.comfy_label.setText(info.comfyui_version or "알 수 없음")
        else:
            self.device_label.setText("-")
            self.vram_label.setText("-")
            self.comfy_label.setText("-")
            self._set_status(f"⚠ ComfyUI 접속 실패 — {info.error or ''}", "#ffd93d")
        # RAM 은 실시간 값이므로 별도 메서드가 맡는다 (3초 주기).

        wf = self.engine.active_workflow
        if wf is None:
            self.workflow_label.setText("-")
            self.description_label.setText("-")
            self.nodes_label.setText("-")
            self.params_label.setText("-")
            if info.online:
                self._set_status("⚠ workflows/ 폴더에 워크플로가 없습니다", "#ffd93d")
            return

        self.workflow_label.setText(wf.name)
        # 설명은 워크플로 파일에 이미 적혀 있다. 안 쓰고 있었다.
        self.description_label.setText(wf.description or "-")
        self.nodes_label.setText(f"{len(wf.prompt)}개")
        # "7개" 는 아무것도 알려주지 않는다. 이름이 있어야
        # "이 워크플로로 무엇을 조절할 수 있지?" 에 답이 된다.
        self.params_label.setText(_describe_parameters(wf.parameters))
        if info.online:
            self._set_status("✅ 준비 완료", "#6bcf7f")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("그려줘 v0.2 — Geuryeojwo")
        self._fit_to_screen()
        # 최소 높이는 실측값이다. 700 미만이면 Generate 탭의 Prompt 프레임과
        # spinbox 가 잘린다 (탭 영역 = 창 높이 - 약 96px, 필요 높이 약 604px).
        self.setMinimumSize(900, 700)
        self.engine=GeurimGyeolEngine(ROOT); self.worker=None
        # 창이 닫힌 뒤 도착한 워커 시그널은 버린다
        self._closing=False
        # ComfyUI 조회는 네트워크 I/O 라 GUI 스레드에서 하지 않는다.
        # 워크플로 목록만(디스크) 먼저 읽고, 서버 조회는 워커로 넘긴다.
        self.engine.refresh_workflows()
        self._info_worker=None
        self._comfy_models={}; self._comfy_samplers={}
        # (사용 가능 여부, 안내 문구) — 백그라운드 조회 결과가 채운다
        self._enhancer_status=None
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
        # setMinimumSize 와 같은 하한을 쓴다. 여기서만 700 보다 작게 잡으면
        # 창이 열리자마자 잘린다.
        self.resize(max(900, width), max(700, height))

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

        # ComfyUI 오프라인 안내 — 서버 조회가 끝난 뒤(_on_info_fetched)
        # 표시 여부가 정해지므로, 처음엔 숨겨 두었다 켠다.
        self.status_banner=QLabel("")
        self.status_banner.setWordWrap(True)
        self.status_banner.setStyleSheet("color:#ffd93d; font-size:12px;")
        self.status_banner.setVisible(False)
        root.addWidget(self.status_banner)

        tabs=QTabWidget()
        # Model 탭을 먼저 만든다. _on_workflow_changed() 가 self.model_info 를
        # 참조하므로, Generate 탭의 시그널이 불리기 전에 준비되어야 한다.
        # 워크플로 선택기는 Model 탭이 먼저 참조하므로 그보다 앞에 만든다.
        workflow_strip=self._build_workflow_strip()
        model_tab=self._build_model_tab()
        generate_tab=self._build_generate_tab()
        history_tab=self._build_history_tab()
        tabs.addTab(generate_tab, "Generate")
        tabs.addTab(model_tab, "Model")
        tabs.addTab(history_tab, "History")

        # 지금 무엇으로 그릴지 정하는 값이라 탭 어느 쪽에 있어도 보여야 한다.
        # 타이틀바는 이미 빽빽하므로 탭 줄 오른쪽 빈자리를 쓴다.
        #
        # 탭과 나란히 별도 레이아웃 줄을 두지 않고 탭 바의 '코너 위젯' 을 쓴다.
        # 그래야 탭 본체와 폭을 두고 다투지 않는다. 같은 줄 레이아웃에 두면
        # combo(긴 워크플로 이름이라 폭이 크다) 가 탭 본체의 최소 너비를
        # 밀어내 창 오른쪽에 빈 공간이 생긴다.
        tabs.setCornerWidget(workflow_strip, Qt.TopRightCorner)
        root.addWidget(tabs, 1)

        status_bar=QHBoxLayout()
        # 하단 상태바는 '지금 얼마나 하고 있는가' (사용률) 전용이다.
        # 무엇으로 돌아가는지(GPU 이름, VRAM 용량)는 타이틀바가 맡는다.
        # 같은 값을 두 곳에 두면 어느 쪽이 '진짜'인지 헷갈린다.
        self.status_ram=QLabel("RAM -"); status_bar.addWidget(self.status_ram)
        self.status_cpu=QLabel("CPU -"); status_bar.addWidget(self.status_cpu)
        self.status_vram=QLabel("VRAM -"); status_bar.addWidget(self.status_vram)
        self.status_gpu=QLabel("GPU -"); status_bar.addWidget(self.status_gpu)
        status_bar.addStretch()
        self.status_msg=QLabel("준비됨"); status_bar.addWidget(self.status_msg)
        root.addLayout(status_bar)
        # GPU 사용률과 VRAM 은 ComfyUI 가 알려주지 않으므로 nvidia-smi 로 읽는다
        self._gpu_usage=GpuUsageReader()
        # 마지막에 읽은 VRAM (사용 GB, 전체 GB). ModelInfo 와 값을 맞춘다.
        self._last_vram=(None, None)
        # 갱신 주기는 지표마다 다르다.
        #   CPU/GPU — 연산 중 급상승이라 1초 (계기판처럼 보여야 함)
        #   RAM/VRAM — 몇 분에 걸쳐 서서히 오르므로 3초면 충분
        # 두 타이머로 나눈 이유는 CPU 블로킹을 3분의 1 로 줄이려는 것도 있다.
        self._fast_timer=QTimer(); self._fast_timer.timeout.connect(self._update_status_fast); self._fast_timer.start(1000)
        self._slow_timer=QTimer(); self._slow_timer.timeout.connect(self._update_status_slow); self._slow_timer.start(3000)
        # 첫 표시를 즉시 채운다 (타이머는 주기 뒤부터 동작하므로)
        self._update_status_fast()
        self._update_status_slow()

    def _build_workflow_strip(self) -> QWidget:
        """탭 줄 오른쪽에 붙는 워크플로 선택기.

        지금 무엇으로 그릴지 정하는 값이라 어떤 탭에서도 보여야 한다.
        combos/ 목록 갱신은 '상태 새로고침' 이 함께 하므로 별도 버튼이 없다.
        """
        box=QWidget(); row=QHBoxLayout(box)
        row.setContentsMargins(0,0,0,0); row.setSpacing(4)
        row.addWidget(QLabel("Workflow:"))
        self.workflow=QComboBox()
        # 워크플로 이름이 길다 (예: 'Qwen-Image 2.1 텍스트→이미지'). 닫힌 상태는
        # 폭을 눌러서 탭 자리를 침범하지 않게 하고, 필요 이상이면 말줄임표로
        # 줄인다. 펼친 목록은 아래처럼 별도로 넓혀 이름이 다 보이게 한다.
        self.workflow.setMinimumWidth(190)
        self.workflow.setMaximumWidth(280)
        self.workflow.view().setMinimumWidth(360)
        row.addWidget(self.workflow)
        # 세로로는 늘어나지 않는다. 탭 줄 옆에 붙는 한 줄짜리 컨트롤이므로
        # 조합상자처럼 QTabWidget 높이까지 늘어나면 탭 줄이 아니게 된다.
        self.workflow.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return box

    def _build_model_tab(self) -> QWidget:
        """Model 탭 — 등록된 워크플로 전체 목록, 모델 파일, 워크플로 요약.

        지금 쓸 워크플로는 창 상단 드롭다운으로 고른다. 여기서는
        workflows/ 에 등록된 전체를 한눈에 보고 목록에서 바로 고를 수 있게 한다.
        모델 파일 목록은 선택한 워크플로에 종속되므로 같은 화면에 둔다.
        """
        tab=QWidget(); layout=QVBoxLayout(tab)

        wfbox=QGroupBox("등록된 워크플로"); wf_layout=QVBoxLayout(wfbox)
        self.workflow_list=QListWidget()
        # 목록에서 고르면 상단 드롭다운이 따라간다
        self.workflow_list.itemSelectionChanged.connect(self._on_workflow_list_selected)
        wf_layout.addWidget(self.workflow_list)
        layout.addWidget(wfbox, 1)

        # 모델 선택 — ComfyUI 의 폴더별 목록에서 고른다 (v0.2 §5.3)
        self.model_boxes=QGroupBox("Models"); ml=QGridLayout(self.model_boxes)
        ml.setHorizontalSpacing(4); ml.setVerticalSpacing(2)
        # (파라미터 키, 라벨) — 워크플로가 LoRA/확산모델을 쓸 때만 활성화된다
        self.model_combos: dict[str, QComboBox] = {}
        self._model_labels: dict[str, str] = {}
        # 마지막으로 조회한 ComfyUI 모델 목록. "설치 안 됨" 판정에 쓴다.
        self._model_options: dict[str, list[str]] = {}
        # 워크플로가 지정한 모델이 ComfyUI 에 없을 때 경고한다.
        # 없으면 다른 모델로 조용히 대체되어 사용자도 모르는 채
        # 잘못된 모델로 생성된다. (시그널이 먼저 발화할 수 있어
        # 콤보 만들기 전에 만든다)
        self._model_warning=QLabel("")
        self._model_warning.setWordWrap(True)
        self._model_warning.setStyleSheet("color:#ff6b6b; font-size:12px;")
        self._model_warning.setVisible(False)
        for row, (key, caption) in enumerate(
            (("unet", "확산 모델"), ("clip", "텍스트 인코더"),
             ("vae", "VAE"), ("lora", "LoRA"))
        ):
            combo=QComboBox(); combo.setMinimumWidth(120)
            # 모델이 많으면 드롭다운이 화면을 다 먹는다.
            # 8줄까지만 보여주고 나머지는 스크롤로 넘긴다.
            combo.setMaxVisibleItems(8)
            self.model_combos[key]=combo
            self._model_labels[key]=caption
            combo.currentIndexChanged.connect(
                lambda _i, k=key: self._update_model_warning(k)
            )
            ml.addWidget(QLabel(caption), row, 0)
            ml.addWidget(combo, row, 1)
        layout.addWidget(self.model_boxes)
        layout.addWidget(self._model_warning)

        self.model_info=ModelInfoPanel(self.engine); layout.addWidget(self.model_info)
        layout.addStretch()
        self.workflow.currentIndexChanged.connect(lambda _: self._on_workflow_changed())
        return tab

    def _build_generate_tab(self) -> QWidget:
        """Generate 탭 (v0.2).

        선택한 워크플로가 받는 파라미터만 입력받는다.
        워크플로·모델 선택은 Model 탭에 있다.
        """
        tab=QWidget(); layout=QVBoxLayout(tab)
        body=QHBoxLayout(); layout.addLayout(body)
        left=QVBoxLayout(); body.addLayout(left,1); right=QVBoxLayout(); body.addLayout(right,1)

        promptbox=QGroupBox("Prompt"); pl=QVBoxLayout(promptbox)
        self.prompt=QTextEdit(); self.prompt.setPlaceholderText("무엇을 그리고 싶나요?")
        self.prompt.setMinimumHeight(90); pl.addWidget(self.prompt)
        # 프롬프트 인핸서 — ComfyUI 안의 LLM 노드가 프롬프트를 다듬는다.
        # 느릴 수 있어 끌 수 있어야 한다.
        # 워크플로에 노드가 없어도 프로그램이 자동 추가하므로,
        # 준비가 안 됐을 때만 아래 경고로 알린다.
        self.enhance=QCheckBox("프롬프트 인핸서 사용 (더 정확해지지만 느림)")
        self.enhance.setChecked(True)
        self.enhance.toggled.connect(self._update_enhancer_warning)
        pl.addWidget(self.enhance)
        self.enhancer_warning=QLabel(""); self.enhancer_warning.setVisible(False)
        self.enhancer_warning.setWordWrap(True)
        self.enhancer_warning.setStyleSheet("color:#d9534f; font-size:11px;")
        pl.addWidget(self.enhancer_warning)
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

        # LoRA 강도 — 별도 프레임이 아니라 Generation 프레임 안에 둔다.
        # 워크플로에 strength_model 입력이 없으면 이 줄만 숨긴다
        # (_setup_lora_strength 가 self.lora_box 를 토글한다).
        self.lora_strength=QSlider(Qt.Horizontal); self.lora_strength.setRange(0,150)
        self.lora_strength.setValue(100); self.lora_strength.setSingleStep(5)
        self.lora_strength_label=QLabel("LoRA 강도 1.00")
        self.lora_strength_label.setStyleSheet("color:#a0a0a0; font-size:11px;")
        self.lora_strength.valueChanged.connect(
            lambda v: self.lora_strength_label.setText(f"LoRA 강도 {v / 100:.2f}")
        )
        self.lora_box=QWidget()
        lora_row=QHBoxLayout(self.lora_box); lora_row.setSpacing(4)
        lora_row.setContentsMargins(0,0,0,0)
        lora_row.addWidget(self.lora_strength_label)
        lora_row.addWidget(self.lora_strength, 1)
        pv.addWidget(self.lora_box)

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

    def _build_history_tab(self) -> QWidget:
        """History 탭 (Output Browser + Session History 통합)."""
        self.history_browser = HistoryBrowser(ROOT / "sessions", ROOT / "outputs")
        self.history_browser.regenerate_requested.connect(self._on_regenerate)
        return self.history_browser

    def _toggle_theme(self) -> None:
        """다크/라이트 테마 토글 (§24)."""
        theme = self.theme_manager.toggle_theme()
        self.log.append(f"Theme switched to: {theme}")

    def _update_status_fast(self) -> None:
        """1초마다 갱신 — 변화가 빠른 지표만 (CPU, GPU).

        cpu_percent(interval=0.1) 은 이름과 달리 0.1초를 실제로 sleep 한다.
        매초 부르면 1분에 6초를 창이 멈춰 있게 된다(실측 100.5ms/회).
        interval=None 은 직전 호출 대비 변화율이라 0.018ms 로 끝난다.
        (첫 호출은 0 을 주지만 차이를 알아채는 데 영향이 없다)
        """
        try:
            import psutil

            self._cpu_percent = psutil.cpu_percent(interval=None)
        except Exception:
            self._cpu_percent = None
        _paint_usage(
            self.status_cpu,
            format_usage("CPU", self._cpu_percent),
            cpu_level(self._cpu_percent),
        )
        self._update_gpu_usage()

    def _update_status_slow(self) -> None:
        """3초마다 갱신 — 변화가 느린 지표 (RAM, VRAM).

        RAM 은 몇 분에 걸쳐 오르는 값이라 3초 주기로도 사람이 변화를
        알아챌 수 있다. 대신 1초마다 재면 CPU 블로킹만 늘어난다.
        """
        try:
            import psutil

            vm = psutil.virtual_memory()
            # percent 와 용량을 같은 기준(total - available)으로 맞춘다.
            used_gb = (vm.total - vm.available) / GB
            total_gb = vm.total / GB
            _paint_usage(
                self.status_ram,
                format_usage("RAM", vm.percent, used_gb, total_gb),
                ram_level(vm.percent),
            )
            self._ram_used_gb, self._ram_total_gb = used_gb, total_gb
        except Exception:
            _paint_usage(self.status_ram, "RAM -", UsageLevel.OK)
            self._ram_used_gb = self._ram_total_gb = None

        self._update_vram()
        # ModelInfo 의 RAM/VRAM 칸도 같은 값을 쓴다 (출처가 달라지면
        # 8.0GB 와 7.9GB 처럼 숫자가 어긋나 보인다)
        self.model_info.refresh_resources(*self._last_vram)

    def _update_vram(self) -> None:
        """VRAM 을 표시하고, 읽은 (사용 GB, 전체 GB) 를 기억한다.

        nvidia-smi 상주 프로세스에서 읽으면 '새로고침' 을 누르기 전까지
        값이 멈춰 있는 문제를 피할 수 있다. nvidia-smi 가 없는 기기
        (AMD/Intel) 는 ComfyUI 가 알려준 값으로 대신한다.
        """
        reader = self._gpu_usage
        if not reader.available:
            if not reader.started:
                # 아직 시도 안 했거나 못 찾은 상태다. 한 번만 시도한다.
                reader.start()
            if not reader.available:
                self._vram_from_comfyui()
                return

        used_gb, total_gb = reader.vram_gb()
        percent = None
        if used_gb is not None and total_gb:
            percent = used_gb / total_gb * 100
        _paint_usage(
            self.status_vram,
            format_usage("VRAM", percent, used_gb, total_gb),
            vram_level(percent),
        )
        self._last_vram = (used_gb, total_gb)

    def _vram_from_comfyui(self) -> None:
        """nvidia-smi 가 없을 때 ComfyUI 의 마지막 조회값으로 대신한다.

        이 값은 '새로고침' 을 누를 때만 갱신되므로 실시간은 아니다.
        그래도 없는 것보다 나으므로 유지한다.
        """
        info = self.engine.system_info
        # vram_total_gb 이 있어도 vram_used_gb 이 None 일 수 있다( free 미제공 ).
        used = info.vram_used_gb
        if info.online and info.vram_total_gb and used is not None:
            percent = info.vram_percent
            _paint_usage(
                self.status_vram,
                format_usage("VRAM", percent, used, info.vram_total_gb),
                vram_level(percent),
            )
            self._last_vram = (used, info.vram_total_gb)
        else:
            _paint_usage(self.status_vram, "VRAM -", UsageLevel.OK)
            self._last_vram = (None, None)

    def _update_gpu_usage(self) -> None:
        """GPU 사용률(%) 을 표시한다.

        nvidia-smi 가 없는 기기(AMD/Intel) 는 조용히 '지원 안 함' 으로
        둔다. 상태바 한 칸이 프로그램 전체를 막을 이유는 없다.
        """
        reader = self._gpu_usage
        if not reader.available:
            if not reader.started:
                # 아직 시도 안 했거나 못 찾은 상태다. 한 번만 시도한다.
                reader.start()
            if not reader.available:
                _paint_usage(self.status_gpu, "GPU 지원 안 함", UsageLevel.OK)
                return
        percent = reader.percent()
        _paint_usage(
            self.status_gpu, format_usage("GPU", percent), gpu_level(percent)
        )

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

    def _on_regenerate(self, prompt: str, params: dict, image_model: object) -> None:
        """History 탭에서 재생성 요청.

        워크플로 이름이 있으면 그 워크플로까지 선택한다.
        미분류 출력처럼 이름이 없으면 파라미터만 되돌린다.
        """
        self._apply_regenerated(prompt, params)

        if not image_model:
            self.status.setText("파라미터를 불러왔습니다. 그려줘를 눌러주세요.")
            return

        # 기록에는 워크플로 표시 이름이 저장되어 있다 (v0.2 에서는 모델 경로가 아니다)
        name = str(image_model)
        index = self._find_workflow_index(name)
        if index >= 0:
            self.workflow.setCurrentIndex(index)
            self.status.setText("기록의 워크플로와 파라미터를 불러왔습니다. 그려줘를 눌러주세요.")
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

        서버 조회는 네트워크 I/O 라 GUI 스레드에서 하지 않는다.
        여기서는 목록(디스크)만 갱신하고, 상태·모델·샘플러는
        ComfyInfoWorker 가 백그라운드에서 가져온 뒤 적용한다.
        """
        if self._info_worker is not None and self._info_worker.isRunning():
            return  # 이미 조회 중이면 중복 요청하지 않는다

        self.comfy_label.setText("ComfyUI 확인 중...")
        self.status_refresh.setEnabled(False)
        self._reload_workflows()
        self._info_worker=ComfyInfoWorker(
            self.engine, allow_launch=self.engine.config.auto_launch
        )
        self._info_worker.fetched.connect(self._on_info_fetched)
        self._info_worker.start()

    def _on_info_fetched(self, info, models, samplers, enhancer=None) -> None:
        """ComfyUI 조회가 끝난 뒤(GUI 스레드) 위젯에 반영한다."""
        if self._closing: return
        self.engine.system_info = info
        self._comfy_models = models or {}
        self._comfy_samplers = samplers or {}
        self._enhancer_status = enhancer

        self.comfy_label.setText(self.engine.status_text())
        self.comfy_label.setStyleSheet(
            "color:#7fb3ff;" if self.engine.online else "color:#d9534f;"
        )
        self.status_refresh.setEnabled(True)
        self._update_offline_banner()
        # 서버 조회가 끝났으니 VRAM/RAM 을 즉시 반영한다.
        # (타이머를 기다리면 갱신 전 값이 최대 3초 더 남는다)
        self._update_status_slow()
        # 새 목록으로 콤보를 다시 채운다 (사용자가 고른 값은 유지된다)
        if self.engine.active_workflow is not None:
            self._on_workflow_changed(preserve_selection=True)

    def _update_offline_banner(self) -> None:
        """ComfyUI 접속 안내 문구를 갱신한다."""
        if self.engine.online:
            self.status_banner.setVisible(False)
            return
        if self.engine.config.auto_launch:
            text = (
                "⚠ ComfyUI 에 접속할 수 없어 자동으로 실행을 시도했습니다. "
                f"사유: {self.engine.system_info.error or '알 수 없음'}\n"
                "'상태 새로고침'을 누르면 다시 시도합니다."
            )
        else:
            text = (
                "⚠ ComfyUI 서버에 접속할 수 없습니다. "
                "ComfyUI를 실행한 뒤 '상태 새로고침'을 눌러주세요.\n"
                "config/comfyui.json 의 auto_launch 를 켜면 자동으로 실행합니다."
            )
        self.status_banner.setText(text)
        self.status_banner.setVisible(True)

    def _reload_workflows(self):
        """workflows/ 폴더를 다시 읽어 드롭다운과 목록을 채운다.

        '상태 새로고침' 이 이 메서드를 함께 부르므로 별도 버튼은 없다.
        """
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
        self._sync_workflow_list()
        # 워크플로를 다시 읽는 것은 목록 갱신이지 워크플로 변경이 아니므로
        # 사용자가 고른 모델/샘플러를 유지한다.
        # (백그라운드 조회가 끝난 뒤 다시 채울 때도 같은 값을 되돌려 둔다)
        self._on_workflow_changed(preserve_selection=True)

    def _sync_workflow_list(self) -> None:
        """Model 탭의 목록을 드롭다운 내용과 선택으로 맞춘다.

        재생성으로 드롭다운이 바뀌는 경우에도 따라가야 하므로
        드롭다운이 바뀔 때마다 부른다.
        """
        # 목록은 Model 탭을 만들면서 생긴다. 그 전에 불릴 수 있다
        if not hasattr(self, "workflow_list"):
            return
        self.workflow_list.blockSignals(True)
        self.workflow_list.clear()
        for i in range(self.workflow.count()):
            self.workflow_list.addItem(self.workflow.itemText(i))
        index = self.workflow.currentIndex()
        if index >= 0:
            self.workflow_list.setCurrentRow(index)
        self.workflow_list.blockSignals(False)

    def _on_workflow_list_selected(self) -> None:
        """Model 탭 목록에서 고른 워크플로를 상단 드롭다운에 반영한다."""
        row = self.workflow_list.currentRow()
        # 같은 항목을 고르면 드롭다운을 건드리지 않는다 (불필요한 재적용 방지)
        if row < 0 or row == self.workflow.currentIndex():
            return
        self.workflow.setCurrentIndex(row)

    def _on_workflow_changed(self, preserve_selection: bool = False):
        """워크플로 선택을 엔진에 반영하고 입력 가능 여부를 갱신한다.

        preserve_selection=True 이면 새로고침으로 사용자가 고른
        모델/샘플러가 워크플로 기본값으로 되돌아가지 않게 유지한다.
        """
        name = self.workflow.currentData()
        if name is not None:
            self.engine.select_workflow(name)
        # 재생성 등으로 드롭다운이 바뀌면 목록 강조도 따라간다
        self._sync_workflow_list()
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
        self._setup_sampler(params, defaults, preserve_selection)
        self._setup_models(params, defaults, preserve_selection)
        self._setup_lora_strength(params, defaults)
        self._setup_enhancer(params, defaults)
        self.status.setText(
            f"{wf.name} · 파라미터 {len(params)}개 사용 가능"
        )

    def _setup_enhancer(self, params: dict, defaults: dict) -> None:
        """프롬프트 인핸서 스위치를 워크플로에 맞춘다.

        인핸서 노드가 없어도 프로그램이 직접 추가할 수 있으므로,
        예전처럼 '노드가 없으면 숨김' 으로 처리하지 않는다.
        대신 붙일 수 없는 경우에는 스위치를 끄고 이유를 툴팁으로 보인다.
        (조용히 사라지면 사용자는 왜 안 되는지 알 수 없다)
        """
        wf = self.engine.active_workflow
        if wf is None:
            self.enhance.setVisible(False)
            return

        self.enhance.setVisible(True)

        if _find_enhancer_node(wf.prompt) is not None:
            self.enhance.setEnabled(True)
            self.enhance.setToolTip(
                "워크플로에 포함된 LLM 노드가 프롬프트를 다듬습니다."
            )
        else:
            reason = injection_block_reason(wf)
            if reason:
                self.enhance.setChecked(False)
                self.enhance.setEnabled(False)
                self.enhance.setToolTip(reason)
            else:
                self.enhance.setEnabled(True)
                self.enhance.setToolTip(
                    "워크플로에 인핸서 노드가 없어 생성할 때 자동으로 추가합니다."
                )
        self._update_enhancer_warning()

    def _update_enhancer_warning(self, *_args) -> None:
        """인핸서를 켰는데 준비가 안 된 경우 상태바에 경고를 띄운다.

        노드나 GGUF 모델이 없으면 ComfyUI 가 생성 자체를 거부하므로
        조용히 원본 프롬프트로 생성하면 사용자는 이유를 알 수 없다.
        """
        if not self.enhance.isVisible() or not self.enhance.isEnabled():
            self.enhancer_warning.setVisible(False)
            return
        if not self.enhance.isChecked():
            self.enhancer_warning.setVisible(False)
            return

        ok, message = self._enhancer_status or (False, "확인되지 않음")
        if ok:
            self.enhancer_warning.setVisible(False)
            return
        self.enhancer_warning.setText(f"⚠ 프롬프트 인핸서: {message}")
        self.enhancer_warning.setVisible(True)

    def _setup_models(self, params: dict, defaults: dict,
                      preserve_selection: bool = False) -> None:
        """모델 선택 드롭다운을 워크플로에 맞춘다.

        워크플로에 없는 모델 종류는 비활성화한다.
        ComfyUI 목록은 백그라운드 워커가 받아 온 캐시(self._comfy_models)를
        쓴다 — 여기서 직접 조회하면 GUI 스레드가 네트워크 만큼 멈춘다.

        워크플로가 지정한 모델이 ComfyUI 목록에 없으면 목록의
        다른 파일로 대체하지 않는다. 목록에 없는 이름을 그대로
        넣고 빨간색으로 표시한다. 대체해 버리면 사용자도 모르는 채
        잘못된 모델로 생성된다.

        preserve_selection=True 이면 사용자가 고른 값이 목록에 그대로
        있을 때 되돌려 놓는다 (새로고침해도 선택이 사라지지 않는다).
        """
        options = self._comfy_models
        # ComfyUI 목록을 저장해 두어야 "설치 안 됨"을 다시 판정할 수 있다
        self._model_options = options
        chosen = (
            {key: combo.currentText() for key, combo in self.model_combos.items()}
            if preserve_selection else {}
        )
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
            # 목록에 없다고 버리지 말고 그대로 넣는다 (교체하지 않는다)
            if current and str(current) not in items:
                combo.insertItem(0, str(current))
            if current:
                index = combo.findText(str(current))
                if index >= 0:
                    combo.setCurrentIndex(index)
            # 사용자가 직접 고른 값이 여전히 유효하면 유지한다
            keep = chosen.get(key)
            if keep:
                index = combo.findText(keep)
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self._paint_missing_models()

    def _active_params(self) -> dict:
        """활성 워크플로의 parameters 맵."""
        return (self.engine.active_workflow.parameters
                if self.engine.active_workflow else {})

    def _model_selections(self) -> dict[str, str]:
        """활성화된 모델 콤보의 현재 값만 모은다."""
        return {
            key: combo.currentText()
            for key, combo in self.model_combos.items()
            if combo.isEnabled()
        }

    def _installed_models(self, key: str) -> list[str]:
        """이 모델 키가 쓰는 ComfyUI 폴더의 설치된 파일 목록."""
        return installed_models(self._model_options, self._active_params(), key)

    def _paint_missing_models(self) -> None:
        """설치되지 않은 모델 항목을 빨간색과 툴팁으로 표시한다."""
        for key, combo in self.model_combos.items():
            if not combo.isEnabled():
                continue
            installed = self._installed_models(key)
            if not installed:
                # ComfyUI 목록을 못 받은 상태라 판정할 수 없다
                continue
            for i in range(combo.count()):
                text = combo.itemText(i)
                if text in installed:
                    combo.setItemData(i, QBrush(QColor("#c9d1d9")), Qt.ForegroundRole)
                    combo.setItemData(i, "", Qt.ToolTipRole)
                else:
                    combo.setItemData(i, QBrush(QColor("#ff6b6b")), Qt.ForegroundRole)
                    combo.setItemData(
                        i, f"{text} — ComfyUI 에 설치되어 있지 않습니다",
                        Qt.ToolTipRole,
                    )
        self._update_model_warning()

    def _missing_models(self) -> list[tuple[str, str]]:
        """현재 선택된 값 중 설치되지 않은 모델 목록.

        Returns:
            [(콤보 키, 모델 파일명), ...]
        """
        return missing_models(
            self._model_options, self._active_params(), self._model_selections()
        )

    def _update_model_warning(self, _key=None) -> None:
        """모델 탭의 경고 라벨을 갱신한다.

        콤보 값이 바뀌면 호출되므로, 사용자가 설치된 모델을 고르면
        경고가 사라진다.
        """
        missing = self._missing_models()
        if not missing:
            self._model_warning.setText("")
            self._model_warning.setVisible(False)
            return
        names = ", ".join(
            f"{self._model_labels.get(key, key)}: {name}" for key, name in missing
        )
        self._model_warning.setText(
            f"⚠ 설치되지 않은 모델 — {names}\n"
            "Model 탭에서 ComfyUI 에 설치된 모델로 바꿔야 생성할 수 있습니다."
        )
        self._model_warning.setVisible(True)

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

    def _setup_sampler(self, params: dict, defaults: dict,
                       preserve_selection: bool = False) -> None:
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
            # 목록은 백그라운드 워커가 받아 온 캐시를 쓴다
            options = self._comfy_samplers
        else:
            options = {}

        # 새로고침이어도 사용자가 고른 샘플러를 되돌려 놓는다
        keep_sampler = self.sampler.currentText() if preserve_selection else ""
        keep_scheduler = self.scheduler.currentText() if preserve_selection else ""

        for combo, key, option_key, keep in (
            (self.sampler, sampler_key, "sampler", keep_sampler),
            (self.scheduler, scheduler_key, "scheduler", keep_scheduler),
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
            # 사용자가 직접 고른 값이 여전히 있으면 유지한다
            if keep:
                index = combo.findText(keep)
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

        # 워크플로가 지정한 모델이 설치되지 않았으면 미리 막는다.
        # 없던 모델을 목록의 다른 파일로 대체하지 않으므로 그대로 보내면
        # ComfyUI 가 node_errors 로 거부한다 (§5.3).
        missing = self._missing_models()
        if missing:
            names = "\n".join(
                f"· {self._model_labels.get(k, k)}: {v}" for k, v in missing
            )
            QMessageBox.warning(
                self, "설치되지 않은 모델",
                "워크플로가 지정한 모델이 ComfyUI 에 없습니다:\n\n"
                f"{names}\n\n"
                "Model 탭에서 ComfyUI 에 설치된 모델을 선택하거나,\n"
                "workflows/ 의 워크플로 JSON 에 적힌 모델 이름을 확인해 주세요."
            )
            return

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

        키 이름은 워크플로마다 다르므로("sampler" 또는 "sampler_name"),
        매핑과 값 조립은 workflow.collect_extra 가 맡는다.
        비활성화된 항목은 보내지 않는다 — 그래야 워크플로 기본값이 유지된다.
        """
        selections = self._model_selections()
        if self.sampler.isEnabled():
            selections["sampler"] = self.sampler.currentText()
        if self.scheduler.isEnabled():
            selections["scheduler"] = self.scheduler.currentText()

        lora_key = getattr(self, "_lora_strength_key", None)
        lora_strength = (self.lora_strength.value() / 100) if lora_key else None
        return collect_extra(
            self._active_params(), selections,
            lora_key=lora_key, lora_strength=lora_strength,
        )

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
        if self._closing: return
        self.generate.setEnabled(True)
        pixmap=QPixmap(path)
        if not pixmap.isNull():
            self.preview.setPixmap(pixmap.scaled(
                self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.status.setText(f"완료: {Path(path).name}")
        self.log.append(f"저장: {path}\nPrompt: {meta.get('prompt','')}")
        if hasattr(self, 'history_browser'): self.history_browser._refresh_list()

    def fail(self, msg, suggestion=None):
        """실패 처리.

        v0.2 에서는 메모리 부족 복구 제안(VRAM 하향 등)을 하지 않는다.
        VRAM 관리는 ComfyUI 가 하고, 이 프로그램은 파라미터만 넘기기
        때문이다. 오류 원인은 워크플로/노드/모델 쪽에 있으므로 로그로 남긴다.
        """
        if self._closing: return
        self.generate.setEnabled(True)
        self.status.setText("실패")
        self.log.append("ERROR: " + msg)
        QMessageBox.critical(self, "생성 실패", msg)

    def closeEvent(self, event):
        # 닫은 뒤 도착하는 워커 시그널은 무시한다.
        # (대화상자가 닫힌 창에 뜨거나, 죽은 위젯에 손대게 된다)
        self._closing = True
        self._fast_timer.stop()
        self._slow_timer.stop()
        # nvidia-smi 를 상주시켜 두므로 창을 닫으면 반드시 정리한다
        self._gpu_usage.stop()
        # 진행 중인 조회가 창이 닫힌 뒤 시그널이 날아와 크래시가 난다
        if self._info_worker is not None and self._info_worker.isRunning():
            self._info_worker.fetched.disconnect(self._on_info_fetched)
            self._info_worker.wait(3000)
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
