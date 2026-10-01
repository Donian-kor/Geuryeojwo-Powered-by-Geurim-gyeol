"""Prompt 시스템 테스트 (v0.1 §13~§16, §36 LLM Test)."""
import pytest

from app.engine.prompt.engine import LlmProfile, PromptEngine
from app.engine.prompt.validator import PromptValidator


@pytest.fixture
def prompt_engine(engine):
    return engine.prompt


def test_validate_prompt_accepts_normal_input(prompt_engine):
    vr = prompt_engine.validate_prompt("a beautiful sunset over the mountains")
    assert vr.valid
    assert not vr.errors


@pytest.mark.parametrize("bad", ["", "   ", "<script>alert(1)</script>", "x" * 2001])
def test_validate_prompt_rejects_invalid(prompt_engine, bad):
    assert not prompt_engine.validate_prompt(bad).valid


def test_validate_parameters(prompt_engine):
    assert prompt_engine.validate_parameters(1024, 1024, 30, 7.0).valid
    assert not prompt_engine.validate_parameters(0, 1024, 30, 7.0).valid
    assert not prompt_engine.validate_parameters(1023, 1024, 30, 7.0).valid
    assert not prompt_engine.validate_parameters(1024, 1024, 0, 7.0).valid
    assert not prompt_engine.validate_parameters(1024, 1024, 30, 0.5).valid


@pytest.mark.parametrize("architecture,style", [
    ("sd15", "tag"),
    ("sd21", "tag"),
    ("sdxl", "sentence"),
    ("flux", "sentence"),
])
def test_prompt_style_per_architecture(prompt_engine, architecture, style):
    """LLM이 아닌 대상 이미지 모델이 스타일을 결정한다 (v0.1 §14)."""
    assert prompt_engine.policy.get_prompt_style(architecture) == style


def test_negative_policy_per_architecture(prompt_engine):
    """negative 정책이 아키텍처별로 다르다 (v0.1 §16)."""
    assert prompt_engine.policy.use_negative_prompt("sd15") is True
    assert prompt_engine.policy.use_negative_prompt("flux") is False
    assert prompt_engine.negative("flux") == ""


def test_fallback_without_llm(prompt_engine):
    """LLM이 없으면 fallback 프롬프트를 만든다."""
    result = prompt_engine.build("a girl walking in the rain", "sd15")
    assert result.enhanced is False
    assert "girl walking in the rain" in result.positive


def test_build_applies_negative_dictionary(prompt_engine):
    result = prompt_engine.build("a cat", "sd15")
    assert "low quality" in result.negative


def test_context_overflow_rejected(prompt_engine):
    """과도한 프롬프트는 거부된다 (§36 Context 초과)."""
    assert not prompt_engine.validate_prompt("word " * 600).valid


def test_llm_profile_lookup():
    """LLM 프로필 조회 (v0.1 §14)."""
    from pathlib import Path

    profile = LlmProfile(Path("config/llm_profiles.json"))
    assert profile.get("qwen2.5-7b-instruct.gguf")["korean_support"] is True
    assert profile.get("unknown.gguf")["max_context"] == 4096
    assert profile.get(None)["recommended_temperature"] == 0.7


def test_validator_seed_range():
    v = PromptValidator()
    assert v.validate_seed(0) is True
    assert v.validate_seed(2**31 - 1) is True
    assert v.validate_seed(-1) is False