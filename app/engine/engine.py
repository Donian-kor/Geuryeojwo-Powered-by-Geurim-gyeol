from __future__ import annotations
import json
import logging
from pathlib import Path
from .hardware.detector import detect_hardware
from .memory.manager import MemoryManager
from .memory.budget import VramBudgetManager
from .models.registry import ModelRegistry
from .prompt.engine import PromptEngine
from .image.pipeline import ImagePipelineManager
from .generation.controller import GenerationController
from .generation.task_runner import TaskRunner
from .logging.manager import LogManager
from .error.handler import ErrorHandler, ErrorType, RecoverySuggestion
from .validation.dry_run import DryRunMode, ModelValidator

_config_logger = logging.getLogger("geurim-gyeol.config")


def load_app_config(path: Path) -> dict:
    """app_config.json을 읽는다 (v0.1 §3.4 Configuration Driven)."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _config_logger.error("설정 파일 읽기 실패 (%s): %s", path, exc)
        return {}


def save_app_config(path: Path, config: dict) -> None:
    """app_config.json을 저장한다."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        _config_logger.error("설정 파일 저장 실패 (%s): %s", path, exc)


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
        self.config = load_app_config(root / "config" / "app_config.json")
        self.vram_budget = VramBudgetManager.from_config(self.config, self.hardware.vram_gb)
        self.memory = MemoryManager(self.logs.memory)
        self.registry = ModelRegistry(
            root / "models",
            root / "config" / "image_profiles.json",
            root / "config" / "user_models.json",
        )
        self.prompt = PromptEngine(
            root / "config" / "prompt_profiles.json",
            root / "config" / "negative_dictionary.json",
            self.logger,
            root / "config" / "llm_profiles.json",
        )
        self.image = ImagePipelineManager(
            self.hardware, self.memory, self.logger, budget=self.vram_budget
        )
        self.task_runner = TaskRunner(self.logger)
        self.error_handler = ErrorHandler(self.logs.error)
        self.generation = GenerationController(
            self, self.registry, self.prompt, self.memory, self.logger,
            root / "outputs",
            task_runner=self.task_runner,
            error_handler=self.error_handler,
            logs=self.logs,
        )
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

    def set_vram_limit(self, mode: str, custom_gb: float | None = None):
        """VRAM 제한 정책을 변경하고 저장한다 (v0.1 §3.4)."""
        budget = self.vram_budget.set_mode(mode, custom_gb)
        self.config.setdefault("memory", {}).update(self.vram_budget.to_config())
        save_app_config(self.root / "config" / "app_config.json", self.config)
        self.logger.info("VRAM 제한 변경: %s", budget.describe())
        return budget

    def analyze_hardware(self) -> "HardwareInfo":
        """하드웨어 분석 결과를 반환한다 (v0.1 §7, §44.8)."""
        return self.hardware

    def resolve_model_profile(self, image_model):
        """이미지 모델 프로필을 결정한다 (v0.1 §11, §44.8)."""
        return self.registry.profile_for(Path(image_model))

    def enhance_prompt(self, user_input: str, architecture: str = "sdxl", llm_path=None):
        """LLM으로 프롬프트를 확장한다 (v0.1 §13, §44.8).

        LLM을 명시적으로 해제하므로 호출자가 메모리를 정리해야 한다.
        """
        from .llm.llama_cpp import LocalLLM

        llm = None
        try:
            if llm_path:
                llm = LocalLLM(
                    Path(llm_path),
                    self.hardware.device,
                    self.logger,
                    profile=self.prompt.llm_profile_for(llm_path),
                ).load()
            result = self.prompt.build(user_input, architecture, llm, llm_path)
            return result.positive, result.negative
        finally:
            if llm:
                llm.unload()
                del llm
            self.memory.cleanup()

    def unload_llm(self) -> None:
        """LLM 완전 해제 후 메모리를 정리한다 (v0.1 §8.1)."""
        self.memory.cleanup()
        snap = self.memory.take_snapshot("after_llm_unload")
        self.logger.info("LLM unloaded — VRAM free=%s", snap.vram_free_gb)

    def cleanup_memory(self) -> None:
        """메모리 정리 (§8)."""
        self.memory.cleanup()

    def load_image_model(self, image_model, architecture: str | None = None) -> None:
        """이미지 모델을 로드한다 (v0.1 §44.8)."""
        path = Path(image_model)
        arch = architecture or self.registry.profile_for(path).architecture
        self.image.load(path, arch)

    def generate_image(self, prompt: str, profile, width=1024, height=1024, steps=30, cfg=7.0, seed=-1):
        """이미지를 생성하고 결과를 반환한다 (v0.1 §44.8)."""
        negative = self.prompt.negative(profile.architecture)
        image, used_seed = self.image.generate(
            prompt, negative, width, height, steps, cfg, seed
        )
        return {"image": image, "seed": used_seed, "model": profile.architecture}

    def unload_image_model(self) -> None:
        """이미지 모델을 해제한다 (v0.1 §44.8)."""
        self.image.unload()

    def shutdown(self) -> None:
        """ENGINE SHUTDOWN — unload any loaded models."""
        self.logger.info("GeurimGyeolEngine shutdown")
        self.image.unload()
        self.memory.cleanup()
        self._initialized = False
