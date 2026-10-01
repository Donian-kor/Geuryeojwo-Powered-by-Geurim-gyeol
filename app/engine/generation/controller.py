from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import time


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
    image_path: Path
    metadata: dict


class GenerationController:
    """전체 generation lifecycle orchestration (v0.1 §19, §44.5)."""

    def __init__(self, engine, registry, prompt_engine, memory, logger, output_root: Path):
        self.engine = engine
        self.registry = registry
        self.prompt_engine = prompt_engine
        self.memory = memory
        self.logger = logger
        self.output_root = output_root
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def run(self, req: GenerationRequest, progress=None) -> GenerationResult:
        from ..output.manager import OutputManager, OutputMetadata
        from ..session.manager import SessionManager, SessionMetadata

        output_manager = OutputManager(self.output_root)
        session_manager = SessionManager(self.output_root.parent / "sessions")
        self.cancelled = False
        started = time.perf_counter()
        image_profile = self.registry.profile_for(req.image_path)
        llm = None

        try:
            self.memory.take_snapshot("before_llm")

            if req.llm_path:
                from ..llm.llama_cpp import LocalLLM
                if progress: progress(5, "로컬 LLM 로드")
                llm = LocalLLM(req.llm_path, self.engine.hardware.device, self.logger).load()
            else:
                if progress: progress(2, "LLM 생략 (fallback)")

            self.memory.take_snapshot("llm_loaded")

            if progress: progress(15, "그림결 프롬프트 분석")
            positive, dictionary_negative = self.prompt_engine.build(
                req.prompt, image_profile.architecture, llm
            )
            negative = req.negative_prompt.strip() or dictionary_negative

            if llm:
                llm.unload()
                del llm
                self.memory.cleanup()

            self.memory.take_snapshot("after_llm_unload")

            if progress: progress(30, "LLM 메모리 해제 완료")
            if self.cancelled:
                raise RuntimeError("Generation cancelled")
            if progress: progress(35, "이미지 모델 로드")

            self.engine.image.load(req.image_path, image_profile.architecture)
            self.memory.take_snapshot("image_loaded")

            def p(v):
                if progress: progress(35 + int(v * 0.6), "이미지 생성")

            image, seed = self.engine.image.generate(
                positive, negative, req.width, req.height,
                req.steps, req.cfg, req.seed, p,
            )

            output_meta = OutputMetadata(
                seed=seed,
                model=str(req.image_path),
                prompt=positive,
                negative_prompt=negative,
                width=req.width,
                height=req.height,
                steps=req.steps,
                cfg=req.cfg,
                sampler=getattr(image_profile, 'sampler', "euler_a"),
                scheduler=getattr(image_profile, 'scheduler', "default"),
                elapsed_seconds=round(time.perf_counter() - started, 2),
                llm_model=str(req.llm_path) if req.llm_path else None,
            )

            png_path, json_path = output_manager.save_output(image, output_meta)
            meta = output_meta.to_dict()

            session_meta = SessionMetadata(
                original_prompt=req.prompt,
                enhanced_prompt=positive,
                negative_prompt=negative,
                llm_model=str(req.llm_path) if req.llm_path else None,
                image_model=str(req.image_path),
                seed=seed,
                width=req.width,
                height=req.height,
                steps=req.steps,
                cfg=req.cfg,
                sampler=getattr(image_profile, 'sampler', "euler_a"),
                scheduler=getattr(image_profile, 'scheduler', "default"),
                generation_time=round(time.perf_counter() - started, 2),
            )
            session_path = session_manager.create_session(session_meta)
            session_manager.add_image_to_session(
                session_path, session_meta, png_path, 1
            )

            self.memory.take_snapshot("after_generation")

            if progress: progress(100, "완료")
            result = GenerationResult(image_path=png_path, metadata=meta)
            result.session_path = session_path
            return result

        finally:
            if llm:
                llm.unload()
                del llm
            self.memory.cleanup()
            self.engine.image.unload()
            self.memory.take_snapshot("final")
