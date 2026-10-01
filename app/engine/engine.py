from __future__ import annotations
import logging
from pathlib import Path
from .hardware.detector import detect_hardware
from .memory.manager import MemoryManager
from .models.registry import ModelRegistry
from .prompt.engine import PromptEngine
from .image.pipeline import NativeImageEngine
from .generation.controller import GenerationController

class GeurimGyeolEngine:
    """Core Local AI Orchestration Engine used by Geuryeojwo."""
    def __init__(self, root: Path):
        self.root = root
        self.logger = logging.getLogger("geurim-gyeol")
        self.hardware = detect_hardware()
        self.memory = MemoryManager()
        self.registry = ModelRegistry(root / "models", root / "config" / "image_profiles.json")
        self.prompt = PromptEngine(root / "config" / "prompt_profiles.json", root / "config" / "negative_dictionary.json", self.logger)
        self.image = NativeImageEngine(self.hardware, self.memory, self.logger)
        self.generation = GenerationController(self, self.registry, self.prompt, self.memory, self.logger, root / "outputs")

    def scan_models(self):
        return self.registry.scan_llm(), self.registry.scan_image()
