from __future__ import annotations
import logging
from pathlib import Path
from .hardware.detector import detect_hardware
from .memory.manager import MemoryManager
from .models.registry import ModelRegistry
from .prompt.engine import PromptEngine
from .image.pipeline import ImagePipelineManager
from .generation.controller import GenerationController


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
        self.logger = logging.getLogger("geurim-gyeol")
        self.hardware = detect_hardware()
        self.memory = MemoryManager(self.logger)
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
        self._initialized = False

    def initialize(self) -> None:
        """ENGINE INITIALIZED (v0.1 §44.9)."""
        self.logger.info("GeurimGyeolEngine initialized — hardware: %s", self.hardware.backend)
        self._initialized = True

    def scan_models(self):
        """Detect local LLM and image models."""
        return self.registry.scan_llm(), self.registry.scan_image()

    def shutdown(self) -> None:
        """ENGINE SHUTDOWN — unload any loaded models."""
        self.logger.info("GeurimGyeolEngine shutdown")
        self.image.unload()
        self.memory.cleanup()
        self._initialized = False
