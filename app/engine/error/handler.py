from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorType(Enum):
    """에러 범주 (v0.1 §28)."""

    MODEL_CORRUPTED = "model_corrupted"
    UNSUPPORTED_MODEL = "unsupported_model"
    VRAM_INSUFFICIENT = "vram_insufficient"
    RAM_INSUFFICIENT = "ram_insufficient"
    CUDA_INIT_FAILED = "cuda_init_failed"
    GGUF_LOAD_FAILED = "gguf_load_failed"
    IMAGE_PIPELINE_FAILED = "image_pipeline_failed"
    VAE_ERROR = "vae_error"
    PROMPT_ERROR = "prompt_error"
    SAVE_FAILED = "save_failed"
    GENERATION_CANCELLED = "generation_cancelled"
    UNKNOWN = "unknown"


@dataclass
class RecoverySuggestion:
    """OOM/에러 시 자동 설정 제안 (v0.1 §29)."""

    title: str
    description: str
    changes: dict[str, any]
    estimated_vram_save: float | None = None


class OomRecovery:
    """CUDA OOM 발생 시 자동 설정 제안기 (v0.1 §29)."""

    @staticmethod
    def suggest_recovery(width: int, height: int, steps: int, current_cfg: float = 7.0) -> RecoverySuggestion:
        """현재 설정을 안전한 설정으로 낮추어 제안한다."""
        new_width = min(width, 1024)
        new_height = min(height, 1024)
        new_steps = min(steps, 30)
        new_cfg = min(current_cfg, 7.0)

        changes = {}
        if new_width < width:
            changes["width"] = new_width
        if new_height < height:
            changes["height"] = new_height
        if new_steps < steps:
            changes["steps"] = new_steps
        if new_cfg < current_cfg:
            changes["cfg"] = new_cfg

        vram_estimate = OomRecovery._estimate_vram(new_width, new_height, new_steps)
        current_estimate = OomRecovery._estimate_vram(width, height, steps)
        vram_save = current_estimate - vram_estimate if vram_estimate else None

        return RecoverySuggestion(
            title="VRAM 부족 - 설정 낮추기",
            description=f"현재 {width}x{height}, Steps {steps} → 제안 {new_width}x{new_height}, Steps {new_steps}",
            changes=changes,
            estimated_vram_save=vram_save,
        )

    @staticmethod
    def _estimate_vram(width: int, height: int, steps: int) -> float | None:
        """대략적인 VRAM 사용량 추정 (GB)."""
        try:
            pixels = (width * height) / (64 * 64)
            base_vram = {
                30: 3.5,
                20: 2.5,
                15: 2.0,
            }.get(steps, 3.0)
            return round(base_vram + pixels * 0.05, 1)
        except Exception:
            return None


class ErrorHandler:
    """중앙화된 에러 처리기 (v0.1 §28, §29).

    프로그램이 예외 발생 시 즉시 종료되지 않도록 에러를 잡아내고
    적절한 복구 조치를 제안한다.
    """

    def __init__(self, logger=None, oom_recovery_class=OomRecovery):
        self._logger = logger
        self._oom_recovery_class = oom_recovery_class

    def handle(self, error: Exception, error_type: ErrorType = ErrorType.UNKNOWN, context: str = "") -> RecoverySuggestion | None:
        """에러를 처리하고 필요시 복구 제안을 반환한다."""
        if self._logger:
            msg = f"[{error_type.value}] {context}: {error}" if context else f"[{error_type.value}] {error}"
            self._logger.error(msg, exc_info=True)

        if error_type == ErrorType.VRAM_INSUFFICIENT:
            return self._handle_oom(error, context)
        elif error_type == ErrorType.GGUF_LOAD_FAILED:
            return self._handle_gguf_error(error, context)
        elif error_type == ErrorType.MODEL_CORRUPTED:
            return self._handle_corrupted_model(error, context)
        elif error_type == ErrorType.UNSUPPORTED_MODEL:
            return self._handle_unsupported_model(error, context)
        elif error_type == ErrorType.GENERATION_CANCELLED:
            return None
        return None

    def _handle_oom(self, error: Exception, context: str) -> RecoverySuggestion:
        """OOM Recovery: 1. Task 중단, 2. Image Model unload, 3. LLM unload, 4. GC, 5. CUDA Cache cleanup, 6. Memory Snapshot, 7. 설정 제안."""
        if self._logger:
            self._logger.warning("OOM Recovery initiated: %s", context)

        # context에서 파라미터 추출 (expected format: "width=1024,height=1024,steps=30")
        params = {}
        if context:
            for part in context.split(","):
                if "=" in part:
                    key, val = part.strip().split("=", 1)
                    try:
                        params[key.strip()] = int(val) if key.strip() in ("width", "height", "steps") else float(val)
                    except ValueError:
                        pass

        return self._oom_recovery_class.suggest_recovery(
            params.get("width", 1024),
            params.get("height", 1024),
            params.get("steps", 30),
            params.get("cfg", 7.0),
        )

    def _handle_gguf_error(self, error: Exception, context: str) -> RecoverySuggestion:
        return RecoverySuggestion(
            title="GGUF 로딩 실패",
            description=f"LLM 모델 로드 중 오류: {error}",
            changes={"skip_llm": True, "use_fallback_prompt": True},
        )

    def _handle_corrupted_model(self, error: Exception, context: str) -> RecoverySuggestion:
        return RecoverySuggestion(
            title="모델 파일 손상",
            description="모델 파일이 손상되었거나 호환되지 않습니다. 다른 모델을 선택하거나 파일을 다시 다운로드하세요.",
            changes={"select_different_model": True},
        )

    def _handle_unsupported_model(self, error: Exception, context: str) -> RecoverySuggestion:
        return RecoverySuggestion(
            title="지원하지 않는 모델",
            description="이 아키텍처의 모델은 현재 지원되지 않습니다. SD15, SDXL 모델을 사용하세요.",
            changes={"select_supported_model": True},
        )
