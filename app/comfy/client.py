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
from pathlib import Path
from typing import Callable

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
        if self.vram_total_gb:
            return (
                f"ComfyUI {self.comfyui_version} · {device} · "
                f"VRAM {self.vram_used_gb:.1f}/{self.vram_total_gb:.1f}GB"
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

    async def get_queue(self) -> dict:
        """GET /queue — 대기열 상태."""
        try:
            return (await self._get("/queue")).json()
        except ComfyUIError:
            return {"queue_running": [], "queue_pending": []}

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
        """POST /interrupt — 실행 중단 (v0.2 §6)."""
        try:
            await self._post("/interrupt", {}, timeout=10)
        except ComfyUIError:
            pass



    # --- WebSocket 진행률 (v0.2 §4.4, §6) -----------------------

    async def run(
        self,
        workflow: dict,
        on_progress: Callable[[int, str], None] | None = None,
        on_stage: Callable[[str, str], None] | None = None,
        timeout: float | None = None,
    ) -> list[dict]:
        """워크플로 실행 → 완료까지 대기 → 결과 이미지 목록 반환.

        Args:
            workflow: ComfyUI API 형식 워크플로
            on_progress: (percent, message) 진행률 콜백
            on_stage: (state, message) 단계 변경 콜백
                state ∈ queued|starting|encoding|sampling|decoding|saving
            timeout: 대기 제한(초). None 이면 설정값 사용

        Returns:
            [{filename, subfolder, type}, ...] /view 로 받을 수 있는 목록
        """
        import websockets

        limit = timeout or self.config.timeout_seconds
        if on_stage:
            on_stage("queued", "ComfyUI에 제출합니다")
        prompt_id = await self.queue_prompt(workflow)

        progress_pct = 5
        if on_progress:
            on_progress(progress_pct, "ComfyUI 제출 완료")
        if on_stage:
            on_stage("starting", "ComfyUI 실행 시작")

        last_error: str | None = None
        completed = False

        try:
            async with websockets.connect(
                f"{self.config.ws_url}?clientId={self.client_id}",
                open_timeout=self.config.connect_timeout_seconds,
                max_size=16 * 1024 * 1024,
            ) as ws:
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
                return images

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
                    return images
                raise ComfyUIError(f"ComfyUI 연결이 끊어졌습니다: {exc}") from exc
            raise ComfyUIError(f"ComfyUI 통신 오류: {exc}") from exc


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
    async def free_memory(self, unload_models: bool = True) -> None:
        """POST /free — 모델 언로드로 메모리 정리 (v0.2 §6)."""
        try:
            await self._post(
                "/free",
                {"unload_models": unload_models, "free_memory": True},
                timeout=30,
            )
        except ComfyUIError:
            pass

    async def is_busy(self) -> bool:
        """현재 실행 중인지 확인."""
        queue = await self.get_queue()
        return bool(queue.get("queue_running"))
