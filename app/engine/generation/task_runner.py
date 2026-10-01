from __future__ import annotations

from enum import Enum
from pathlib import Path


class TaskState(Enum):
    """Task 상태 머신 (v0.1 §20)."""

    IDLE = "idle"
    INITIALIZING = "initializing"
    ANALYZING = "analyzing"
    LOADING_LLM = "loading_llm"
    ENHANCING_PROMPT = "enhancing_prompt"
    UNLOADING_LLM = "unloading_llm"
    CLEANING_MEMORY = "cleaning_memory"
    LOADING_IMAGE_MODEL = "loading_image_model"
    ENCODING = "encoding"
    SAMPLING = "sampling"
    DECODING = "decoding"
    SAVING = "saving"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class TaskRunner:
    """Task 상태 머신 및 진행 상황 추적 (v0.1 §20).

    GUI Progress 매핑:
        0%    초기화        (INITIALIZING)
        10%   프롬프트 분석  (ANALYZING)
        20%   프롬프트 생성  (ENHANCING_PROMPT)
        25%   LLM 해제      (UNLOADING_LLM)
        30%   메모리 정리   (CLEANING_MEMORY)
        40%   이미지 모델 로드 (LOADING_IMAGE_MODEL)
        50~90% Sampling   (SAMPLING)
        95%   이미지 저장   (SAVING)
        100%  완료         (COMPLETED)
    """

    STATE_PROGRESS = {
        TaskState.INITIALIZING: (0, "초기화"),
        TaskState.ANALYZING: (10, "프롬프트 분석"),
        TaskState.ENHANCING_PROMPT: (20, "프롬프트 생성"),
        TaskState.UNLOADING_LLM: (25, "LLM 해제"),
        TaskState.CLEANING_MEMORY: (30, "메모리 정리"),
        TaskState.LOADING_IMAGE_MODEL: (40, "이미지 모델 로드"),
        TaskState.SAMPLING: (50, "이미지 생성"),
        TaskState.SAVING: (95, "이미지 저장"),
        TaskState.COMPLETED: (100, "완료"),
    }

    def __init__(self, logger=None):
        self._state: TaskState = TaskState.IDLE
        self._progress: int = 0
        self._message: str = ""
        self._error: str | None = None
        self._logger = logger
        self._progress_callback = None

    def set_progress_callback(self, callback) -> None:
        """GUI 진행 상황 콜백 설정."""
        self._progress_callback = callback

    @property
    def state(self) -> TaskState:
        return self._state

    @property
    def progress(self) -> int:
        return self._progress

    @property
    def message(self) -> str:
        return self._message

    @property
    def is_active(self) -> bool:
        return self._state not in (TaskState.IDLE, TaskState.COMPLETED, TaskState.ERROR, TaskState.CANCELLED)

    @property
    def is_completed(self) -> bool:
        return self._state == TaskState.COMPLETED

    @property
    def is_failed(self) -> bool:
        return self._state in (TaskState.ERROR, TaskState.CANCELLED)

    def transition(self, state: TaskState, message: str = "", progress: int | None = None) -> None:
        """상태 전환 및 진행 상황 전파."""
        old_state = self._state
        self._state = state

        if state == TaskState.ERROR:
            self._error = message or "Unknown error"
            if self._logger:
                self._logger.error(self._error)
        elif state == TaskState.CANCELLED:
            self._error = message or "Task cancelled"
            if self._logger:
                self._logger.warning(self._error)

        if message:
            self._message = message

        if progress is not None:
            self._progress = progress
        elif state in self.STATE_PROGRESS:
            self._progress, default_msg = self.STATE_PROGRESS[state]
            if not message:
                self._message = default_msg

        if old_state != state and self._logger:
            self._logger.info("Task state: %s → %s (%s)", old_state.value, state.value, self._message)

        if self._progress_callback:
            self._progress_callback(self._progress, self._message)

    def start(self) -> None:
        """작업 시작 - INITIALIZING 상태로 전환."""
        self._error = None
        self.transition(TaskState.INITIALIZING, "초기화")

    def cancel(self) -> None:
        """작업 취소."""
        self.transition(TaskState.CANCELLED, "작업이 취소되었습니다")

    def get_error(self) -> str | None:
        """마지막 에러 메시지 반환."""
        return self._error

    def get_session_path(self) -> Path | None:
        """현재 세션 경로 (상태 추적용)."""
        return getattr(self, '_session_path', None)

    def set_session_path(self, path: Path) -> None:
        """현재 세션 경로 설정."""
        self._session_path = path
