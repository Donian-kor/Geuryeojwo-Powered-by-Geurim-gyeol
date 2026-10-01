"""ComfyUI 접속 설정 (v0.2 §4.1).

config/comfyui.json 을 읽고 접속 정보를 제공한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8188,
    "timeout_seconds": 300,
    "connect_timeout_seconds": 5,
    "auto_launch": False,
    "launch_command": "",
    "model_folders": [
        "checkpoints",
        "diffusion_models",
        "vae",
        "loras",
        "text_encoders",
    ],
}


@dataclass
class ComfyUIConfig:
    """ComfyUI 접속 설정."""

    host: str = "127.0.0.1"
    port: int = 8188
    timeout_seconds: int = 300
    connect_timeout_seconds: int = 5
    auto_launch: bool = False
    launch_command: str = ""
    model_folders: list[str] = field(default_factory=list)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws"

    @property
    def launch_args(self) -> list[str]:
        """--api 플래그를 포함한 실행 인자 목록."""
        if not self.launch_command:
            return []
        parts = self.launch_command.split()
        if "--api" not in parts:
            parts.append("--api")
        if "--port" not in parts:
            parts.extend(["--port", str(self.port)])
        return parts

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
            model_folders=list(data.get("model_folders", DEFAULT_CONFIG["model_folders"])),
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
                    "model_folders": self.model_folders,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )