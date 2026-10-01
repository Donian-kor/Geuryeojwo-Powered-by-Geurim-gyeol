"""TaskRunner 상태 머신 및 생성 흐름 테스트 (v0.1 §19~§20, §28~§29)."""
from pathlib import Path

import pytest

from app.engine.error.handler import ErrorHandler, ErrorType, OomRecovery
from app.engine.generation.controller import GenerationRequest, GenerationCancelled
from app.engine.generation.task_runner import TaskRunner, TaskState


def test_state_machine_reaches_completed():
    """상태가 순서대로 진행된다."""
    tr = TaskRunner()
    tr.start()
    assert tr.state == TaskState.INITIALIZING
    tr.transition(TaskState.LOADING_LLM)
    tr.transition(TaskState.ENHANCING_PROMPT)
    tr.transition(TaskState.SAMPLING)
    tr.transition(TaskState.COMPLETED, "완료")
    assert tr.state == TaskState.COMPLETED
    assert tr.progress == 100
    assert tr.is_completed


def test_progress_callback_receives_updates():
    """진행률 콜백이 호출된다."""
    received = []
    tr = TaskRunner()
    tr.set_progress_callback(lambda p, m: received.append((p, m)))
    tr.start()
    tr.set_progress(65, "생성 중")
    assert (65, "생성 중") in received


def test_sampling_progress_range():
    """Sampling 진행률은 50~90 범위로 매핑된다 (v0.1 §20)."""
    tr = TaskRunner()
    tr.transition(TaskState.SAMPLING)
    assert tr.progress == 50
    tr.set_progress(90)
    assert 50 <= tr.progress <= 100


def test_cancel_state():
    tr = TaskRunner()
    tr.start()
    tr.cancel()
    assert tr.state == TaskState.CANCELLED
    assert tr.is_failed
    assert not tr.is_active


def test_error_state_records_message():
    tr = TaskRunner()
    tr.transition(TaskState.ERROR, "OOM 발생")
    assert tr.state == TaskState.ERROR
    assert tr.get_error() == "OOM 발생"


def test_oom_recovery_suggests_lower_settings():
    """OOM 시 해상도/스텝을 낮춘 제안을 반환한다 (v0.1 §29)."""
    suggestion = OomRecovery.suggest_recovery(1536, 1536, 40, 9.0)
    assert suggestion.changes["width"] == 1024
    assert suggestion.changes["height"] == 1024
    assert suggestion.changes["steps"] == 30
    assert suggestion.estimated_vram_save and suggestion.estimated_vram_save > 0


def test_error_handler_invokes_recovery_callback():
    """OOM 시 복구 콜백이 실행된다 (v0.1 §29 2~6단계)."""
    called = []
    handler = ErrorHandler()
    suggestion = handler.handle(
        RuntimeError("CUDA out of memory"),
        ErrorType.VRAM_INSUFFICIENT,
        context="width=1536,height=1536,steps=40,cfg=7.0",
        on_recovery=lambda: called.append(True),
    )
    assert called == [True]
    assert suggestion is not None
    assert suggestion.changes


def test_error_handler_classifies_types():
    handler = ErrorHandler()
    assert handler.handle(RuntimeError("x"), ErrorType.GENERATION_CANCELLED) is None
    assert handler.handle(RuntimeError("x"), ErrorType.GGUF_LOAD_FAILED) is not None
    assert handler.handle(RuntimeError("x"), ErrorType.UNSUPPORTED_MODEL) is not None


def test_generate_request_defaults():
    req = GenerationRequest("p", None, Path("m.safetensors"))
    assert req.width == 1024 and req.steps == 20 and req.cfg == 7.0
    assert req.seed == -1


def test_controller_cancel_mid_generation(engine, tmp_path):
    """생성 진행 중 취소하면 CANCELLED로 종료된다 (v0.1 §20, §28)."""
    req = GenerationRequest(
        "test prompt", None, tmp_path / "nonexistent.safetensors", steps=1
    )
    states = []

    def on_progress(value, message):
        states.append(value)
        # 프롬프트 생성 단계에서 사용자가 중지를 누른 상황
        if value == 20:
            engine.generation.cancel()

    result = engine.generation.run(req, on_progress)

    assert result.success is False
    assert "취소" in (result.error or "")
    assert engine.task_runner.state == TaskState.CANCELLED
    assert engine.task_runner.progress < 100
    assert states, "진행률이 전달되어야 한다"


def test_controller_cancel_sets_flag(engine):
    """cancel()은 취소 플래그와 상태를 설정한다."""
    engine.generation.cancel()
    assert engine.generation.cancelled is True
    assert engine.task_runner.state == TaskState.CANCELLED
    engine.generation.cancelled = False


def test_unsupported_model_returns_error_not_crash(engine, tmp_path):
    """지원하지 않는 모델은 예외가 아니라 결과로 반환된다 (v0.1 §28)."""
    req = GenerationRequest(
        "a cat", None, tmp_path / "weird_model.safetensors", steps=1
    )
    result = engine.generation.run(req)
    assert result.success is False
    assert result.error
    assert engine.task_runner.state == TaskState.ERROR