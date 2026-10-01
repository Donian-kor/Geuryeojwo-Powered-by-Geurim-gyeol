"""Session / Output 저장 테스트.

    네트워크나 ComfyUI 없이 순수 파일 I/O만 검증한다.
    """
import json
import shutil
from datetime import datetime
from pathlib import Path

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


def test_output_does_not_overwrite_when_middle_file_deleted(tmp_path):
    """중간 파일을 지워도 살아있는 파일을 덮어쓰지 않는다.

    회귀: index = len(existing) + 1 방식이면
    3개 저장 → 첫 번째 삭제 → 재저장 시 img_002_seed9.png 가 덮어써진다.
    """
    manager = OutputManager(tmp_path)
    first_paths = []
    for seed in (9, 18, 27):
        png, _ = manager.save_output(FakeImage(), OutputMetadata(
            seed=seed, model="m", prompt="p", negative_prompt="",
            width=8, height=8, steps=4, cfg=4.0,
        ))
        first_paths.append(png)

    # 첫 번째 파일 삭제 → 이제 2개만 남는다
    first_paths[0].unlink()
    first_paths[0].with_suffix(".json").unlink()

    second_png, _ = manager.save_output(FakeImage(), OutputMetadata(
        seed=9, model="m", prompt="p", negative_prompt="",
        width=8, height=8, steps=4, cfg=4.0,
    ))

    # 남은 두 파일은 그대로 살아있어야 한다
    for alive in first_paths[1:]:
        assert alive.exists(), f"{alive.name} 이 덮어써졌다"
    assert second_png != first_paths[1], "새 파일이 기존 파일과 겹치지 않아야 한다"


def test_session_does_not_reuse_existing_folder(tmp_path):
    """중간 세션을 지워도 살아있는 세션 폴더를 재사용하지 않는다.

    회귀: 개수 + 1 방식이면 001/002 생성 → 001 삭제 → 새 생성 시
    살아있는 002 폴더를 그대로 쓰고 session.json 을 덮어썼다.
    """
    manager = SessionManager(tmp_path)
    meta = SessionMetadata(
        original_prompt="p", enhanced_prompt="p", negative_prompt="",
        llm_model=None, image_model="m", seed=1,
        width=8, height=8, steps=4, cfg=4.0,
    )

    dirs = [manager.create_session(meta) for _ in range(3)]
    marker = dirs[1] / "keepme.txt"
    marker.write_text("살아있는 세션", encoding="utf-8")

    shutil.rmtree(dirs[0])  # 첫 세션 삭제

    fresh = manager.create_session(meta)
    assert fresh not in (dirs[1], dirs[2]), "기존 세션 폴더를 재사용했다"
    assert marker.exists(), "살아있는 세션의 내용이 사라졌다"
    assert (fresh / "session.json").exists()


def test_next_index_uses_maximum_not_count():
    """next_index 헬퍼는 최대 번호를 기준으로 한다."""
    from app.engine.output.manager import next_index

    assert next_index([], prefix="img_") == 1
    assert next_index(["img_001_seed9.png"], prefix="img_", suffix_before="_seed") == 2
    # 002만 남았는데 (001 삭제) 개수 기준이면 2 → 충돌
    assert next_index(
        ["img_002_seed18.png", "img_005_seed27.png"],
        prefix="img_",
        suffix_before="_seed",
    ) == 6


def test_theme_manager_survives_broken_config(tmp_path):
    """깨진 theme_config.json 이 있어도 프로그램이 시작된다.

    회귀: json.loads 에 예외 처리가 없어 시작 자체가 실패했다.
    """
    import logging

    from PySide6.QtWidgets import QApplication

    from app.gui.theme.manager import ThemeManager

    app = QApplication.instance() or QApplication([])
    config = tmp_path / "theme_config.json"
    config.write_text("{", encoding="utf-8")  # 잘못된 JSON

    manager = ThemeManager(app, config)
    assert manager.current_theme == "dark", "기본 테마로 시작해야 한다"
    assert logging.getLogger("app.gui.theme.manager") is not None


def test_output_metadata_version_matches_package(tmp_path):
    """저장되는 metadata 버전이 프로그램 버전과 같다 (§7 단일 source of truth)."""
    from app import __version__

    manager = OutputManager(tmp_path)
    _, js = manager.save_output(FakeImage(), OutputMetadata(
        seed=1, model="m", prompt="p", negative_prompt="",
        width=8, height=8, steps=4, cfg=4.0,
    ))
    assert json.loads(js.read_text(encoding="utf-8"))["version"] == __version__
    assert __version__ != "0.1.0", "버전 문자열이 이전 판에 남아 있다"


def test_session_folder_name_uses_prompt_not_number(tmp_path):
    """세션 폴더 이름이 사람이 읽는 프롬프트 이름이다.

    회귀: 194036-001 처럼 시각과 순번만 들어가 탐색기에서
    무엇인지 알 수 없었다.
    """
    manager = SessionManager(tmp_path)
    session = manager.create_session(SessionMetadata(
        original_prompt="해변에서 수영하는 한국여자",
        enhanced_prompt="해변에서 수영하는 한국여자",
        negative_prompt="", llm_model=None, image_model="m",
        seed=1, width=8, height=8, steps=4, cfg=4.0,
    ))
    assert session.name == "해변에서 수영하는 한국여자"
    # 시각/순번 숫자가 이름에 섞이지 않는다
    assert not session.name[0].isdigit(), session.name
    assert (session / "session.json").exists()


def test_session_folder_name_strips_illegal_chars(tmp_path):
    """Windows 파일명에서 쓸 수 없는 문자가 제거된다."""
    manager = SessionManager(tmp_path)
    session = manager.create_session(SessionMetadata(
        original_prompt='a cat: "cute" <best>/fancy? 100% |nice|',
        enhanced_prompt="x", negative_prompt="", llm_model=None,
        image_model="m", seed=1, width=8, height=8, steps=4, cfg=4.0,
    ))
    for ch in '\\/:*?"<>|':
        assert ch not in session.name, f"{ch} 가 남아 있다: {session.name}"
    assert (session / "session.json").exists()


def test_session_folder_name_is_truncated_and_never_blank():
    """긴 프롬프트는 잘리고, 빈 값이면 기본 이름을 쓴다."""
    from app.engine.session.manager import _slugify

    long_prompt = "가나다라마바사아자차카타파하가나다라마바사아자차카타파하"
    assert len(_slugify(long_prompt)) <= 32

    assert _slugify("") == "이미지"
    assert _slugify("   ") == "이미지"
    assert _slugify("...") == "이미지"
    # 끝 공백/마침표는 Windows 가 버린다
    assert _slugify("고양이 ...") == "고양이"


def test_same_prompt_twice_does_not_overwrite(tmp_path):
    """같은 프롬프트를 다시 생성해도 첫 세션을 덮어쓰지 않는다."""
    manager = SessionManager(tmp_path)
    meta = SessionMetadata(
        original_prompt="고양이", enhanced_prompt="고양이", negative_prompt="",
        llm_model=None, image_model="m", seed=1,
        width=8, height=8, steps=4, cfg=4.0,
    )
    first = manager.create_session(meta)
    marker = first / "keepme.txt"
    marker.write_text("살아있는 세션", encoding="utf-8")

    second = manager.create_session(meta)
    assert second != first, "같은 폴더를 재사용했다"
    assert marker.exists(), "첫 세션이 덮어써졌다"
    assert (second / "session.json").exists()
    assert len(manager.list_sessions()) == 2


def test_list_sessions_sorted_by_created_at_not_name(tmp_path):
    """이름이 아니라 생성 시각 최신순으로 정렬된다.

    회귀: 폴더 이름에 시각이 없으므로 이름 정렬로는 newest-first 가
    되지 않는다.
    """
    import json as _json

    manager = SessionManager(tmp_path)
    date_dir = tmp_path / datetime.now().strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    # 이름은 알파벳 역순, 시각은 오래된 순으로 일부러 만든다
    for name, stamp in (("aaa-이름", "2026-01-01T00:00:00"),
                        ("zzz-이름", "2026-06-01T00:00:00")):
        d = date_dir / name
        d.mkdir()
        (d / "session.json").write_text(
            _json.dumps({"created_at": stamp}), encoding="utf-8"
        )

    listed = [p.name for p in manager.list_sessions()]
    assert listed == ["zzz-이름", "aaa-이름"], f"{listed}"


def test_list_sessions_finds_legacy_numeric_folders(tmp_path):
    """옛 형식(194036-001) 폴더도 계속 조회된다."""
    import json as _json

    manager = SessionManager(tmp_path)
    date_dir = tmp_path / datetime.now().strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    legacy = date_dir / "194036-001"
    legacy.mkdir()
    (legacy / "session.json").write_text(
        _json.dumps({"created_at": "2026-10-01T19:40:36"}), encoding="utf-8"
    )

    assert legacy in manager.list_sessions()


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