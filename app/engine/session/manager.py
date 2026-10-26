from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# Windows 파일명에서 쓸 수 없는 문자
_ILLEGAL_CHARS = '\\/:*?"<>|'
# 세션 폴더 이름에 넣을 프롬프트 최대 길이
_SLUG_MAX = 32


def _slugify(text: str, limit: int = _SLUG_MAX) -> str:
    """프롬프트를 탐색기에서 알아보기 좋은 폴더명으로 바꾼다.

    세션 폴더 이름은 사람이 읽는 것이 목적이므로 시각·순번을 넣지 않는다.
    순서는 session.json 의 created_at 으로 정렬한다 (list_sessions).
    """
    if not text:
        return "이미지"
    cleaned = "".join("_" if ch in _ILLEGAL_CHARS else ch for ch in text.strip())
    # 연속 공백을 하나로 모은다
    cleaned = " ".join(cleaned.split())
    # Windows 는 이름 끝의 공백과 마침표를 버린다
    cleaned = cleaned.rstrip(" .")
    if not cleaned:
        return "이미지"
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip(" .")
    return cleaned or "이미지"


def _read_created_at(meta_path: Path) -> str:
    """session.json 의 created_at 을 읽는다 (실패 시 빈 문자열)."""
    import json as _json

    try:
        data = _json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("created_at", ""))


@dataclass
class SessionMetadata:
    """Session 메타데이터.

    생성 이력을 되짚을 수 있도록 원본 프롬프트와 사용된 파라미터를 기록한다.
    """

    original_prompt: str
    enhanced_prompt: str
    negative_prompt: str
    llm_model: str | None
    image_model: str
    seed: int
    width: int
    height: int
    steps: int
    cfg: float
    sampler: str = "euler_a"
    scheduler: str = "default"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    generation_time: float = 0.0
    images: list[dict] = field(default_factory=list)
    prompt_options: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "original_prompt": self.original_prompt,
            "enhanced_prompt": self.enhanced_prompt,
            "negative_prompt": self.negative_prompt,
            "llm_model": self.llm_model,
            "image_model": self.image_model,
            "seed": self.seed,
            "width": self.width,
            "height": self.height,
            "steps": self.steps,
            "cfg": self.cfg,
            "sampler": self.sampler,
            "scheduler": self.scheduler,
            "created_at": self.created_at,
            "generation_time": self.generation_time,
            "images": self.images,
            "prompt_options": self.prompt_options,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SessionMetadata:
        return cls(
            original_prompt=data.get("original_prompt", ""),
            enhanced_prompt=data.get("enhanced_prompt", ""),
            negative_prompt=data.get("negative_prompt", ""),
            llm_model=data.get("llm_model"),
            image_model=data.get("image_model", "unknown"),
            seed=data.get("seed", 0),
            width=data.get("width", 1024),
            height=data.get("height", 1024),
            steps=data.get("steps", 20),
            cfg=data.get("cfg", 7.0),
            sampler=data.get("sampler", "euler_a"),
            scheduler=data.get("scheduler", "default"),
            created_at=data.get("created_at", datetime.now().isoformat(timespec="seconds")),
            generation_time=data.get("generation_time", 0.0),
            images=data.get("images", []),
            prompt_options=data.get("prompt_options", {}),
        )


class SessionManager:
    """Session CRUD 및 메타데이터 관리.

    구조:
        sessions/
            2026-10-01/
                001123-001/
                    session.json
                    001.png
                    001.json
                    002.png
                    002.json
    """

    def __init__(self, sessions_root: Path):
        self.sessions_root = sessions_root
        self.sessions_root.mkdir(parents=True, exist_ok=True)

    def create_session(self, metadata: SessionMetadata) -> Path:
        """새 세션 디렉토리를 생성하고 session.json을 저장한다.

        폴더 이름은 프롬프트에서 만들어 탐색기에서 알아보기 쉽게 한다.
        같은 이름이 이미 있으면 -2, -3 … 을 붙여 기존 폴더를 덮어쓰지 않는다.
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        date_dir = self.sessions_root / date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        slug = _slugify(metadata.original_prompt or metadata.enhanced_prompt)
        session_dir = date_dir / slug
        suffix = 2
        while session_dir.exists():
            session_dir = date_dir / f"{slug}-{suffix}"
            suffix += 1
        session_dir.mkdir(parents=True)

        meta_path = session_dir / "session.json"
        meta_path.write_text(
            json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return session_dir

    def get_session(self, session_path: Path) -> tuple[SessionMetadata, list[Path]]:
        """Session 디렉토리에서 메타데이터와 이미지 경로 리스트를 반환한다."""
        meta_path = session_path / "session.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"session.json not found in {session_path}")

        metadata = SessionMetadata.from_dict(
            json.loads(meta_path.read_text(encoding="utf-8"))
        )
        images = sorted(session_path.glob("*.png"))
        return metadata, images

    def list_sessions(self) -> list[Path]:
        """모든 세션 디렉토리를 생성 시각 최신순으로 반환한다.

        폴더 이름이 사람이 읽는 프롬프트 이름이라 순서를 담지 않는다.
        그래서 정렬은 session.json 의 created_at 을 쓴다.
        (ISO 형식이므로 문자열 비교가 곧 시간 비교다)
        """
        sessions: list[tuple[str, Path]] = []
        for date_dir in sorted(self.sessions_root.glob("*/"), reverse=True):
            if not date_dir.is_dir():
                continue
            for session_dir in date_dir.glob("*"):
                meta_path = session_dir / "session.json"
                if not meta_path.is_file():
                    continue
                sessions.append((_read_created_at(meta_path), session_dir))
        sessions.sort(key=lambda pair: pair[0], reverse=True)
        return [path for _, path in sessions]

    def delete_session(self, session_path: Path) -> None:
        """세션 디렉토리와 모든 내용을 삭제한다."""
        import shutil
        if session_path.exists():
            shutil.rmtree(session_path)

    def add_image_to_session(
        self,
        session_path: Path,
        metadata: SessionMetadata,
        image_path: Path,
        image_number: int,
    ) -> list[Path]:
        """세션에 이미지 생성 결과를 추가한다.

        이미지와 메타데이터 JSON을 세션 디렉토리로 복사하고,
        복사된 파일 경로 리스트를 반환한다.

        Returns:
            list[Path]: (이미지 경로, JSON 경로) 리스트
        """
        import json as _json
        import shutil

        meta_path = session_path / "session.json"

        target_image = session_path / f"{image_number:03d}.png"
        target_json = session_path / f"{image_number:03d}.json"

        shutil.copy2(image_path, target_image)

        source_json = image_path.with_suffix(".json")
        if source_json.exists():
            shutil.copy2(source_json, target_json)
        else:
            target_json.write_text(
                _json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        metadata.images.append({
            "filename": target_image.name,
            "metadata": target_json.name,
            "source": str(image_path),
            "number": image_number,
            "seed": metadata.seed,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        meta_path.write_text(
            _json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return [target_image, target_json]

    def remove_image_from_session(
        self,
        session_path: Path,
        image_name: str,
    ) -> bool:
        """세션에서 이미지 한 장과 그 메타데이터를 삭제한다.

        세션 폴더 전체가 아니라 이미지 단위로 지울 때 쓴다.
        images 목록도 함께 갱신해야 나중에 목록을 다시 읽어도
        없는 파일이 다시 나타나지 않는다.

        Returns:
            bool: 실제 삭제되었으면 True
        """
        import json as _json

        meta_path = session_path / "session.json"
        if not meta_path.exists():
            return False

        target_image = session_path / image_name
        if not target_image.exists():
            return False

        metadata = SessionMetadata.from_dict(
            _json.loads(meta_path.read_text(encoding="utf-8"))
        )
        entry = next(
            (e for e in metadata.images if e.get("filename") == image_name),
            None,
        )

        target_image.unlink()
        target_json = target_image.with_suffix(".json")
        if target_json.exists():
            target_json.unlink()

        if entry is not None:
            metadata.images.remove(entry)
        # images 가 비었다면 session.json 이 통째로 사라진 상태다.
        # 그래도 남겨 둔다 (빈 세션으로 보여주는 편이 삭제 실패보다 낫다)
        meta_path.write_text(
            _json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True

    def list_source_outputs(self) -> set[str]:
        """모든 세션이 참조한 원본 outputs/ 경로 집합을 반환한다.

        통합 브라우저에서 "세션이 없는 출력"을 찾아내는 데 쓴다.
        경로는 서로 다른 표기(슬래시/대소문자)를 가질 수 있어
        정규화해서 비교한다.
        """
        import json as _json
        import os

        sources: set[str] = set()
        for session_path in self.list_sessions():
            meta_path = session_path / "session.json"
            try:
                data = _json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for entry in data.get("images", []):
                source = entry.get("source")
                if source:
                    sources.add(os.path.normcase(os.path.abspath(source)))
        return sources
