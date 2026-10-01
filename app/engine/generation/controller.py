from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import time

from .task_runner import TaskRunner, TaskState


class GenerationCancelled(Exception):
    """사용자가 생성을 취소했음을 나타내는 예외 (v0.1 §28)."""


@dataclass
class GenerationRequest:
    prompt: str
    llm_path: Path | None
    image_path: Path
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg: float = 7.0
    seed: int = -1


@dataclass
class GenerationResult:
    """생성 결과 (v0.1 §44.12 GenerationResult 구조)."""

    image_path: Path | None = None
    metadata: dict = field(default_factory=dict)
    session_path: Path | None = None
    success: bool = False
    error: str | None = None
    suggestion: object | None = None
    prompt: str = ""
    negative_prompt: str = ""
    seed: int = -1
    generation_time: float = 0.0
    model: str = ""


class GenerationController:
    """전체 generation lifecycle orchestration (v0.1 §19, §44.5).

    TaskRunner 상태 머신(§20), ErrorHandler/OOM Recovery(§28-29),
    LogManager(§30)를 실제 생성 흐름에 연결한다.
    """

    def __init__(
        self,
        engine,
        registry,
        prompt_engine,
        memory,
        logger,
        output_root: Path,
        task_runner: TaskRunner | None = None,
        error_handler=None,
        logs=None,
    ):
        self.engine = engine
        self.registry = registry
        self.prompt_engine = prompt_engine
        self.memory = memory
        self.logger = logger
        self.output_root = output_root
        self.task_runner = task_runner or TaskRunner(logger)
        self.error_handler = error_handler
        self.logs = logs
        self.cancelled = False

    def cancel(self) -> None:
        """생성 취소 요청 (v0.1 §20 CANCELLED, §28)."""
        self.cancelled = True
        self.task_runner.cancel()

    def _check_cancelled(self) -> None:
        if self.cancelled:
            raise GenerationCancelled("사용자가 생성을 취소했습니다.")

    def _emit(self, progress, state: TaskState, message: str = "") -> None:
        """TaskRunner 상태를 전환하고 GUI로 진행률을 전달한다."""
        self.task_runner.transition(state, message)
        if progress:
            progress(self.task_runner.progress, self.task_runner.message)

    def _log(self, event: str, **payload) -> None:
        """LogManager 4-tier 기록 위임 (§30)."""
        if not self.logs:
            return
        method = {
            "model_load": lambda: self.logs.log_model_load(
                payload.get("name", ""), payload.get("model_type", "")
            ),
            "model_unload": lambda: self.logs.log_model_unload(payload.get("name", "")),
            "vram": lambda: self.logs.log_vram(
                payload.get("allocated", 0.0),
                payload.get("reserved", 0.0),
                payload.get("total", 0.0),
            ),
            "ram": lambda: self.logs.log_ram(
                payload.get("used", 0.0),
                payload.get("total", 0.0),
                payload.get("percent", 0.0),
            ),
            "generation_time": lambda: self.logs.log_generation_time(
                payload.get("elapsed", 0.0)
            ),
            "prompt_policy": lambda: self.logs.log_prompt_policy(
                payload.get("original", ""),
                payload.get("enhanced", ""),
                payload.get("policy", ""),
            ),
        }.get(event)
        if method:
            method()

    def _snapshot_log(self, snap) -> None:
        """스냅샷을 memory.log에 기록한다 (§30)."""
        self._log(
            "vram",
            allocated=snap.vram_allocated_gb or 0.0,
            reserved=snap.vram_reserved_gb or 0.0,
            total=snap.vram_total_gb or 0.0,
        )
        if snap.ram_total_gb and snap.ram_free_gb is not None:
            used = snap.ram_total_gb - snap.ram_free_gb
            self._log(
                "ram",
                used=used,
                total=snap.ram_total_gb,
                percent=(used / snap.ram_total_gb * 100) if snap.ram_total_gb else 0.0,
            )

    def _classify_error(self, error: Exception):
        """예외를 ErrorType으로 분류한다 (v0.1 §28)."""
        from ..error.handler import ErrorType

        name = type(error).__name__
        text = str(error).lower()
        if isinstance(error, GenerationCancelled):
            return ErrorType.GENERATION_CANCELLED
        if "out of memory" in text or "cuda oom" in text or name == "OutOfMemoryError":
            return ErrorType.VRAM_INSUFFICIENT
        if "no such file" in text or "not found" in text:
            return ErrorType.MODEL_CORRUPTED
        if "지원하지 않는 아키텍처" in str(error):
            return ErrorType.UNSUPPORTED_MODEL
        if "not installed" in text or "no module named" in text:
            return ErrorType.IMAGE_PIPELINE_FAILED
        return ErrorType.UNKNOWN

    def _recover_from_oom(self) -> None:
        """OOM Recovery 정리 단계 (v0.1 §29 2~6단계).

        2. Image Model unload → 3. LLM unload → 4. GC
        → 5. CUDA Cache cleanup → 6. Memory Snapshot
        """
        self.engine.image.unload()
        self.memory.cleanup()
        self._snapshot_log(self.memory.take_snapshot("after_oom"))

    def run(self, req: GenerationRequest, progress=None) -> GenerationResult:
        from ..output.manager import OutputManager, OutputMetadata
        from ..session.manager import SessionManager, SessionMetadata

        output_manager = OutputManager(self.output_root)
        session_manager = SessionManager(self.output_root.parent / "sessions")
        self.cancelled = False
        self.task_runner.start()
        started = time.perf_counter()
        image_profile = self.registry.profile_for(req.image_path)
        llm = None

        try:
            self._emit(progress, TaskState.INITIALIZING, "초기화")
            self._snapshot_log(self.memory.take_snapshot("before_llm"))

            if req.llm_path:
                self._emit(progress, TaskState.LOADING_LLM, "로컬 LLM 로드")
                from ..llm.llama_cpp import LocalLLM
                llm_profile = self.prompt_engine.llm_profile_for(req.llm_path)
                llm = LocalLLM(
                    req.llm_path,
                    self.engine.hardware.device,
                    self.logger,
                    profile=llm_profile,
                ).load()
                self._log("model_load", name=req.llm_path.name, model_type="llm")
            else:
                self._emit(progress, TaskState.ANALYZING, "LLM 생략 (fallback)")

            self._snapshot_log(self.memory.take_snapshot("llm_loaded"))
            self._check_cancelled()

            self._emit(progress, TaskState.ANALYZING, "그림결 프롬프트 분석")
            prompt_result = self.prompt_engine.build(
                req.prompt, image_profile.architecture, llm, req.llm_path
            )
            positive = prompt_result.positive
            negative = req.negative_prompt.strip() or prompt_result.negative
            self._log(
                "prompt_policy",
                original=req.prompt,
                enhanced=positive,
                policy=prompt_result.policy_used,
            )

            self._emit(progress, TaskState.ENHANCING_PROMPT, "프롬프트 생성 완료")
            self._check_cancelled()

            if llm:
                self._emit(progress, TaskState.UNLOADING_LLM, "LLM 해제")
                llm.unload()
                self._log("model_unload", name=req.llm_path.name)
                del llm
                llm = None

                self._emit(progress, TaskState.CLEANING_MEMORY, "메모리 정리")
                self.memory.cleanup()
                self._snapshot_log(self.memory.take_snapshot("after_llm_unload"))

            self._check_cancelled()
            self._emit(progress, TaskState.LOADING_IMAGE_MODEL, "이미지 모델 로드")

            # 메모리 전략 자동 결정 (v0.1 §8.2)
            strategy = self.engine.image.plan_strategy(
                image_profile.architecture, req.width, req.height, req.steps
            )
            if strategy.tier.value == "impossible":
                raise RuntimeError(f"메모리 부족: {strategy.reason}")
            if strategy.uses_offload or strategy.suggested_width:
                self._emit(progress, TaskState.LOADING_IMAGE_MODEL, strategy.describe())
                self.logger.info("메모리 전략: %s", strategy.describe())

            self.engine.image.load(
                req.image_path, image_profile.architecture, strategy
            )
            self._log("model_load", name=req.image_path.name, model_type="image")
            self._snapshot_log(self.memory.take_snapshot("image_loaded"))

            # 전략이 제안한 해상도/steps를 적용한다
            width, height, steps = req.width, req.height, req.steps
            reduced = self.engine.image.reduced_settings
            if reduced:
                width = reduced["width"]
                height = reduced["height"]
                steps = reduced["steps"]

            self._emit(progress, TaskState.ENCODING, "프롬프트 인코딩")

            def sampling_progress(step_pct: int) -> None:
                """Sampling 진행률 + 취소 확인 (v0.1 §20)."""
                self._check_cancelled()
                pct = 50 + int(step_pct * 0.45)
                self.task_runner.set_progress(
                    pct, f"이미지 생성 중... {pct}%"
                )

            self.task_runner.transition(TaskState.SAMPLING, "이미지 생성")
            image, seed = self.engine.image.generate(
                positive, negative, width, height,
                steps, req.cfg, req.seed, sampling_progress,
            )

            self._emit(progress, TaskState.DECODING, "VAE 디코딩")
            elapsed = round(time.perf_counter() - started, 2)

            self._emit(progress, TaskState.SAVING, "이미지 저장")

            output_meta = OutputMetadata(
                seed=seed,
                model=str(req.image_path),
                prompt=positive,
                negative_prompt=negative,
                width=width,
                height=height,
                steps=steps,
                cfg=req.cfg,
                sampler=getattr(image_profile, 'sampler', "euler_a"),
                scheduler=getattr(image_profile, 'scheduler', "default"),
                elapsed_seconds=elapsed,
                llm_model=str(req.llm_path) if req.llm_path else None,
            )

            png_path, json_path = output_manager.save_output(image, output_meta)

            session_meta = SessionMetadata(
                original_prompt=req.prompt,
                enhanced_prompt=positive,
                negative_prompt=negative,
                llm_model=str(req.llm_path) if req.llm_path else None,
                image_model=str(req.image_path),
                seed=seed,
                width=width,
                height=height,
                steps=steps,
                cfg=req.cfg,
                sampler=getattr(image_profile, 'sampler', "euler_a"),
                scheduler=getattr(image_profile, 'scheduler', "default"),
                generation_time=elapsed,
            )
            session_path = session_manager.create_session(session_meta)
            session_manager.add_image_to_session(
                session_path, session_meta, png_path, 1
            )

            self._snapshot_log(self.memory.take_snapshot("after_generation"))
            self._log("generation_time", elapsed=elapsed)
            self.task_runner.set_session_path(session_path)
            self._emit(progress, TaskState.COMPLETED, "완료")

            return GenerationResult(
                image_path=png_path,
                metadata=output_meta.to_dict(),
                session_path=session_path,
                success=True,
                prompt=positive,
                negative_prompt=negative,
                seed=seed,
                generation_time=elapsed,
                model=image_profile.architecture,
            )

        except GenerationCancelled as exc:
            self.task_runner.transition(TaskState.CANCELLED, str(exc))
            if progress:
                progress(self.task_runner.progress, str(exc))
            self.logger.info("Generation cancelled: %s", exc)
            return GenerationResult(
                success=False, error=str(exc), model=image_profile.architecture
            )

        except Exception as exc:
            error_type = self._classify_error(exc)
            suggestion = None
            if self.error_handler:
                suggestion = self.error_handler.handle(
                    exc,
                    error_type,
                    context=(
                        f"width={req.width},height={req.height},"
                        f"steps={req.steps},cfg={req.cfg}"
                    ),
                    on_recovery=self._recover_from_oom,
                )
            self.logger.error("Generation failed: %s", exc, exc_info=True)
            self.task_runner.transition(TaskState.ERROR, str(exc))
            if progress:
                progress(self.task_runner.progress, f"오류: {exc}")
            return GenerationResult(
                success=False,
                error=str(exc),
                suggestion=suggestion,
                model=image_profile.architecture,
            )

        finally:
            if llm:
                llm.unload()
                if req.llm_path:
                    self._log("model_unload", name=req.llm_path.name)
                del llm
            if self.engine.image.adapter:
                self._log("model_unload", name=req.image_path.name)
            self.engine.image.unload()
            self.memory.cleanup()
            self._snapshot_log(self.memory.take_snapshot("final"))
