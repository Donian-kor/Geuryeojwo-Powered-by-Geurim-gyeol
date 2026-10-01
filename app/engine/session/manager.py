from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class SessionMetadata:
    """Session 메타데이터 (v0.1 §21 Session Metadata)."""

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
        )


class SessionManager:
    """Session CRUD 및 메타데이터 관리 (v0.1 §21, PHASE 9).

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
        """새 세션 디렉토리를 생성하고 session.json을 저장한다."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H%M%S")
        date_dir = self.sessions_root / date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        count = len(list(date_dir.glob(f"{time_str}-*")))
        session_num = f"{count + 1:03d}"
        session_id = f"{time_str}-{session_num}"
        session_dir = date_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

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
        """모든 세션 디렉토리를 날짜별로 정렬하여 반환한다."""
        sessions = []
        for date_dir in sorted(self.sessions_root.glob("*/"), reverse=True):
            if not date_dir.is_dir():
                continue
            for session_dir in sorted(date_dir.glob("*-*"), reverse=True):
                if (session_dir / "session.json").exists():
                    sessions.append(session_dir)
        return sessions

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
        """세션에 이미지 생성 결과를 추가한다 (v0.1 §21).

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
