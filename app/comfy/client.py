"""ComfyUI HTTP/WebSocket 클라이언트 (v0.2 §4).

그림결과 ComfyUI 사이의 모든 통신을 담당한다.
이 프로그램에서 유일하게 ComfyUI에 직접 접근하는 모듈이다.

사용 API (v0.2 §4.2):
    GET  /system_stats        서버·VRAM 정보
    GET  /object_info         노드 정의
    GET  /models              폴더 목록
    GET  /models/{folder}     폴더의 모델 목록
    POST /prompt              워크플로 제출
    WS   /ws?clientId=        진행률 실시간 수신
    GET  /history/{id}        실행 결과
    GET  /view                결과 이미지
    POST /interrupt           실행 중단
    POST /free                모델 언로드
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from .config import ComfyUIConfig


class ComfyUIError(RuntimeError):
    """ComfyUI 호출 실패."""


@dataclass
class SystemInfo:
    """ComfyUI 서버 상태 (v0.2 §11 연결)."""

    online: bool
    comfyui_version: str = ""
    python_version: str = ""
    torch_version: str = ""
    os_name: str = ""
    ram_total_gb: float | None = None
    ram_free_gb: float | None = None
    device_name: str = ""
    device_type: str = ""
    vram_total_gb: float | None = None
    vram_free_gb: float | None = None
    error: str | None = None

    @property
    def vram_used_gb(self) -> float | None:
        if self.vram_total_gb is None or self.vram_free_gb is None:
            return None
        return max(0.0, self.vram_total_gb - self.vram_free_gb)

    @property
    def vram_percent(self) -> float:
        if not self.vram_total_gb:
            return 0.0
        return (self.vram_used_gb or 0.0) / self.vram_total_gb * 100

    def describe(self) -> str:
        if not self.online:
            return f"ComfyUI 접속 실패 — {self.error or '응답 없음'}"
        device = self.device_name or self.device_type or "CPU"
        # vram_total_gb 이 있어도 vram_free_gb 이 None 이면 vram_used_gb 도
        # None 이다. 이 값을 그대로 :.1f 로 포맷하면 TypeError 가 난다.
        used = self.vram_used_gb
        if self.vram_total_gb and used is not None:
            return (
                f"ComfyUI {self.comfyui_version} · {device} · "
                f"VRAM {used:.1f}/{self.vram_total_gb:.1f}GB"
            )
        return f"ComfyUI {self.comfyui_version} · {device} · VRAM 없음"


class ComfyClient:
    """ComfyUI API 클라이언트 (v0.2 §4).

    이 프로그램에서 유일하게 ComfyUI에 직접 접근하는 모듈이다.
    """

    def __init__(self, config: ComfyUIConfig | None = None, logger=None):
        self.config = config or ComfyUIConfig()
        self.logger = logger
        self.client_id = str(uuid.uuid4())
        self._http: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _ensure_http(self) -> httpx.AsyncClient:
        """지연 생성 HTTP 클라이언트.

        이벤트 루프가 바뀌면 반드시 새 클라이언트를 만든다.
        asyncio.run 은 호출마다 루프를 새로 만들고 닫으므로, 이전 루프에
        묶인 클라이언트를 재사용하면 "Event loop is closed" 로 실패한다.
        (GUI 엔진이 sync facade 로 asyncio.run 을 반복 호출할 때 발생)
        """
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None

        if (
            self._http is None
            or self._http.is_closed
            or self._loop is not current
        ):
            self._http = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.connect_timeout_seconds,
            )
            self._loop = current
        return self._http

    async def close(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
        self._http = None
        self._loop = None

    async def _get(self, path: str, timeout: float | None = None):
        http = self._ensure_http()
        try:
            response = await http.get(
                path, timeout=timeout or self.config.connect_timeout_seconds
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise ComfyUIError(
                f"GET {path} 실패: HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ComfyUIError(
                f"ComfyUI 접속 실패 ({self.config.base_url}): {exc}"
            ) from exc

    async def _post(self, path: str, payload: dict | None = None, timeout: float | None = None):
        """POST 요청을 보내고 응답을 반환한다."""
        http = self._ensure_http()
        try:
            response = await http.post(
                path,
                json=payload or {},
                timeout=timeout or self.config.connect_timeout_seconds,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            raise ComfyUIError(
                f"POST {path} 실패: HTTP {exc.response.status_code} {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"ComfyUI 요청 실패: {exc}") from exc

    # --- 조회 API (v0.2 §4.2) -------------------------------------

    async def get_system_info(self) -> SystemInfo:
        """GET /system_stats — 서버·VRAM 정보."""
        try:
            response = await self._get("/system_stats")
            data = response.json()
        except ComfyUIError as exc:
            return SystemInfo(online=False, error=str(exc))

        system = data.get("system", {}) or {}
        devices = data.get("devices", []) or []
        device = devices[0] if devices else {}

        return SystemInfo(
            online=True,
            comfyui_version=system.get("comfyui_version", ""),
            python_version=system.get("python_version", ""),
            torch_version=system.get("pytorch_version", ""),
            os_name=system.get("os", ""),
            ram_total_gb=_to_gb(system.get("ram_total")),
            ram_free_gb=_to_gb(system.get("ram_free")),
            device_name=device.get("name", ""),
            device_type=device.get("type", ""),
            vram_total_gb=_to_gb(device.get("vram_total")),
            vram_free_gb=_to_gb(device.get("vram_free")),
        )

    async def get_models(self, folder: str) -> list[str]:
        """GET /models/{folder} — 해당 폴더의 모델 목록."""
        try:
            response = await self._get(f"/models/{folder}")
            data = response.json()
        except ComfyUIError:
            return []
        return data if isinstance(data, list) else []

    async def get_model_folders(self) -> list[str]:
        """GET /models — 사용 가능한 모델 폴더 목록."""
        try:
            response = await self._get("/models")
            data = response.json()
        except ComfyUIError:
            return []
        return data if isinstance(data, list) else []

    async def get_all_models(self) -> dict[str, list[str]]:
        """설정에 지정된 모든 폴더의 모델을 한 번에 조회."""
        result: dict[str, list[str]] = {}
        for folder in self.config.model_folders:
            models = await self.get_models(folder)
            if models:
                result[folder] = models
        return result

    async def get_object_info(self, node_class: str | None = None) -> dict:
        """GET /object_info — 노드 정의."""
        path = f"/object_info/{node_class}" if node_class else "/object_info"
        try:
            response = await self._get(path, timeout=30)
            return response.json()
        except ComfyUIError:
            return {}

    async def get_node_defaults(self, node_class: str) -> dict[str, Any]:
        """노드의 필수 입력 기본값을 전부 읽는다.

        워크플로에 없는 노드를 프로그램이 직접 만들어 넣을 때 쓴다.
        필수 입력을 비워 넣으면 ComfyUI 가 그 노드를 거부하므로
        object_info 에 적힌 기본값을 그대로 채워야 한다.

        COMBO 는 '선언된 기본값' 이 아니라 '설치된 선택지' 를 쓴다.
        선언 기본값이 목록에 없으면(모델을 안 깐 경우) ComfyUI 가 실패한다.

        Returns:
            dict[str, Any]: 입력 이름 -> 넣을 값. 노드가 없으면 빈 dict.
        """
        info = await self.get_object_info(node_class)
        node = info.get(node_class) if isinstance(info, dict) else None
        if not isinstance(node, dict):
            return {}
        required = ((node.get("input") or {}).get("required") or {})
        defaults: dict[str, Any] = {}
        for name, spec in required.items():
            value = _input_default(spec)
            if value is not None:
                defaults[name] = value
        return defaults

    async def get_node_options(self, node_class: str, input_name: str) -> list[str]:
        """노드의 선택지 목록 (설치된 값만 들어있다).

        자유 입력(STRING)인 입력은 선택지가 없으므로 빈 리스트를 돌려준다.
        """
        info = await self.get_object_info(node_class)
        node = info.get(node_class) if isinstance(info, dict) else None
        if not isinstance(node, dict):
            return []
        inputs = node.get("input") or {}
        required = inputs.get("required") or {}
        optional = inputs.get("optional") or {}
        spec = required.get(input_name) or optional.get(input_name)
        return _input_options(spec)

    async def get_queue(self) -> dict:
        """GET /queue — 대기열 상태."""
        try:
            return (await self._get("/queue")).json()
        except ComfyUIError:
            return {"queue_running": [], "queue_pending": []}

    async def post_free(self) -> None:
        """POST /free — 로드된 모델을 내리고 VRAM 을 반환한다.

        종료 직전에 호출하면 프로세스를 끝까지 살려두면서도
        GPU 메모리를 빠르게 확보할 수 있다.
        """
        try:
            await self._post(
                "/free",
                {"unload_models": True, "free_memory": True},
                timeout=15,
            )
        except ComfyUIError:
            pass

    async def get_samplers(self) -> dict[str, list[str]]:
        """KSampler 노드 정의에서 sampler/scheduler 목록을 뽑는다.

        ComfyUI 0.3x 는 선택지를 input.required 에 두중 구조로 넣는다.
            input.required.sampler_name = [["euler", "dpmpp_2m", ...]]
        구버전은 dict 안에 combo_options 로 주어지므로 둘 다 처리한다.
        """
        info = await self.get_object_info("KSampler")
        result = {"sampler": [], "scheduler": []}
        node = info.get("KSampler", {}) if isinstance(info, dict) else {}
        inputs = node.get("input", {}) or {}
        # 신버전: {"required": {...}, "optional": {...}}
        if isinstance(inputs.get("required"), dict):
            inputs = {**inputs.get("required", {}), **inputs.get("optional", {})}

        for field, key in (("sampler_name", "sampler"), ("scheduler", "scheduler")):
            result[key] = _extract_options(inputs.get(field))
        return result

    async def get_input_options(
        self, node_class: str, input_name: str
    ) -> list[str]:
        """노드 하나가 받는 선택지 목록 (열거형 입력).

        노드 하나만 조회한다. /object_info 전체는 노드 1000종이 넘어
        2MB 라 0.6KB 로 줄일 수 있다.
        (실측: 전체 87ms/2.4MB → 한 종류 0.6ms/1.2KB)

        Returns:
            list[str]: 선택지. 해당 입력이 없거나 열거형이 아니면 빈 목록.
        """
        info = await self.get_object_info(node_class)
        node = info.get(node_class) if isinstance(info, dict) else None
        if not isinstance(node, dict):
            return []
        required = (node.get("input") or {}).get("required") or {}
        return _input_options(required.get(input_name))

    async def get_clip_types(self) -> list[str]:
        """CLIPLoader 의 type 입력 선택지 (qwen_image, flux, lumina2 …).

        CLIPLoader 만 읽는다. CLIP 로더는 여럿이고 type 선택지가 서로
        다르므로 나머지는 get_input_options 로 노드 종류를 따로 읽는다.
        """
        return await self.get_input_options("CLIPLoader", "type")

    # --- 실행 API (v0.2 §4.2, §4.3) -----------------------------

    async def queue_prompt(self, workflow: dict) -> str:
        """POST /prompt — 워크플로 제출 후 prompt_id 반환."""
        payload = {"prompt": workflow, "client_id": self.client_id}
        response = await self._post("/prompt", payload, timeout=30)
        data = response.json()

        node_errors = data.get("node_errors") or {}
        if node_errors:
            raise ComfyUIError(f"워크플로 오류: {json.dumps(node_errors, ensure_ascii=False)[:400]}")

        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"prompt_id를 받지 못했습니다: {data}")
        return prompt_id

    async def get_history(self, prompt_id: str) -> dict:
        """GET /history/{prompt_id} — 실행 결과."""
        try:
            return (await self._get(f"/history/{prompt_id}", timeout=30)).json()
        except ComfyUIError:
            return {}

    async def get_image(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        """GET /view — 결과 이미지 바이트."""
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        http = self._ensure_http()
        try:
            response = await http.get("/view", params=params, timeout=60)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            raise ComfyUIError(f"이미지 다운로드 실패: {exc}") from exc

    async def interrupt(self) -> None:
        """POST /interrupt — 실행 중단 (v0.2 §6).

        ComfyUI 는 이 신호를 '노드 경계'에서만 본다. 한 노드가 오래
        걸리면(LLM 프롬프트 정리 등) 다음 경계까지 기다려야 하므로
        사용자에게는 "중지됨"이 아니라 "중지 중..." 으로 보여야 한다.
        """
        try:
            await self._post("/interrupt", {}, timeout=10)
        except ComfyUIError:
            pass

    def interrupt_now(self, timeout: float = 5.0) -> bool:
        """중단을 **생성 스레드와 무관하게** 즉시 전송한다 (동기).

        왜 별도 경로가 필요한가:
        생성 중이면 엔진의 _loop_lock 을 생성 스레드가 쥐고 있다.
        기존 cancel() 은 그 잠금을 얻으려고 기다렸다가, 전송하기 전에
        생성이 끝나버려 /interrupt 가 한 번도 안 나갔다.
        여기서는 잠금을 전혀 쓰지 않고, 이 호출 자체가 만든 짧은 수명의
        HTTP 클라이언트로 바로 보낸다. 호출자는 곧바로 반환한다.

        Args:
            timeout: ComfyUI 응답 대기 초. 실패해도 예외를 던지지 않는다.

        Returns:
            bool: 중단 요청이 서버에 도착했으면 True.
        """
        try:
            with httpx.Client(
                base_url=self.config.base_url,
                timeout=timeout,
            ) as http:
                response = http.post("/interrupt", json={})
                return response.status_code < 400
        except Exception:
            return False

    def clear_queue_now(self, timeout: float = 5.0) -> bool:
        """POST /queue {"clear": true} — 대기 중(미시작) 작업만 지운다.

        /interrupt 는 '지금 실행 중인' 것만 멈춘다. 그 뒤에 줄 선
        작업은 계속 돌아가므로 그것도 함께 비워야 중지가 완전히 된다.
        """
        try:
            with httpx.Client(
                base_url=self.config.base_url,
                timeout=timeout,
            ) as http:
                response = http.post("/queue", json={"clear": True})
                return response.status_code < 400
        except Exception:
            return False

    # --- WebSocket 진행률 (v0.2 §4.4, §6) -----------------------

    async def run(
        self,
        workflow: dict,
        on_progress: Callable[[int, str], None] | None = None,
        on_stage: Callable[[str, str], None] | None = None,
        timeout: float | None = None,
        run_details: bool = False,
    ) -> list[dict] | tuple[list[dict], dict, str]:
        """워크플로 실행 → 완료까지 대기 → 결과 이미지 목록 반환.

        Args:
            workflow: ComfyUI API 형식 워크플로
            on_progress: (percent, message) 진행률 콜백
            on_stage: (state, message) 단계 변경 콜백
                state ∈ queued|starting|encoding|sampling|decoding|saving
            timeout: 대기 제한(초). None 이면 설정값 사용
            run_details: True 이면 (images, history, prompt_id) 를 반환한다.
                인핸서가 실제로 만든 프롬프트를 읽는 데 필요하다 (B4).

        Returns:
            [{filename, subfolder, type}, ...] /view 로 받을 수 있는 목록.
            run_details=True 면 (위 목록, history dict, prompt_id) 튜플.
        """
        import websockets

        limit = timeout or self.config.timeout_seconds
        if on_stage:
            on_stage("queued", "ComfyUI에 제출합니다")

        # WebSocket 을 먼저 연다. POST 를 먼저 하면 실행이 빠른 워크플로에서
        # "executing + node=null" 완료 신호가 연결 전에 지나가,
        # 실제로 끝난 작업이 timeout_seconds 만큼 멈춘 뒤 타임아웃으로
        # 오탐되는 문제가 있었다.
        last_error: str | None = None
        completed = False
        prompt_id: str | None = None

        try:
            async with websockets.connect(
                f"{self.config.ws_url}?clientId={self.client_id}",
                open_timeout=self.config.connect_timeout_seconds,
                max_size=16 * 1024 * 1024,
            ) as ws:
                prompt_id = await self.queue_prompt(workflow)

                progress_pct = 5
                if on_progress:
                    on_progress(progress_pct, "ComfyUI 제출 완료")
                if on_stage:
                    on_stage("starting", "ComfyUI 실행 시작")

                deadline = asyncio.get_event_loop().time() + limit

                while not completed:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        await self.interrupt()
                        raise ComfyUIError(f"실행 시간이 {limit:.0f}초를 초과했습니다")

                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 10))
                    except asyncio.TimeoutError:
                        continue

                    message = json.loads(raw)
                    msg_type = message.get("type")
                    data = message.get("data", {}) or {}

                    # 같은 ComfyUI 를 다른 프로그램이 쓰는 중일 수 있으므로
                    # 내 prompt_id 의 이벤트만 처리한다.
                    # (status/queue 는 대상 지정이 없어 통과시킨다)
                    if msg_type not in ("status", "queue"):
                        event_prompt_id = data.get("prompt_id")
                        if prompt_id and event_prompt_id and event_prompt_id != prompt_id:
                            continue

                    if msg_type == "progress":
                        value = data.get("value") or 0
                        maximum = data.get("max") or 0
                        if maximum:
                            percent = 10 + int((value / maximum) * 80)
                            progress_pct = max(progress_pct, min(percent, 90))
                            if on_progress:
                                on_progress(progress_pct, f"생성 중... {int(value)}/{int(maximum)}")
                            if on_stage:
                                on_stage("sampling", "샘플링")

                    elif msg_type == "execution_start":
                        if on_stage:
                            on_stage("starting", "ComfyUI 실행 중")

                    elif msg_type == "executing":
                        if data.get("node") is None:
                            completed = True

                    elif msg_type == "executed":
                        node = data.get("node")
                        if node and on_stage:
                            on_stage("decoding", "노드 실행 완료")

                    elif msg_type == "execution_error":
                        last_error = (
                            data.get("exception_message")
                            or data.get("node_type")
                            or "ComfyUI 실행 오류"
                        )
                        completed = True

                    elif msg_type == "execution_interrupted":
                        last_error = "사용자가 실행을 중단했습니다"
                        completed = True

                if last_error:
                    raise ComfyUIError(last_error)

                # 완료 후 결과 조회
                if on_stage:
                    on_stage("saving", "결과를 가져옵니다")
                history = await self.get_history(prompt_id)
                images = _extract_images(history, prompt_id)
                if on_progress:
                    on_progress(100, "완료")
                return (images, history, prompt_id) if run_details else images

        except ComfyUIError:
            raise
        except Exception as exc:
            if "ConnectionClosed" in type(exc).__name__:
                # 소켓이 닫혔어도 결과가 있으면 성공으로 본다
                history = await self.get_history(prompt_id)
                images = _extract_images(history, prompt_id)
                if images:
                    if on_progress:
                        on_progress(100, "완료")
                    return (images, history, prompt_id) if run_details else images
                raise ComfyUIError(f"ComfyUI 연결이 끊어졌습니다: {exc}") from exc
            raise ComfyUIError(f"ComfyUI 통신 오류: {exc}") from exc


def extract_text_outputs(history: dict, prompt_id: str) -> dict[str, str]:
    """history 응답에서 노드별 텍스트 출력을 뽑는다.

    T8ShowText 같은 노드는 실행 후 history 의 outputs 에
    {"text": ["..."]} 형태로 결과를 남긴다. 프롬프트 인핸서를 켜고
    생성했을 때 "실제로 이미지 모델에 들어간 프롬프트" 는
    인핸서 노드의 이 출력이다 (B4).

    Returns:
        {node_id: 텍스트} — 텍스트 출력이 없으면 빈 dict
    """
    entry = history.get(prompt_id) or history.get(prompt_id.replace("-", "")) or {}
    outputs = entry.get("outputs") or {}
    texts: dict[str, str] = {}
    for node_id, node_output in outputs.items():
        if not isinstance(node_output, dict):
            continue
        for key in ("text", "text_g", "string", "prompt"):
            value = node_output.get(key)
            # ComfyUI 의 custom node 는 텍스트를 ["값"] 리스트로 준다.
            if isinstance(value, list) and value and isinstance(value[0], str):
                value = value[0]
            if isinstance(value, str) and value.strip():
                texts[str(node_id)] = value
                break
    return texts


def _to_gb(value) -> float | None:
    """바이트 값을 GB로 변환."""
    if value is None:
        return None
    return round(value / (1024**3), 2)


def _extract_options(spec) -> list[str]:
    """object_info 의 선택지 값을 뽑아낸다 (버전별 구조 대응).

    - 신버전: [["euler", "dpmpp_2m", ...]]  (이중 리스트)
    - 구버전: {"combo_options": [...]} 또는 {"options": [...]}
    - 리스트: ["a", "b"]
    """
    if spec is None:
        return []
    if isinstance(spec, list):
        # [["a", "b"]] → ["a", "b"], ["a", "b"] → ["a", "b"]
        if spec and isinstance(spec[0], list):
            return [str(x) for x in spec[0]]
        return [str(x) for x in spec]
    if isinstance(spec, dict):
        for key in ("combo_options", "options", "values"):
            if key in spec:
                return _extract_options(spec[key])
    return []


def _input_options(spec) -> list[str]:
    """object_info 의 입력 정의에서 '선택지 목록' 만 뽑는다.

    ComfyUI 의 정의 형태가 두 가지라 _extract_options 를 그대로 쓰면 안 된다.
    - [["euler", ...], {...}]  (KSampler) → 첫 항목이 리스트
    - ["COMBO", {"options": [...]}]  (T8 팩) → 첫 항목이 타입 문자열
    두 번째 형태에 _extract_options 를 쓰면 ["COMBO", "{...}"] 처럼
    타입 이름과 딕셔너리를 문자열로 돌려준다. 그래서 COMBO 만 받아들이고,
    STRING 같은 자유 입력은 빈 리스트로 처리한다.
    """
    if not isinstance(spec, list) or not spec:
        return []
    kind = spec[0] if isinstance(spec[0], str) else None
    if kind is not None:
        if kind != "COMBO":
            return []
        return _extract_options(spec[1] if len(spec) > 1 else None)
    return _extract_options(spec)


def _input_kind(spec) -> str:
    """입력 정의 한 개에서 종류 이름만 뽑는다. 모르면 빈 문자열.

    형태가 두 가지다.
    - ["COMBO", {...}] / ["INT", {...}]   → 첫 항목이 종류 이름
    - [["a", "b"], {...}]                → 선택지 목록이 붙은 입력(COMBO)
    """
    if not isinstance(spec, list) or not spec:
        return ""
    first = spec[0]
    if isinstance(first, str):
        return first.upper()
    return "COMBO" if first else ""


def node_input_kinds(node: dict) -> dict[str, str]:
    """노드 정의에서 입력 이름 -> 종류를 모두 뽑는다. (COMBO/INT/… )

    커스텀 노드의 선택형 입력을 찾을 때 쓴다. object_info 정의 모양을
    아는 곳은 여기뿐이라 해석도 여기서 한다. (엔진은 이 함수만 쓴다)

    Args:
        node: /object_info 응답의 한 노드 (정의 dict)

    Returns:
        dict[str, str]: {입력 이름: 종류}. 정의가 없으면 빈 dict.
    """
    inputs = (node.get("input") or {}) if isinstance(node, dict) else {}
    kinds: dict[str, str] = {}
    for group in ("required", "optional"):
        for name, spec in (inputs.get(group) or {}).items():
            kind = _input_kind(spec)
            if kind:
                kinds[str(name)] = kind
    return kinds


def _input_default(spec):
    """object_info 의 입력 정의에서 넣을 기본값 하나를 뽑는다.

    - COMBO: 설치된 선택지(options) 중 선언된 기본값, 없으면 첫 번째
    - STRING/INT/FLOAT/BOOLEAN: 선언된 default
    값을 얻을 수 없으면 None 을 돌려준다 (호출자가 그 입력은 빼게 된다).
    """
    if not isinstance(spec, list) or not spec:
        return None
    kind = spec[0] if isinstance(spec[0], str) else ""
    options = _extract_options(spec[1] if len(spec) > 1 else None)
    declared = spec[1].get("default") if (
        len(spec) > 1 and isinstance(spec[1], dict)
    ) else None

    if kind == "COMBO" or (not kind and options):
        if isinstance(declared, str) and declared in options:
            return declared
        return options[0] if options else None
    return declared


def _extract_images(history: dict, prompt_id: str) -> list[dict]:
    """history 응답에서 /view 로 받을 수 있는 이미지 목록을 뽑는다."""
    entry = history.get(prompt_id) or history.get(prompt_id.replace("-", "")) or {}
    outputs = entry.get("outputs", {}) or {}
    images: list[dict] = []

    for node_output in outputs.values():
        image_list = (node_output or {}).get("images", []) or []
        for image in image_list:
            filename = image.get("filename")
            if not filename:
                continue
            images.append(
                {
                    "filename": filename,
                    "subfolder": image.get("subfolder", ""),
                    "type": image.get("type", "output"),
                }
            )
    return images
