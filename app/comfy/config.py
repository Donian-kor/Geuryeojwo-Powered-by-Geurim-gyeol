"""ComfyUI 접속 설정.

config/comfyui.json 을 읽고 접속 정보를 제공한다.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8188,
    "timeout_seconds": 300,
    "connect_timeout_seconds": 5,
    "auto_launch": False,
    "launch_command": "",
    "launch_working_dir": "",
    "launch_wait_seconds": 90,
    "model_folders": [
        "checkpoints",
        "diffusion_models",
        "vae",
        "loras",
        "text_encoders",
    ],
    # ComfyUI 의 models 폴더. 모델이 없으면 '어디에 넣어야 하는지'
    # 알려줄 수 없으므로 등록 화면의 안내에 쓰인다.
    "models_dir": "",
}


def _windows_split(command: str) -> list[str]:
    """Windows 명령줄을 인자 목록으로 나눈다.

    subprocess 가 list 를 받으면 알아서 인자 인용을 처리하므로,
    여기의 목표는 따옴표를 제거해 경로를 온전하게 만드는 것이다.

    shlex.split(posix=False) 는 따옴표를 제거하지 않고 중첩따옴표도
    처리하지 못해 Windows 경로에 쓸 수 없다.
    """
    parts: list[str] = []
    current: list[str] = []
    quote = ""          # 현재 열려 있는 따옴표 문자
    escaped = False     # 직전 문자가 백슬래시였는가

    for char in command:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\" and quote == '"':
            # 따옴표 안의 백슬래시는 그대로 두되, 다음 문자가 따옴표면
            # 이스케이프 여부를 기억한다
            current.append(char)
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ""
            else:
                current.append(char)
            continue
        if char in ('"', "'"):
            quote = char
            continue
        if char.isspace():
            if current:
                parts.append("".join(current))
                current = []
            continue
        current.append(char)

    if current:
        parts.append("".join(current))
    return parts


def _env_root(var: str) -> Path | None:
    """환경 변수를 경로로. 없으면 None (빈 문자열로 Path 를 만들면 상대경로가 된다)."""
    value = os.environ.get(var)
    return Path(value) if value else None


def _looks_like_models_dir(root: Path, folders) -> bool:
    """모델 하위 폴더가 하나라도 있어야 모델 폴더로 본다."""
    try:
        return root.is_dir() and any((root / f).is_dir() for f in folders)
    except OSError:
        return False  # 접근 권한이 없는 경로에서 죽지 않게


def guess_models_dir(folders=None, roots=None) -> str:
    """ComfyUI 의 models 폴더를 찾아 경로를 돌려준다. 못 찾으면 빈 문자열.

    설치 방식마다 경로가 달라 매번 물어봐야 하는데,
    흔한 위치 몇 곳만 훑어본다. 없으면 빈 문자열을 돌려
    호출자가 사용자에게 한 번만 물어보게 한다.

    Returns:
        str: 찾은 models 폴더 경로. 없으면 ""
    """
    folders = folders or DEFAULT_CONFIG["model_folders"]
    if roots is None:
        candidates = []
        local = _env_root("LOCALAPPDATA")
        roaming = _env_root("APPDATA")
        if local is not None:
            candidates.append(local / "Comfy-Desktop" / "ComfyUI-Shared" / "models")
        if roaming is not None:
            candidates.append(roaming / "ComfyUI" / "models")
        candidates.append(Path.cwd() / "ComfyUI" / "models")
        candidates.append(Path.cwd() / "models")
        roots = candidates
    for root in roots:
        if _looks_like_models_dir(Path(root), folders):
            return str(root)
    return ""


@dataclass
class ComfyUIConfig:
    """ComfyUI 접속 설정."""

    host: str = "127.0.0.1"
    port: int = 8188
    timeout_seconds: int = 300
    connect_timeout_seconds: int = 5
    auto_launch: bool = False
    launch_command: str = ""
    launch_working_dir: str = ""
    launch_wait_seconds: int = 90
    model_folders: list[str] = field(default_factory=list)
    # ComfyUI 의 models 폴더. 비어 있으면 guess_models_dir() 로 찾고,
    # 그것도 없으면 사용자에게 한 번 물어본 뒤 여기에 기억한다.
    models_dir: str = ""

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws"

    def build_launch_argv(self) -> list[str]:
        """실행에 쓸 인자 목록을 만든다.

        공백이 포함된 경로도 안전하게 분리한다.
        Windows 는 shlex 가 따옴표를 그대로 남기므로 직접 처리한다
        (그대로 두면 "C:\\Program Files\\..." 처럼 깨진 경로가 그대로 실행된다).

        Returns:
            list[str]: 실행 인자. launch_command 가 비어 있으면 빈 목록.
        """
        if not self.launch_command.strip():
            return []
        parts = self._split_command()

        if not any(p == "--api" for p in parts):
            parts.append("--api")
        if not any(p == "--port" for p in parts):
            parts.extend(["--port", str(self.port)])
        return parts

    def _split_command(self) -> list[str]:
        """launch_command 를 인자 목록으로 분리한다."""
        command = self.launch_command.strip()

        if sys.platform.startswith("win"):
            return _windows_split(command)

        try:
            return shlex.split(command)
        except ValueError:
            # 따옴표가 맞지 않는 등 분리 실패 시 공백 기준으로 자른다
            return command.split()

    def launch(self, logger=None) -> subprocess.Popen | None:
        """ComfyUI 를 백그라운드로 실행한다.

        Returns:
            Popen | None: 실행 실패 사유는 logger 로 남기고 None 을 돌려준다.
        """
        argv = self.build_launch_argv()
        if not argv:
            if logger:
                logger.warning(
                    "auto_launch 가 켜져 있지만 launch_command 가 비어 있습니다."
                )
            return None

        cwd = self.launch_working_dir or None
        if cwd and not Path(cwd).is_dir():
            if logger:
                logger.error("launch_working_dir 가 존재하지 않습니다: %s", cwd)
            return None

        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(
                    # Windows에서 콘솔 창이 뜨지 않도록
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if sys.platform.startswith("win") else 0
                ),
            )
        except (OSError, ValueError) as exc:
            if logger:
                logger.error("ComfyUI 실행 실패: %s", exc)
            return None

        if logger:
            logger.info("ComfyUI 실행 (pid=%s, cwd=%s)", proc.pid, cwd or "현재 폴더")
        return proc

    @classmethod
    def load(cls, path: Path) -> "ComfyUIConfig":
        data = dict(DEFAULT_CONFIG)
        if path.exists():
            try:
                data.update(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return cls(
            host=data.get("host", "127.0.0.1"),
            port=int(data.get("port", 8188)),
            timeout_seconds=int(data.get("timeout_seconds", 300)),
            connect_timeout_seconds=int(data.get("connect_timeout_seconds", 5)),
            auto_launch=bool(data.get("auto_launch", False)),
            launch_command=data.get("launch_command", ""),
            launch_working_dir=data.get("launch_working_dir", ""),
            launch_wait_seconds=int(data.get("launch_wait_seconds", 90)),
            model_folders=list(data.get("model_folders", DEFAULT_CONFIG["model_folders"])),
            models_dir=str(data.get("models_dir", "")),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "host": self.host,
                    "port": self.port,
                    "timeout_seconds": self.timeout_seconds,
                    "connect_timeout_seconds": self.connect_timeout_seconds,
                    "auto_launch": self.auto_launch,
                    "launch_command": self.launch_command,
                    "launch_working_dir": self.launch_working_dir,
                    "launch_wait_seconds": self.launch_wait_seconds,
                    "model_folders": self.model_folders,
                    "models_dir": self.models_dir,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )