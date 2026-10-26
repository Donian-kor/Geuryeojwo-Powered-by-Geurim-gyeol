from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ... import __version__


def next_index(
    names,
    prefix: str,
    suffix_before: str = "",
) -> int:
    """파일명에서 최대 번호를 읽어 +1 을 반환한다.

    파일 "개수 + 1" 방식은 중간 파일이 지워졌을 때 이미 있는 이름과
    겹쳐 기존 파일을 덮어쓴다. 최대값 방식은 삭제 여부에 영향받지 않는다.

    Args:
        names: 파일명 iterable (예: ["img_001_seed9.png", ...])
        prefix: 접두사 (예: "img_")
        suffix_before: 번호 뒤에 붙는 구분자 (예: "_seed").
            비우면 접두사만 제거한 나머지 전체를 번호로 본다.

    Returns:
        int: 기존 최대 번호 + 1 (기존 파일이 없으면 1)
    """
    highest = 0
    for name in names:
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        if suffix_before and suffix_before in rest:
            rest = rest.split(suffix_before, 1)[0]
        # 확장자 제거 후 숫자 부분만 취한다
        digits = ""
        for ch in rest:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            highest = max(highest, int(digits))
    return highest + 1


@dataclass
class OutputMetadata:
    """출력 이미지 메타데이터.

    같은 프롬프트로 같은 결과를 다시 만들 수 있도록 (Reproducibility)
    생성에 사용한 모든 값을 기록한다.
    """

    seed: int
    model: str
    # prompt: 이미지 모델에 실제로 전달된 최종 프롬프트 (인핸서 ON 이면 다듬은 것)
    prompt: str
    # original_prompt: 사용자가 입력한 원문 (B4 §12 시드 재현성)
    original_prompt: str | None = None
    negative_prompt: str = ""
    width: int = 0
    height: int = 0
    steps: int = 0
    cfg: float = 0.0
    sampler: str = "euler_a"
    scheduler: str = "default"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    app: str = "Geuryeojwo"
    version: str = __version__
    engine: str = "Geurim-gyeol"
    elapsed_seconds: float = 0.0
    llm_model: str | None = None
    prompt_options: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "app": self.app,
            "version": self.version,
            "engine": self.engine,
            "seed": self.seed,
            "model": self.model,
            "prompt": self.prompt,
            "original_prompt": self.original_prompt,
            "negative_prompt": self.negative_prompt,
            "width": self.width,
            "height": self.height,
            "steps": self.steps,
            "cfg": self.cfg,
            "sampler": self.sampler,
            "scheduler": self.scheduler,
            "created_at": self.created_at,
            "elapsed_seconds": self.elapsed_seconds,
            "llm_model": self.llm_model,
            "prompt_options": self.prompt_options,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OutputMetadata:
        return cls(
            seed=data.get("seed", 0),
            model=data.get("model", "unknown"),
            prompt=data.get("prompt", ""),
            original_prompt=data.get("original_prompt"),
            negative_prompt=data.get("negative_prompt", ""),
            width=data.get("width", 1024),
            height=data.get("height", 1024),
            steps=data.get("steps", 20),
            cfg=data.get("cfg", 7.0),
            sampler=data.get("sampler", "euler_a"),
            scheduler=data.get("scheduler", "default"),
            created_at=data.get("created_at", datetime.now().isoformat(timespec="seconds")),
            app=data.get("app", "Geuryeojwo"),
            version=data.get("version", __version__),
            engine=data.get("engine", "Geurim-gyeol"),
            elapsed_seconds=data.get("elapsed_seconds", 0.0),
            llm_model=data.get("llm_model"),
            prompt_options=data.get("prompt_options", {}),
        )


class OutputManager:
    """출력 이미지/JSON 저장 및 관리.

    구조:
        outputs/
            2026-10-01/
                img_001_seed1234.png
                img_001_seed1234.json
                img_002_seed5678.png
                img_002_seed5678.json
    """

    def __init__(self, outputs_root: Path):
        self.outputs_root = outputs_root
        self.outputs_root.mkdir(parents=True, exist_ok=True)

    def save_output(
        self,
        image,
        metadata: OutputMetadata,
    ) -> tuple[Path, Path]:
        """이미지와 메타데이터 JSON을 저장하고 (png_path, json_path)를 반환한다."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        date_dir = self.outputs_root / date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        existing = sorted(date_dir.glob("img_*.png"))
        index = next_index(
            (p.name for p in existing),
            prefix="img_",
            # img_003_seed999.png → 3
            suffix_before="_seed",
        )

        png_name = f"img_{index:03d}_seed{metadata.seed}"
        png_path = date_dir / f"{png_name}.png"
        json_path = date_dir / f"{png_name}.json"

        image.save(png_path)
        json_path.write_text(
            json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return png_path, json_path

    def list_outputs(self) -> list[tuple[Path, Path]]:
        """모든 출력 (png, json) 쌍을 날짜별로 정렬하여 반환한다."""
        results = []
        for date_dir in sorted(self.outputs_root.glob("*/"), reverse=True):
            if not date_dir.is_dir():
                continue
            for png_path in sorted(date_dir.glob("img_*.png")):
                json_path = png_path.with_suffix(".json")
                if json_path.exists():
                    results.append((png_path, json_path))
        return results

    def get_output(self, png_path: Path) -> tuple[OutputMetadata, Path]:
        """이미지 경로로부터 메타데이터를 로드한다."""
        json_path = png_path.with_suffix(".json")
        if not json_path.exists():
            raise FileNotFoundError(f"metadata JSON not found: {json_path}")
        metadata = OutputMetadata.from_dict(
            json.loads(json_path.read_text(encoding="utf-8"))
        )
        return metadata, json_path

    def delete_output(self, png_path: Path) -> None:
        """이미지와 연관된 JSON을 함께 삭제한다."""
        json_path = png_path.with_suffix(".json")
        png_path.unlink(missing_ok=True)
        json_path.unlink(missing_ok=True)

    def get_output_dir(self) -> Path:
        """오늘 날짜의 출력 디렉토리를 반환한다."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        date_dir = self.outputs_root / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        return date_dir
