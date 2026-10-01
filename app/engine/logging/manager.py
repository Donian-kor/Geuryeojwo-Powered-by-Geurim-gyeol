from __future__ import annotations

import logging
from pathlib import Path


class LogManager:
    """4-tier logging system (v0.1 §30).

    logs/
        application.log  - 일반 애플리케이션 로그 (INFO+)
        generation.log   - 이미지 생성 워크플로 로그
        memory.log       - 메모리/VRAM 추적 로그
        error.log        - 오류 및 예외 로그 (ERROR+)
    """

    APPLICATION = "application"
    GENERATION = "generation"
    MEMORY = "memory"
    ERROR = "error"

    def __init__(self, logs_root: Path):
        self.logs_root = logs_root
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self._loggers: dict[str, logging.Logger] = {}
        self._setup_loggers()

    def _setup_loggers(self) -> None:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        for name, filename, level, propagate in [
            (self.APPLICATION, "application.log", logging.INFO, True),
            (self.GENERATION, "generation.log", logging.INFO, False),
            (self.MEMORY, "memory.log", logging.DEBUG, False),
            (self.ERROR, "error.log", logging.ERROR, False),
        ]:
            logger = logging.getLogger(f"geurim-gyeol.{name}")
            logger.setLevel(level)
            logger.propagate = propagate

            if logger.handlers:
                for h in logger.handlers:
                    h.close()
                logger.handlers.clear()

            handler = logging.FileHandler(
                self.logs_root / filename, encoding="utf-8"
            )
            handler.setFormatter(formatter)
            handler.setLevel(level)
            logger.addHandler(handler)

            stream = logging.StreamHandler()
            stream.setFormatter(formatter)
            stream.setLevel(logging.WARNING if name == self.ERROR else level)
            logger.addHandler(stream)

            self._loggers[name] = logger

    def get_logger(self, name: str) -> logging.Logger:
        """지정된 범주의 로거를 반환한다."""
        if name in self._loggers.values():
            return name
        base_name = name.rsplit(".", 1)[-1]
        for category in (self.APPLICATION, self.GENERATION, self.MEMORY, self.ERROR):
            if category in base_name:
                return self._loggers[category]
        return self._loggers[self.APPLICATION]

    @property
    def application(self) -> logging.Logger:
        return self._loggers[self.APPLICATION]

    @property
    def generation(self) -> logging.Logger:
        return self._loggers[self.GENERATION]

    @property
    def memory(self) -> logging.Logger:
        return self._loggers[self.MEMORY]

    @property
    def error(self) -> logging.Logger:
        return self._loggers[self.ERROR]

    def log_model_load(self, model_name: str, model_type: str) -> None:
        """Model Load 기록 (v.01 §30 기록)."""
        msg = f"Model loaded: {model_name} ({model_type})"
        self.application.info(msg)
        self.generation.info(msg)

    def log_model_unload(self, model_name: str) -> None:
        """Model Unload 기록."""
        msg = f"Model unloaded: {model_name}"
        self.application.info(msg)
        self.generation.info(msg)

    def log_vram(self, allocated: float, reserved: float, total: float) -> None:
        """VRAM 추적 기록."""
        msg = f"VRAM: allocated={allocated:.1f}GB, reserved={reserved:.1f}GB, total={total:.1f}GB"
        self.memory.debug(msg)
        self.application.debug(msg)

    def log_ram(self, used: float, total: float, percent: float) -> None:
        """RAM 추적 기록."""
        msg = f"RAM: {used:.1f}/{total:.1f}GB ({percent:.1f}%)"
        self.memory.debug(msg)
        self.application.debug(msg)

    def log_generation_time(self, elapsed: float) -> None:
        """Generation Time 기록."""
        self.generation.info(f"Generation completed in {elapsed:.2f}s")
        self.application.info(f"Generation time: {elapsed:.2f}s")

    def log_prompt_policy(self, original: str, enhanced: str, policy_used: str) -> None:
        """Prompt Policy 기록."""
        msg = f"Prompt policy '{policy_used}': '{original}' -> '{enhanced}'"
        self.generation.info(msg)
        self.application.debug(msg)

    def log_model_detection(self, models: dict[str, list]) -> None:
        """Model Detection 기록."""
        for model_type, model_list in models.items():
            for m in model_list:
                self.application.info(f"Detected {model_type}: {m}")

    def log_error(self, error: Exception, context: str = "") -> None:
        """Error 기록 (v.01 §30 Error)."""
        msg = f"{context}: {type(error).__name__}: {error}" if context else f"{type(error).__name__}: {error}"
        self.error.error(msg, exc_info=True)
        self.application.error(msg, exc_info=True)

    def shutdown(self) -> None:
        """모든 핸들러를 닫고 로거를 정리한다."""
        for logger in self._loggers.values():
            for handler in logger.handlers:
                handler.flush()
                handler.close()
            logger.handlers.clear()
