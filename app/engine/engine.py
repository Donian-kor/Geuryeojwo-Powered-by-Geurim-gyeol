from __future__ import annotations
import logging
from pathlib import Path
from .hardware.detector import detect_hardware
from .memory.manager import MemoryManager
from .models.registry import ModelRegistry
from .prompt.engine import PromptEngine
from .image.pipeline import ImagePipelineManager
from .generation.controller import GenerationController
from .generation.task_runner import TaskRunner
from .logging.manager import LogManager
from .error.handler import ErrorHandler, ErrorType, RecoverySuggestion
from .validation.dry_run import DryRunMode, ModelValidator


class GeurimGyeolEngine:
    """Core Local AI Orchestration Engine used by Geuryeojwo (v0.1 §44.8).

    Lifecycle:
        CREATED → INITIALIZED → HARDWARE_READY → MODEL_READY
        → LLM_LOADING → PROMPT_PROCESSING → LLM_UNLOADING
        → MEMORY_CLEANUP → IMAGE_LOADING → IMAGE_GENERATING
        → IMAGE_DECODING → RESULT_READY → IMAGE_UNLOADING → READY/SHUTDOWN
    """

    def __init__(self, root: Path):
        self.root = root
        self.logs = LogManager(root / "logs")
        self.logger = self.logs.get_logger("engine")
        self.hardware = detect_hardware()
        self.memory = MemoryManager(self.logs.memory)
        self.registry = ModelRegistry(
            root / "models", root / "config" / "image_profiles.json"
        )
        self.prompt = PromptEngine(
            root / "config" / "prompt_profiles.json",
            root / "config" / "negative_dictionary.json",
            self.logger,
        )
        self.image = ImagePipelineManager(self.hardware, self.memory, self.logger)
        self.generation = GenerationController(
            self, self.registry, self.prompt, self.memory, self.logger,
            root / "outputs"
        )
        self.task_runner = TaskRunner(self.logger)
        self.error_handler = ErrorHandler(self.logs.error)
        self.dry_runner = DryRunMode(self, self.logs.application)
        self.model_validator = ModelValidator(self.logger)
        self._initialized = False

    def initialize(self) -> None:
        """ENGINE INITIALIZED (v0.1 §44.9)."""
        self.logger.info("GeurimGyeolEngine initialized — hardware: %s", self.hardware.backend)
        self.logs.log_model_detection({
            "LLM": [str(p) for p in self.registry.scan_llm()],
            "Image": [str(p) for p in self.registry.scan_image()],
        })
        self._initialized = True

    def scan_models(self):
        """Detect local LLM and image models."""
        llm_models, image_models = self.registry.scan_llm(), self.registry.scan_image()
        self.logs.log_model_detection({
            "LLM": [str(p) for p in llm_models],
            "Image": [str(p) for p in image_models],
        })
        return llm_models, image_models

    def shutdown(self) -> None:
        """ENGINE SHUTDOWN — unload any loaded models."""
        self.logger.info("GeurimGyeolEngine shutdown")
        self.image.unload()
        self.memory.cleanup()
        self._initialized = False
