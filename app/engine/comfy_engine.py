"""ComfyUI 기반 GeurimGyeolEngine v0.2 (v0.2 §5).

네이티브 추론(torch/diffusers)을 직접 수행하지 않는다.
ComfyUI가 모델 실행·VRAM 관리·양자화를 전부 담당하고,
이 클래스는 GUI에 필요한 동기 인터페이스를 제공하며
워크플로 선택 → 값 주입 → 실행 → 결과 저장을 중재한다.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..comfy import ComfyClient, ComfyUIConfig, ComfyUIError, SystemInfo
from ..comfy.workflow import Workflow, infer_parameters, list_workflows, load_workflow
from .output.manager import OutputManager, OutputMetadata
from .session.manager import SessionManager, SessionMetadata

# 이미지를 남기는 출력 노드 (앞에서부터 우선)
_OUTPUT_NODES = ("SaveImage", "PreviewImage", "SaveAnimatedWEBP", "SaveAnimatedPNG")


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
    내부적으로 ComfyClient(비동기)를 asyncio.run 으로 감싼다.
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

    # --- 생명주기 ---------------------------------------------------

    def initialize(self) -> None:
        """워크플로 목록을 읽고 ComfyUI 접속을 확인한다."""
        self.refresh_workflows()
        self.refresh_status()

    def shutdown(self) -> None:
        """열린 HTTP 연결을 닫고, 띄운 ComfyUI 가 있으면 종료한다."""
        self.stop_launched()
        try:
            asyncio.run(self.client.close())
        except Exception:
            pass

    # --- ComfyUI 상태 -----------------------------------------------

    def refresh_status(self, allow_launch: bool = True) -> SystemInfo:
        """ComfyUI 서버 상태를 갱신한다.

        접속에 실패했고 설정에서 자동 실행이 켜져 있으면
        ComfyUI 를 띄운 뒤 응답이 올라올 때까지 기다린다.

        Args:
            allow_launch: True 면 필요할 때 ComfyUI 를 실행한다.
        """
        try:
            self.system_info = asyncio.run(self.client.get_system_info())
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
                info = asyncio.run(self.client.get_system_info())
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
        """
        proc = self._launched_process
        if proc is None or proc.poll() is not None:
            self._launched_process = None
            return
        self.logger.info("내가 실행한 ComfyUI 를 종료합니다 (pid=%s).", proc.pid)
        proc.terminate()
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
        """ComfyUI 의 모델 폴더별 목록 (v0.2 §5.3)."""
        folders = ["diffusion_models", "checkpoints", "text_encoders", "vae", "loras"]
        try:
            models = asyncio.run(self.client.get_all_models())
        except Exception as exc:
            self.logger.warning("모델 목록 조회 실패: %s", exc)
            return {}
        return {f: models[f] for f in folders if models.get(f)}

    def sampler_options(self) -> dict[str, list[str]]:
        """KSampler 가 받는 sampler / scheduler 목록."""
        try:
            return asyncio.run(self.client.get_samplers())
        except Exception:
            return {}

    # --- 취소 -------------------------------------------------------

    def cancel(self) -> None:
        """생성 중지를 요청한다."""
        try:
            asyncio.run(self.client.interrupt())
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
        return wf, wf.apply(values)

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
            images = asyncio.run(
                self.client.run(
                    payload,
                    on_progress=_progress,
                    on_stage=_stage,
                    timeout=self.config.timeout_seconds,
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

        return self._save(request, wf, payload, images, elapsed)

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
                    asyncio.run(
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

        metadata = OutputMetadata(
            seed=applied["seed"],
            model=wf.name,
            prompt=applied["prompt"],
            negative_prompt=applied["negative"],
            width=applied["width"],
            height=applied["height"],
            steps=applied["steps"],
            cfg=applied["cfg"],
            sampler=applied["sampler"],
            scheduler=applied["scheduler"],
            elapsed_seconds=round(elapsed, 2),
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
                original_prompt=applied["prompt"] or request.prompt,
                enhanced_prompt=applied["prompt"],
                negative_prompt=applied["negative"],
                llm_model=None,
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
