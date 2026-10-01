"""Session / Output 저장 테스트.

    네트워크나 ComfyUI 없이 순수 파일 I/O만 검증한다.
    """
import json
from pathlib import Path

import pytest

from app.engine.output.manager import OutputManager, OutputMetadata
from app.engine.session.manager import SessionManager, SessionMetadata


class FakeImage:
    """PIL 없이 저장 동작만 검증하기 위한 더미 이미지."""

    def __init__(self):
        self.saved_to = None

    def save(self, path):
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
        self.saved_to = Path(path)


def test_output_save_creates_png_and_json(tmp_path):
    """PNG와 JSON이 함께 저장된다."""
    manager = OutputManager(tmp_path)
    meta = OutputMetadata(
        seed=1234, model="sdxl", prompt="a cat", negative_prompt="blurry",
        width=1024, height=1024, steps=30, cfg=7.0,
    )
    png, js = manager.save_output(FakeImage(), meta)
    assert png.exists() and js.exists()
    assert "seed1234" in png.name
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["seed"] == 1234
    assert data["prompt"] == "a cat"
    assert data["app"] == "Geuryeojwo"


def test_output_listing_roundtrip(tmp_path):
    manager = OutputManager(tmp_path)
    for seed in (1, 2):
        manager.save_output(FakeImage(), OutputMetadata(
            seed=seed, model="sdxl", prompt="p", negative_prompt="",
            width=512, height=512, steps=20, cfg=7.0,
        ))
    outputs = manager.list_outputs()
    assert len(outputs) == 2
    meta, js = manager.get_output(outputs[0][0])
    assert meta.seed in (1, 2)


def test_output_delete_removes_both_files(tmp_path):
    manager = OutputManager(tmp_path)
    png, js = manager.save_output(FakeImage(), OutputMetadata(
        seed=7, model="sdxl", prompt="p", negative_prompt="",
        width=512, height=512, steps=20, cfg=7.0,
    ))
    manager.delete_output(png)
    assert not png.exists() and not js.exists()


def test_session_stores_required_metadata(tmp_path):
    """Session metadata 필드를 모두 기록한다."""
    manager = SessionManager(tmp_path)
    meta = SessionMetadata(
        original_prompt="원본", enhanced_prompt="enhanced",
        negative_prompt="neg", llm_model="qwen.gguf",
        image_model="sdxl", seed=42, width=1024, height=1024,
        steps=30, cfg=7.0,
    )
    session = manager.create_session(meta)
    assert (session / "session.json").exists()
    loaded, _ = manager.get_session(session)
    assert loaded.original_prompt == "원본"
    assert loaded.seed == 42
    assert loaded.generation_time == 0.0


def test_session_copies_image_files(tmp_path):
    """세션 폴더에 이미지와 JSON이 실제 저장된다."""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    output_manager = OutputManager(outputs)
    png, _ = output_manager.save_output(FakeImage(), OutputMetadata(
        seed=99, model="sdxl", prompt="p", negative_prompt="",
        width=512, height=512, steps=20, cfg=7.0,
    ))

    session_manager = SessionManager(tmp_path / "sessions")
    meta = SessionMetadata(
        original_prompt="o", enhanced_prompt="e", negative_prompt="",
        llm_model=None, image_model="sdxl", seed=99,
        width=512, height=512, steps=20, cfg=7.0,
    )
    session = session_manager.create_session(meta)
    session_manager.add_image_to_session(session, meta, png, 1)

    copied = session / "001.png"
    assert copied.exists(), "세션 폴더에 이미지가 복사되어야 한다"
    assert (session / "001.json").exists()

    _, images = session_manager.get_session(session)
    assert len(images) == 1


def test_session_listing_and_delete(tmp_path):
    manager = SessionManager(tmp_path)
    for i in range(2):
        meta = SessionMetadata(
            original_prompt=f"p{i}", enhanced_prompt="e", negative_prompt="",
            llm_model=None, image_model="sdxl", seed=i,
            width=512, height=512, steps=20, cfg=7.0,
        )
        manager.create_session(meta)
    sessions = manager.list_sessions()
    assert len(sessions) == 2
    manager.delete_session(sessions[0])
    assert len(manager.list_sessions()) == 1