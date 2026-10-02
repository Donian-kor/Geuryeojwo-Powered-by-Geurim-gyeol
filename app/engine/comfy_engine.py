"""ComfyUI 기반 GeurimGyeolEngine v0.2 (v0.2 §5).

네이티브 추론(torch/diffusers)을 직접 수행하지 않는다.
ComfyUI가 모델 실행·VRAM 관리·양자화를 전부 담당하고,
이 클래스는 GUI에 필요한 동기 인터페이스를 제공하며
워크플로 선택 → 값 주입 → 실행 → 결과 저장을 중재한다.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..comfy import ComfyClient, ComfyUIConfig, ComfyUIError, SystemInfo
from ..comfy.client import extract_text_outputs
from ..comfy.workflow import Workflow, infer_parameters, list_workflows, load_workflow
from .output.manager import OutputManager, OutputMetadata
from .session.manager import SessionManager, SessionMetadata

# 이미지를 남기는 출력 노드 (앞에서부터 우선)
_OUTPUT_NODES = ("SaveImage", "PreviewImage", "SaveAnimatedWEBP", "SaveAnimatedPNG")
# 프롬프트 인핸서 노드로 간주하는 class_type
_ENHANCER_TYPES = ("PromptEnhance", "PromptEnhancer", "PromptExpander")
# 인핸서 노드에서 LLM 모델명을 읽어올 입력 키 (우선순위 순).
# 인핸서는 API 모드 / 로컬 GGUF / 사용자 지정 모델을 지원하는데,
# 어느 쪽이 실제로 쓰였는지는 api_mode 라는 자유 입력 문자열에만 있고
# 그 문자열은 워크플로마다 한국어 표현이 달라 파싱할 수 없다.
# 그래서 "값이 채워져 있는 첫 번째" 를 모델명으로 기록한다.
_ENHANCER_MODEL_INPUTS = ("custom_model", "local_model", "ai_workshop_model")
# 인핸서 노드가 없는 워크플로에 자동으로 넣을 때 쓸 노드 종류.
# 앞의 것부터 확인하고, ComfyUI 에 설치된 첫 번째를 쓴다.
_ENHANCER_INJECT_CLASSES = (
    "QwenImage21PromptEnhancerT8",
    "MiniMaxH3PromptEnhancerT8",
    "Seedance20PromptEnhancerT8",
)
# 인핸서가 여러 백엔드(온라인 API / OpenAI 호환 / 로컬 GGUF) 중에서
# 고를 때, 이 표시가 있는 항목을 우선한다.
# 노드 자체의 기본값은 '온라인 상점' 이라 API 키가 없으면 실패한다.
# 이 프로그램은 로컬 GGUF 전제로 만들어졌으므로 그쪽을 고른다.
# 표기가 언어와 무관하게 고르려고 'GGUF' 라는 문자열로 찾는다.
_ENHANCER_LOCAL_MODE_MARK = "gguf"
# 텍스트 인코더에서 "사용자 프롬프트" 를 받는 입력 이름.
# Flux(clip_l/t5xxl) · SD3(clip_l/clip_g/t5xxl) 처럼 인코더가 여러 개인
# 모델은 여기 걸리지 않으므로 자동으로 붙지 않는다.
# 어느 인코더에 붙여야 할지는 워크플로마다 달라 프로그램이 정할 수 없다.
_PROMPT_TEXT_INPUTS = ("text", "prompt", "positive", "user_prompt")

# ComfyUI 목록 조회 결과의 캐시 유효 시간(초).
# 노드를 방금 설치했을 수 있으니 너무 길지 않게 둔다.
# 한 번에 여러 파일을 확인하는 동안에는 재사용된다.
_LIST_CACHE_TTL = 300.0
# 설정에 model_folders 가 없을 때 쓸 기본 목록.
_DEFAULT_MODEL_FOLDERS = (
    "checkpoints", "diffusion_models", "vae", "loras", "text_encoders", "LLM",
)


def _is_enhancer(class_type: str) -> bool:
    """프롬프트 인핸서 노드인지 판단한다."""
    return any(marker in class_type for marker in _ENHANCER_TYPES)


def _find_enhancer_node(prompt: dict) -> str | None:
    """인핸서 노드의 ID 를 찾는다. 없으면 None."""
    for node_id, node in (prompt or {}).items():
        if isinstance(node, dict) and _is_enhancer(node.get("class_type", "")):
            return node_id
    return None


def _prompt_text_inputs(node: dict) -> list[str]:
    """노드가 가진 프롬프트 문자열 입력 이름들 (링크가 아닌 값만)."""
    inputs = node.get("inputs") or {}
    return [
        name for name in _PROMPT_TEXT_INPUTS
        if isinstance(inputs.get(name), str)
    ]


def injection_target(wf: Workflow) -> tuple[str, str] | None:
    """인핸서를 붙일 (노드 ID, 입력 이름) 을 찾는다.

    워크플로에 인핸서가 이미 있으면 붙일 곳이 없으므로 None.
    프롬프트 문자열 입력이 '정확히 하나' 인 텍스트 인코더만 대상으로 한다.
    SDXL(text_g/text_l) 처럼 둘 이상이면 어느 쪽에 붙여야 하는지
    워크플로마다 달라 판단할 수 없으므로 넣지 않는다.

    Returns:
        tuple[str, str] | None: 붙일 자리, 없으면 None
    """
    if wf is None or _find_enhancer_node(wf.prompt) is not None:
        return None
    spec = wf.parameters.get("positive")
    if spec is None:
        return None
    node = (wf.prompt or {}).get(spec.node)
    if not isinstance(node, dict) or _is_enhancer(node.get("class_type", "")):
        return None
    if _prompt_text_inputs(node) != [spec.input]:
        return None
    return spec.node, spec.input


def injection_block_reason(wf: Workflow) -> str:
    """자동 추가가 안 되는 이유를 문장으로 돌려준다. 가능하면 빈 문자열.

    GUI 가 스위치를 끄면서 사유를 보여줄 때 쓴다.
    """
    if wf is None:
        return "워크플로가 없습니다."
    if _find_enhancer_node(wf.prompt) is not None:
        return ""
    spec = wf.parameters.get("positive")
    if spec is None:
        return (
            "이 워크플로에서 프롬프트를 받는 노드를 찾지 못했습니다. "
            "텍스트 인코더 노드가 필요합니다."
        )
    node = (wf.prompt or {}).get(spec.node)
    if not isinstance(node, dict):
        return f"노드 {spec.node} 을(를) 찾을 수 없습니다."
    count = len(_prompt_text_inputs(node))
    if count == 0:
        return (
            f"{spec.node} 노드는 프롬프트를 직접 받지 않습니다. "
            "텍스트 인코더 노드가 필요합니다."
        )
    if count > 1:
        return (
            f"{spec.node} 노드에 프롬프트 입력이 {count}개 있어 어디에 "
            "연결할지 결정할 수 없습니다. 워크플로 JSON 에 직접 지정하세요."
        )
    return ""


def _free_node_id(prompt: dict) -> str:
    """워크플로와 겹치지 않는 인핸서 노드 ID 를 만든다."""
    index = 1
    while f"prompt_enhancer_{index}" in (prompt or {}):
        index += 1
    return f"prompt_enhancer_{index}"


def _enhancer_model(payload: dict) -> str | None:
    """실제로 실행된 인핸서의 LLM 모델명을 payload 에서 읽는다.

    인핸서 스위치를 끈 경우 _bypass_enhancer 가 노드를 payload 에서
    지우므로 인핸서를 찾을 수 없고 None 이 나온다.
    붙일 자리가 없어 자동 추가에 실패한 경우도 마찬가지로 None 이다.
    None 은 "LLM 이 안 돌았다" 는 뜻이므로 그대로 기록하면 된다.

    Returns:
        str | None: 모델명, 또는 인핸서를 실행하지 않았으면 None
    """
    for node in (payload or {}).values():
        if not isinstance(node, dict):
            continue
        if not _is_enhancer(node.get("class_type", "")):
            continue
        inputs = node.get("inputs") or {}
        for key in _ENHANCER_MODEL_INPUTS:
            value = inputs.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _pick_enhanced_prompt(
    wf: Workflow,
    history: dict | None,
    prompt_id: str | None,
    fallback: str,
) -> str:
    """이미지에 실제로 들어간 프롬프트를 고른다.

    인핸서를 켜면 그 노드의 출력이 곧 이미지 모델에 들어간 값이다.
    껐으면 history 에 남는 텍스트 중 positive 로 연결된 노드의 것을 쓴다.

    아무 텍스트나 고르면 안 된다. positive 와 negative 가 별도
    CLIPTextEncode 인 워크플로에서는 history 순서가 negative 를 먼저
    주므로, 네거티브 문장이 프롬프트로 기록된다.
    (ERNIE 기본 워크플로: positive=2, negative=3)

    Args:
        wf: 실행한 워크플로
        history: ComfyUI /history 응답
        prompt_id: 방금 실행한 프롬프트 id
        fallback: 못 찾았을 때 쓸 값 (원본 프롬프트)

    Returns:
        str: 이미지 모델에 들어간 프롬프트
    """
    if not history or not prompt_id:
        return fallback
    texts = extract_text_outputs(history, prompt_id)
    if not texts:
        return fallback
    positive_nodes = {
        spec.node for spec in wf.parameters.values()
        if spec.name == "positive" and spec.node
    }
    for spec in wf.parameters.values():
        if spec.input not in ("prompt", "text") or spec.node not in texts:
            continue
        if spec.node in positive_nodes:
            return texts[spec.node]
        break        # 인핸서 노드. positive 여부와 상관없이 그게 답이다
    return next(iter(texts.values()))


@dataclass
class GenerationRequest:
    """생성 요청.

    워크플로와 파라미터를 받는다.
    모델 교체는 워크플로 파라미터로 이루어진다.
    """

    prompt: str
    workflow: Workflow | None = None
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg: float = 7.0
    seed: int = -1
    extra: dict[str, Any] = field(default_factory=dict)
    # False 면 워크플로의 프롬프트 인핸서 노드를 건너뛴다
    enhance_prompt: bool = True
    # 인핸서가 쓰는 로컬 GGUF 파일명.
    # 워크플로에 인핸서 노드가 없을 때 생성 시점에 자동으로 끼워 넣으므로
    # 노드 ID 가 없다. 그래 값을 워크플로가 아니라 여기로 보낸다.
    enhancer_model: str = ""


@dataclass
class GenerationResult:
    """생성 결과."""

    success: bool
    image_path: Path | None = None
    metadata: dict = field(default_factory=dict)
    error: str | None = None
    suggestion: object | None = None
    elapsed_seconds: float = 0.0


class GeurimGyeolEngine:
    """v0.2 엔진.

    GUI 가 동기적으로 호출하는 facade 이다.
    내부적으로 ComfyClient(비동기)를 소유한 이벤트 루프에서 실행한다.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.logger = logging.getLogger("geurim-gyeol.engine")
        self.config = ComfyUIConfig.load(self.root / "config" / "comfyui.json")
        self.client = ComfyClient(self.config, logger=self.logger)
        self.system_info = SystemInfo(online=False, error="확인되지 않음")

        self.workflow_dir = self.root / "workflows"
        self.workflows: list[Workflow] = []
        self.active_workflow: Workflow | None = None

        self.outputs = OutputManager(self.root / "outputs")
        self.sessions = SessionManager(self.root / "sessions")

        # 이 프로그램이 직접 띄운 ComfyUI 프로세스 (자동 실행 시에만 채워짐)
        self._launched_process = None

        # 인핸서 노드 정의 캐시 (ComfyUI 에 물어본 결과).
        # 워크플로에 없는 노드를 직접 만들어 넣을 때만 필요하다.
        self._enhancer_defaults: tuple[str | None, dict, dict] | None = None

        # /object_info 전체 응답에서 뽑은 노드 종류 집합 (가져오기 창이 쓴다).
        # 응답이 2.4MB 라 파일을 몇 개 열 때마다 다시 받으면 낭비가 크다.
        # 방금 커스텀 노드를 설치했을 수 있으니 시간을 둔다(TTL).
        self._node_types_cache: set[str] | None = None
        self._node_types_at: float = 0.0
        # CLIP 로더의 type 선택지. (노드 종류마다 목록이 달라 키로 나눠 캐한다)
        self._input_options_cache: dict[str, tuple[float, list[str] | None]] = {}

        # ComfyUI 통신용 이벤트 루프를 하나만 두고 재사용한다.
        # (GUI 스레드와 QThread 워커가 함께 쓸 수 있으므로 직렬화한다)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.RLock()

    def _run(self, coro):
        """코루틴을 소유 이벤트 루프에서 실행한다.

        asyncio.run 을 쓰면 호출마다 루프가 새로 만들어졌다 닫히므로
        httpx.AsyncClient 가 호출 횟수만큼 새로 생기고, 앞의 것들은
        aclose() 되지 않은 채 GC 에 맡겨진다. 루프를 하나만 두면
        클라이언트가 그대로 재사용된다.

        GUI 스레드와 워커 스레드가 함께 호출할 수 있어 잠금으로
        직렬화한다. 이벤트 루프는 실행되지 않는 한 스레드에 묶이지
        않으므로, 겹치지 않는 한 어느 스레드에서든 돌려도 된다.
        """
        with self._loop_lock:
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
            return self._loop.run_until_complete(coro)

    def _close_loop(self) -> None:
        with self._loop_lock:
            if self._loop is not None and not self._loop.is_closed():
                self._loop.close()
            self._loop = None

    # --- 생명주기 ---------------------------------------------------

    def initialize(self) -> None:
        """워크플로 목록을 읽고 ComfyUI 접속을 확인한다."""
        self.refresh_workflows()
        self._enhancer_defaults = None
        self.refresh_status()

    def shutdown(self) -> None:
        """열린 HTTP 연결을 닫고, 띄운 ComfyUI 가 있으면 종료한다."""
        self.stop_launched()
        try:
            self._run(self.client.close())
        except Exception:
            pass
        self._enhancer_defaults = None
        self._close_loop()

    # --- ComfyUI 상태 -----------------------------------------------

    def refresh_status(self, allow_launch: bool = True) -> SystemInfo:
        """ComfyUI 서버 상태를 갱신한다.

        접속에 실패했고 설정에서 자동 실행이 켜져 있으면
        ComfyUI 를 띄운 뒤 응답이 올라올 때까지 기다린다.

        Args:
            allow_launch: True 면 필요할 때 ComfyUI 를 실행한다.
        """
        try:
            self.system_info = self._run(self.client.get_system_info())
        except Exception as exc:
            self.system_info = SystemInfo(online=False, error=str(exc))

        if not self.system_info.online and allow_launch:
            self.system_info = self._try_launch()

        return self.system_info

    def _try_launch(self) -> SystemInfo:
        """ComfyUI 를 자동 실행하고 응답을 기다린다."""
        if not self.config.auto_launch:
            return self.system_info

        self.logger.info("ComfyUI 접속 실패 — 자동 실행을 시도합니다.")
        proc = self.config.launch(self.logger)
        if proc is None:
            self.logger.warning(
                "ComfyUI 자동 실행에 실패했습니다. config/comfyui.json 의 "
                "launch_command 와 launch_working_dir 를 확인해주세요."
            )
            return SystemInfo(
                online=False,
                error="자동 실행 실패 — 설정의 launch_command 를 확인해주세요",
            )

        # 우리가 띄운 서버만 종료할 수 있도록 기억한다
        self._launched_process = proc

        deadline = time.monotonic() + self.config.launch_wait_seconds
        while time.monotonic() < deadline:
            # 사용자가 중간에 끄면 바로 포기한다
            if proc.poll() is not None:
                self.logger.error(
                    "ComfyUI 가 시작 도중 종료되었습니다 (코드 %s).", proc.returncode
                )
                return SystemInfo(
                    online=False, error="ComfyUI 시작 실패 (프로세스 종료)"
                )
            try:
                info = self._run(self.client.get_system_info())
            except Exception:
                info = SystemInfo(online=False)
            if info.online:
                self.logger.info("ComfyUI 자동 실행 완료")
                return info
            time.sleep(1.5)

        self.logger.error(
            "ComfyUI 가 %d초 안에 응답하지 않았습니다.",
            self.config.launch_wait_seconds,
        )
        return SystemInfo(online=False, error="ComfyUI 응답 시간 초과")

    def stop_launched(self) -> None:
        """자동 실행한 ComfyUI 를 종료한다.

        이 프로그램이 띄운 서버만 종료하며, 사용자가 직접 실행한
        ComfyUI 는 건드리지 않는다.

        VRAM 이 즉시 풀려야 하므로 모델을 먼저 해제하고,
        그래도 안 죽으면 강제로 끝낸다.
        """
        proc = self._launched_process
        if proc is None:
            return
        if proc.poll() is not None:
            self._launched_process = None
            return

        self.logger.info("내가 실행한 ComfyUI 를 종료합니다 (pid=%s).", proc.pid)

        # 1) 모델부터 해제해 VRAM 이 빨리 반환되게 한다
        # (서버가 살아 있을 때만 — 죽었으면 연결 시도가 오래 걸린다)
        if self.system_info.online or self.online:
            try:
                self._run(self.client.post_free())
            except Exception:
                pass

        # 2) 정상 종료 시도
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            # 3) 그래도 살아 있으면 강제 종료 (VRAM 은 프로세스 종료와 함께 풀린다)
            self.logger.warning("ComfyUI 가 정상 종료되지 않아 강제 종료합니다.")
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        finally:
            self._launched_process = None

    @property
    def online(self) -> bool:
        return self.system_info.online

    def status_text(self) -> str:
        return self.system_info.describe()

    # --- 워크플로 ---------------------------------------------------

    def refresh_workflows(self) -> list[Workflow]:
        """workflows/ 폴더를 스캔해 사용 가능한 워크플로를 읽는다.

        parameters 맵이 없는 워크플로는 자동으로 추론해 채운다.
        """
        loaded: list[Workflow] = []
        for path in list_workflows(self.workflow_dir):
            try:
                wf = load_workflow(path)
            except ValueError as exc:
                self.logger.warning("워크플로 로드 실패 (%s): %s", path.name, exc)
                continue
            if wf is None:
                continue
            if not wf.parameters:
                wf.parameters = infer_parameters(wf.prompt)
                if wf.parameters:
                    self.logger.info(
                        "%s: 파라미터 %d개를 자동 인식", wf.name, len(wf.parameters)
                    )
                else:
                    self.logger.warning("%s: 조작 가능한 파라미터 없음", wf.name)
            if not wf.output_node:
                wf.output_node = _guess_output_node(wf.prompt)
            loaded.append(wf)

        self.workflows = loaded
        if self.active_workflow is not None:
            keep = next(
                (w for w in loaded if w.path == self.active_workflow.path), None
            )
            self.active_workflow = keep or (loaded[0] if loaded else None)
        elif loaded:
            self.active_workflow = loaded[0]
        return loaded

    def select_workflow(self, name: str) -> Workflow | None:
        """이름 또는 파일명으로 워크플로를 선택한다."""
        for wf in self.workflows:
            if name in (wf.name, wf.path.stem):
                self.active_workflow = wf
                return wf
        return None

    def model_options(self) -> dict[str, list[str]]:
        """ComfyUI 의 모델 폴더별 목록 (v0.2 §5.3).

        조회할 폴더는 설정(config/comfyui.json 의 model_folders)을 따른다.
        여기서 목록을 박아 두면 설정에 새 폴더를 더해도 반영되지 않는다.
        (프롬프트 인핸서의 LLM 폴더가 그래서 빠졌었다)
        """
        folders = list(self.config.model_folders or _DEFAULT_MODEL_FOLDERS)
        try:
            models = self._run(self.client.get_all_models())
        except Exception as exc:
            self.logger.warning("모델 목록 조회 실패: %s", exc)
            return {}
        return {f: models[f] for f in folders if models.get(f)}

    def sampler_options(self) -> dict[str, list[str]]:
        """KSampler 가 받는 sampler / scheduler 목록."""
        try:
            return self._run(self.client.get_samplers())
        except Exception:
            return {}

    def node_types(self) -> set[str]:
        """ComfyUI 가 아는 노드 타입 이름 집합.

        워크플로가 설치되지 않은 노드를 쓰는지 확인할 때 쓴다.

        /object_info 응답이 노드 1000종을 넘어 2.4MB 다. 가져오기 창에서
        파일을 몇 개 열 때마다 다시 받으면 낭비가 크니 잠깐(TTL) 캐한다.
        방금 커스텀 노드를 설치했을 수 있어 시간만 두고 지킨다.

        Returns:
            set[str]: 노드 타입 이름. 조회 실패면 빈 집합(판단 보류).
        """
        if self._is_fresh(self._node_types_at) and self._node_types_cache is not None:
            return self._node_types_cache
        try:
            info = self._run(self.client.get_object_info())
        except Exception as exc:
            self.logger.warning("노드 목록 조회 실패: %s", exc)
            return set()
        self._node_types_cache = set(info) if isinstance(info, dict) else set()
        self._node_types_at = time.monotonic()
        return self._node_types_cache

    def input_options(self, node_class: str, input_name: str) -> list[str]:
        """노드 종류가 받는 선택지 목록. (CLIP 로더의 type 등)

        노드 종류마다 다르다. DualCLIPLoader 는 CLIPLoader 와 다른
        선택지를 받으므로 한쪽 목록을 다른 쪽에 쓰면 안 된다.

        Returns:
            list[str]: 선택지. 조회에 실패하면 빈 목록.
        """
        key = f"{node_class}.{input_name}"
        stamp, cached = self._input_options_cache.get(key, (0.0, None))
        if cached is not None and self._is_fresh(stamp):
            return list(cached)
        try:
            options = self._run(self.client.get_input_options(
                node_class, input_name
            ))
        except Exception as exc:
            self.logger.warning(
                "%s 의 %s 선택지 조회 실패: %s", node_class, input_name, exc
            )
            return []
        options = list(options)
        self._input_options_cache[key] = (time.monotonic(), options)
        return list(options)

    def clip_types(self) -> list[str]:
        """CLIPLoader 가 받는 type 선택지 (qwen_image, flux, lumina2 …).

        텍스트 인코더가 여러 개인 모델은 type 이 달라져야 한다.
        (Flux 는 flux, Z-Image 는 lumina2, Qwen 은 qwen_image)
        워크플로에 없는 CLIP 타입을 넣으면 ComfyUI 가 거부한다.
        """
        return self.input_options("CLIPLoader", "type")

    @staticmethod
    def _is_fresh(stamp: float) -> bool:
        """캐시가 아직 유효한가."""
        return (time.monotonic() - stamp) < _LIST_CACHE_TTL

    # --- 취소 -------------------------------------------------------

    def cancel(self) -> None:
        """생성 중지를 요청한다."""
        try:
            self._run(self.client.interrupt())
        except Exception:
            pass

    # --- 생성 -------------------------------------------------------

    def build_request(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        cfg: float = 7.0,
        seed: int = -1,
        extra: dict[str, Any] | None = None,
        enhance_prompt: bool = True,
        enhancer_model: str = "",
    ) -> GenerationRequest:
        """현재 선택된 워크플로를 쓰는 생성 요청을 만든다."""
        wf = self.active_workflow
        if wf is None:
            raise RuntimeError(
                "선택된 워크플로가 없습니다. workflows/ 폴더를 확인해주세요."
            )
        return GenerationRequest(
            prompt=prompt,
            workflow=wf,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg=cfg,
            seed=seed,
            extra=dict(extra or {}),
            enhance_prompt=enhance_prompt,
            enhancer_model=enhancer_model,
        )

    def _payload(self, request: GenerationRequest) -> tuple[Workflow, dict]:
        """요청 값을 워크플로에 주입한 ComfyUI API 형식을 만든다."""
        wf = request.workflow
        if wf is None:
            raise RuntimeError("생성 요청에 워크플로가 없습니다.")

        values: dict[str, Any] = {}
        params = wf.parameters

        if "positive" in params:
            values["positive"] = request.prompt
        if "negative" in params and request.negative_prompt:
            values["negative"] = request.negative_prompt
        if "width" in params:
            values["width"] = request.width
        if "height" in params:
            values["height"] = request.height
        if "steps" in params:
            values["steps"] = request.steps
        if "cfg" in params:
            values["cfg"] = request.cfg
        # seed 가 -1 이면 워크플로 기본값을 그대로 쓴다 (ComfyUI 규약)
        if "seed" in params and request.seed is not None and request.seed >= 0:
            values["seed"] = request.seed

        for key, value in request.extra.items():
            if value is not None:
                values[key] = value

        # 워크플로가 받지 않는 입력은 조용히 건너뛴다.
        # (예: Flux 워크플로에 negative 가 없을 수 있다)
        if not values:
            self.logger.warning(
                "%s 워크플로에 주입할 수 있는 입력이 없습니다", wf.name
            )

        # 프롬프트 인핸서 우회 (GUI 의 스위치가 꺼져 있으면)
        payload = wf.apply(values)
        if request.enhance_prompt:
            self._ensure_enhancer(wf, payload, request.enhancer_model)
        else:
            payload = self._bypass_enhancer(payload)
        return wf, payload

    def enhancer_defaults(self) -> tuple[str | None, dict, dict]:
        """설치된 인핸서 노드 종류와 그 입력 기본값을 돌려준다.

        워크플로에 인핸서 노드를 직접 만들어 넣을 때 쓴다.
        매번 조회하면 매번 HTTP 가 되므로 결과를 캐시한다.

        Returns:
            tuple[str | None, dict, dict]:
                (노드 class_type, 필수 입력 기본값, LLM 모델 지정값).
                노드가 하나도 설치돼 있지 않으면 (None, {}, {}).
        """
        if self._enhancer_defaults is not None:
            return self._enhancer_defaults
        found: tuple[str | None, dict, dict] = (None, {}, {})
        if self.online:
            for node_class in _ENHANCER_INJECT_CLASSES:
                defaults = self._run(self.client.get_node_defaults(node_class))
                if not defaults:
                    continue
                # LLM 모델 지정값은 '선택' 입력이므로 object_info 기본값이
                # 아니라 '설치된 것 중 첫 번째' 를 써야 한다.
                model_inputs: dict[str, Any] = {}
                for key in _ENHANCER_MODEL_INPUTS:
                    options = self._run(
                        self.client.get_node_options(node_class, key)
                    )
                    if options:
                        model_inputs[key] = options[0]
                # GGUF 가 실제로 깔려 있으면 로컬 백엔드를 고른다.
                # 안 고르면 노드 기본값(온라인 API)이 들어가는데,
                # 이 프로그램에는 API 키가 없어서 그대로 실패한다.
                if "local_model" in model_inputs and "api_mode" in defaults:
                    modes = self._run(
                        self.client.get_node_options(node_class, "api_mode")
                    )
                    for mode in modes:
                        if _ENHANCER_LOCAL_MODE_MARK in str(mode).lower():
                            defaults = {**defaults, "api_mode": mode}
                            break
                found = (node_class, defaults, model_inputs)
                break
        self._enhancer_defaults = found
        return found

    def enhancer_status(self) -> tuple[bool, str]:
        """인핸서를 쓸 수 있는지와 안 되면 이유를 돌려준다.

        Returns:
            tuple[bool, str]: (가능 여부, 안내 문구)
        """
        node_class, defaults, model_inputs = self.enhancer_defaults()
        if node_class is None:
            return False, (
                "프롬프트 인핸서 노드가 설치돼 있지 않습니다 "
                "(ComfyUI 의 T8 팩이 필요합니다)."
            )
        if not model_inputs.get("local_model"):
            return False, (
                "인핸서용 GGUF 모델이 설치돼 있지 않습니다 "
                "(ComfyUI 모델 폴더에 GGUF 파일이 필요합니다)."
            )
        return True, f"인핸서 사용 가능 ({node_class})"

    def _ensure_enhancer(self, wf: Workflow, payload: dict,
                       enhancer_model: str = "") -> None:
        """인핸서 노드가 없으면 실행 그래프에 직접 추가한다.

        워크플로에 이미 있으면 아무것도 하지 않는다.
        추가하지 못하면 원본 프롬프트로 그대로 생성한다 —
        조용히 LLM 을 돌릴 수는 없으므로, 못 넣는 게 맞아 보인다.

        enhancer_model 은 사용자가 고른 GGUF 파일명이다.
        워크플로에 노드가 없으니 값을 받을 곳이 없으므로 여기서 물려받는다.

        Returns:
            None
        """
        if _find_enhancer_node(payload) is not None:
            return
        target = injection_target(wf)
        if target is None:
            self.logger.warning(
                "%s: 인핸서를 붙일 자리가 없어 원본 프롬프트로 생성합니다 (%s)",
                wf.name, injection_block_reason(wf),
            )
            return
        node_class, defaults, model_inputs = self.enhancer_defaults()
        if node_class is None:
            self.logger.warning(
                "%s: 인핸서 노드가 설치돼 있지 않아 원본 프롬프트로 생성합니다",
                wf.name,
            )
            return
        if enhancer_model:
            # 사용자가 고른 파일만 쓴다. ComfyUI 는 목록에 없는 값을 거부한다.
            model_inputs = {**model_inputs, "local_model": enhancer_model}
        self._inject_enhancer(
            wf, payload, node_class, defaults, model_inputs, *target
        )

    def _inject_enhancer(
        self,
        wf: Workflow,
        payload: dict,
        node_class: str,
        defaults: dict,
        model_inputs: dict,
        node_id: str,
        input_name: str,
    ) -> bool:
        """payload 에 인핸서 노드를 추가해 프롬프트 경로에 끼워 넣는다.

        텍스트 인코더의 문자열 입력을 인핸서로 옮기고, 그 자리를
        인핸서 출력 0번(rewritten_prompt) 링크로 바꾼다.

        Returns:
            bool: 주입에 성공했으면 True
        """
        node = payload.get(node_id) or {}
        original = (node.get("inputs") or {}).get(input_name)
        if not isinstance(original, str) or not original.strip():
            return False

        new_id = _free_node_id(payload)
        inputs = dict(defaults)
        inputs.update(model_inputs)
        inputs["prompt"] = original
        payload[new_id] = {
            "inputs": inputs,
            "class_type": node_class,
            "_meta": {"title": "프롬프트 인핸서 (자동 추가)"},
        }
        node.setdefault("inputs", {})[input_name] = [new_id, 0]
        self.logger.info(
            "%s: 인핸서 %s 를 %s.%s 앞에 자동으로 연결했습니다",
            wf.name, node_class, node_id, input_name,
        )
        return True

    def _bypass_enhancer(self, payload: dict) -> dict:
        """프롬프트 인핸서 노드를 건너뛰도록 payload 를 고친다.

        인핸서 노드(14)의 출력이 TextEncode(4) 로 들어가는 구조라면,
        인핸서를 끄고 사용자가 입력한 프롬프트를 그대로 TextEncode 에 넣는다.

        TextEncode 쪽 링크만 풀면 안 된다. T8ShowText 같은 출력 노드가
        ["14", 0] 을 참조하고 있으면 ComfyUI 는 출력 노드로 도달 가능한
        노드를 실행하므로 LLM 이 여전히 호출된다. 인핸서를 참조하는 모든
        노드의 연결을 끊고 인핸서 노드 자체를 payload 에서 제거해야 한다.

        Returns:
            dict: 고쳐진 payload
        """
        # 1) TextEncode 로 연결된 프롬프트를 원본 값으로 되돌린다.
        enhancer_id: str | None = None
        original_prompt: str | None = None
        for node_id, node in (payload or {}).items():
            inputs = node.get("inputs") or {}
            for input_name in ("prompt", "text", "positive"):
                source = inputs.get(input_name)
                if not (isinstance(source, list) and len(source) == 2):
                    continue
                src_id = source[0]
                src_node = payload.get(src_id) or {}
                if not _is_enhancer(src_node.get("class_type", "")):
                    continue
                # 인핸서 노드 자체의 prompt 값이 사용자 원문이다.
                original = (src_node.get("inputs") or {}).get("prompt")
                if isinstance(original, str):
                    inputs[input_name] = original
                    enhancer_id = src_id
                    original_prompt = original
                    break
            if enhancer_id:
                break

        if not enhancer_id:
            return payload

        # 2) 인핸서를 참조하는 다른 노드(T8ShowText 등)의 연결도 끊는다.
        dangling: list[str] = []
        for node_id, node in payload.items():
            if node_id == enhancer_id:
                continue
            inputs = node.get("inputs") or {}
            for input_name, value in list(inputs.items()):
                if not (isinstance(value, list) and len(value) == 2):
                    continue
                if value[0] != enhancer_id:
                    continue
                # 문자열 입력은 원본 프롬프트로 대체하고, 나머지는 링크 제거.
                if input_name in ("prompt", "text", "string", "positive"):
                    inputs[input_name] = original_prompt
                else:
                    del inputs[input_name]
                dangling.append(f"{node_id}.{input_name}")

        # 3) 인핸서 노드 자체를 제거한다. 그래야 LLM 이 아예 로드되지 않는다.
        payload.pop(enhancer_id, None)

        self.logger.info(
            "프롬프트 인핸서(%s)를 실행 그래프에서 제거했습니다 (끊은 입력: %s)",
            enhancer_id,
            ", ".join(dangling) if dangling else "없음",
        )
        return payload

    def generate(
        self,
        request: GenerationRequest,
        on_progress: Callable[[int, str], None] | None = None,
    ) -> GenerationResult:
        """워크플로를 실행하고 결과 이미지를 저장한다.

        Args:
            request: build_request 로 만든 생성 요청
            on_progress: (percent, message) 진행률 콜백
        """
        started = time.perf_counter()

        # 오프라인이면 실행하지 않는다.
        # refresh_status() 는 예외를 삼키고 online=False 를 담은 상태를
        # 남기므로, 여기서는 오직 온라인 여부만 확인한다.
        if not self.online:
            self.refresh_status()
        if not self.online:
            return GenerationResult(
                success=False,
                error=(
                    f"ComfyUI에 연결할 수 없습니다 "
                    f"({self.config.base_url}) — {self.system_info.error or ''}"
                ),
            )

        try:
            wf, payload = self._payload(request)
        except RuntimeError as exc:
            return GenerationResult(success=False, error=str(exc))

        def _progress(percent: int, message: str) -> None:
            if on_progress:
                on_progress(percent, message)

        def _stage(state: str, message: str) -> None:
            self.logger.info("[%s] %s", state, message)

        try:
            # run_details=True 로 실제 사용된 프롬프트와 prompt_id 를 함께 받는다 (B4)
            images, history, prompt_id = self._run(
                self.client.run(
                    payload,
                    on_progress=_progress,
                    on_stage=_stage,
                    timeout=self.config.timeout_seconds,
                    run_details=True,
                )
            )
        except ComfyUIError as exc:
            return GenerationResult(success=False, error=str(exc))
        except Exception as exc:
            return GenerationResult(
                success=False,
                error=f"생성 실패: {type(exc).__name__}: {exc}",
            )

        elapsed = time.perf_counter() - started
        if not images:
            return GenerationResult(
                success=False,
                error="ComfyUI가 이미지를 반환하지 않았습니다.",
                elapsed_seconds=elapsed,
            )

        return self._save(request, wf, payload, images, elapsed, history, prompt_id)

    def _applied_values(self, wf: Workflow, payload: dict) -> dict[str, Any]:
        """실제로 전송된 payload 에서 메타데이터 값을 읽는다.

        parameters 맵의 키 이름은 워크플로마다 다르므로
        spec.input (ComfyUI 입력 이름) 을 기준으로 찾는다.
        """
        values: dict[str, Any] = {
            "seed": 0, "prompt": "", "negative": "",
            "width": 0, "height": 0, "steps": 0, "cfg": 0.0,
            "sampler": "", "scheduler": "",
        }
        fields = {
            "seed": "seed", "prompt": "prompt", "text": "prompt",
            "negative_prompt": "negative",
            "width": "width", "height": "height", "steps": "steps",
            "cfg": "cfg", "sampler_name": "sampler", "scheduler": "scheduler",
        }
        for spec in wf.parameters.values():
            field = fields.get(spec.input)
            if field is None:
                continue
            node = payload.get(spec.node) or {}
            raw = (node.get("inputs") or {}).get(spec.input)
            # 링크로 연결된 값은 실제 값이 아니라 참조이므로 건너뛴다
            if isinstance(raw, list):
                continue
            if raw is not None:
                values[field] = raw
        return values

    def _save(
        self,
        request: GenerationRequest,
        wf: Workflow,
        payload: dict,
        images: list[dict],
        elapsed: float,
        history: dict | None = None,
        prompt_id: str = "",
    ) -> GenerationResult:
        """ComfyUI 결과를 outputs/ 와 sessions/ 에 저장한다.

        metadata 는 요청값이 아니라 실제 전송된 payload 에서 읽는다.
        (seed 를 -1 로 보내면 ComfyUI 가 임의 배정하고, 워크플로 기본값이
        그대로 사용될 수도 있으므로 요청과 실제 값이 다를 수 있다)
        """
        from io import BytesIO

        from PIL import Image

        try:
            blobs = []
            for item in images:
                blobs.append(
                    self._run(
                        self.client.get_image(
                            item.get("filename", ""), item.get("subfolder", "")
                        )
                    )
                )
        except Exception as exc:
            return GenerationResult(
                success=False, error=f"결과 이미지 다운로드 실패: {exc}"
            )

        # 실제 전송된 값에서 메타데이터를 읽는다
        applied = self._applied_values(wf, payload)

        # 프롬프트를 다듬어 준 LLM 모델명.
        # 인핸서 스위치를 끈 경우 노드가 payload 에 없어서 None 이 된다.
        llm_model = _enhancer_model(payload)

        # 인핸서가 실제로 만든 프롬프트를 history 에서 읽는다 (B4).
        # 인핸서 노드의 text 출력이 곧 이미지 모델에 들어간 값이다.
        original_prompt = applied["prompt"] or request.prompt
        enhanced_prompt = _pick_enhanced_prompt(
            wf, history, prompt_id, original_prompt,
        )

        metadata = OutputMetadata(
            seed=applied["seed"],
            model=wf.name,
            prompt=enhanced_prompt,
            original_prompt=original_prompt,
            negative_prompt=applied["negative"],
            width=applied["width"],
            height=applied["height"],
            steps=applied["steps"],
            cfg=applied["cfg"],
            sampler=applied["sampler"],
            scheduler=applied["scheduler"],
            elapsed_seconds=round(elapsed, 2),
            llm_model=llm_model,
        )

        # 1) outputs/ 에 저장
        images_saved: list[Path] = []
        for blob in blobs:
            try:
                image = Image.open(BytesIO(blob))
                image.load()
            except Exception as exc:
                return GenerationResult(success=False, error=f"이미지 해석 실패: {exc}")
            png_path, _ = self.outputs.save_output(image, metadata)
            images_saved.append(png_path)

        if not images_saved:
            return GenerationResult(success=False, error="저장할 이미지가 없습니다.")

        # 2) sessions/ 에 기록
        try:
            session_meta = SessionMetadata(
                original_prompt=original_prompt,
                enhanced_prompt=enhanced_prompt,
                negative_prompt=applied["negative"],
                llm_model=llm_model,
                image_model=wf.name,
                seed=applied["seed"],
                width=applied["width"],
                height=applied["height"],
                steps=applied["steps"],
                cfg=applied["cfg"],
                sampler=applied["sampler"],
                scheduler=applied["scheduler"],
                generation_time=round(elapsed, 2),
                images=[],
            )
            session_dir = self.sessions.create_session(session_meta)
            for index, png_path in enumerate(images_saved, start=1):
                self.sessions.add_image_to_session(
                    session_dir, session_meta, png_path, index
                )
        except Exception as exc:
            self.logger.warning("세션 기록 실패: %s", exc)

        return GenerationResult(
            success=True,
            image_path=images_saved[0],
            metadata=metadata.to_dict(),
            elapsed_seconds=elapsed,
        )


def _guess_output_node(prompt: dict) -> str:
    """이미지를 남기는 출력 노드를 찾는다.

    SaveImage > PreviewImage 순으로, 없으면 빈 문자열을 돌려준다.
    """
    for wanted in _OUTPUT_NODES:
        for node_id, node in prompt.items():
            if node.get("class_type") == wanted:
                return str(node_id)
    return ""
