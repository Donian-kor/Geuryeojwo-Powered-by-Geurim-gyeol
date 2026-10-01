from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DryRunResult:
    """Dry Run 검증 결과 (v0.1 §27).

    실제 이미지를 생성하지 않고 하드웨어/메모리 상태를 검증한다.
    """

    hardware_backend: str
    hardware_name: str
    hardware_dtype: str

    llm_model: str | None
    llm_path: Path | None

    image_model: str
    image_path: Path
    architecture: str

    estimated_llm_memory_gb: float | None = None
    estimated_image_memory_gb: float | None = None
    available_vram_gb: float | None = None
    total_vram_gb: float | None = None
    available_ram_gb: float | None = None
    total_ram_gb: float | None = None

    prompt_style: str = "natural"
    uses_negative_prompt: bool = True
    negative_prompt_available: bool = True
    vram_budget: str = ""
    memory_strategy: str = ""
    offload_mode: str = "none"
    suggested_resolution: str = ""

    ready: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "hardware": {
                "backend": self.hardware_backend,
                "name": self.hardware_name,
                "dtype": self.hardware_dtype,
            },
            "llm": {
                "model": self.llm_model,
                "path": str(self.llm_path) if self.llm_path else None,
                "estimated_memory_gb": self.estimated_llm_memory_gb,
            },
            "image": {
                "model": self.image_model,
                "architecture": self.architecture,
                "path": str(self.image_path),
                "estimated_memory_gb": self.estimated_image_memory_gb,
            },
            "memory": {
                "vram_available_gb": self.available_vram_gb,
                "vram_total_gb": self.total_vram_gb,
                "ram_available_gb": self.available_ram_gb,
                "ram_total_gb": self.total_ram_gb,
            },
            "prompt": {
                "style": self.prompt_style,
                "uses_negative_prompt": self.uses_negative_prompt,
            },
            "result": {
                "ready": self.ready,
                "warnings": self.warnings,
                "errors": self.errors,
            },
        }


@dataclass
class ModelValidationResult:
    """Model 파일 검증 결과 (v.01 §28)."""

    model_path: Path
    valid: bool
    model_type: str
    architecture: str
    file_size_gb: float
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class DryRunMode:
    """Dry Run Mode (v.01 §27).

    실제 이미지를 생성하지 않고 하드웨어/메모리/모델을 검증한다.
    """

    LLM_ESTIMATED_SIZES_GB = {
        "qwen": 2.5,
        "qwen2": 4.0,
        "qwen2.5": 7.0,
        "llama": 4.0,
        "llama2": 4.0,
        "llama3": 8.0,
        "gemma": 2.0,
        "phi": 2.5,
        "default": 4.0,
    }

    def __init__(self, engine, logger=None):
        self.engine = engine
        self.logger = logger

    def run(
        self,
        image_path: Path,
        llm_path: Path | None = None,
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        cfg: float = 7.0,
        seed: int = -1,
    ) -> DryRunResult:
        """Dry Run 검증을 수행한다."""
        result = DryRunResult(
            hardware_backend=self.engine.hardware.backend,
            hardware_name=self.engine.hardware.name,
            hardware_dtype=self.engine.hardware.dtype,
            llm_model=llm_path.name if llm_path else None,
            llm_path=llm_path,
            image_model=image_path.name,
            image_path=image_path,
            architecture=self._detect_architecture(image_path),
        )

        # 메모리 스냅샷
        snap = self.engine.memory.take_snapshot("dry_run")
        result.available_vram_gb = snap.vram_free_gb
        result.total_vram_gb = snap.vram_total_gb
        result.available_ram_gb = snap.ram_free_gb
        result.total_ram_gb = snap.ram_total_gb

        # LLM 메모리 추정
        if llm_path:
            result.estimated_llm_memory_gb = self._estimate_llm_memory(llm_path)
        else:
            result.estimated_llm_memory_gb = 0.0

        # 이미지 모델 메모리 추정
        try:
            result.estimated_image_memory_gb = self.engine.image.estimate_memory(
                result.architecture
            )
        except Exception:
            result.estimated_image_memory_gb = 5.0

        # Prompt 스타일 확인
        policy = self.engine.prompt.policy.get_policy(result.architecture)
        result.prompt_style = policy.get("prompt_style", "natural")
        result.uses_negative_prompt = policy.get("use_negative", True)
        result.negative_prompt_available = bool(
            self.engine.prompt.dictionary.get("quality_tags")
            or self.engine.prompt.dictionary.get("anatomy_tags")
        )

        # 검증
        self._validate(result, width, height, steps, cfg, seed)

        if self.logger:
            status = "READY" if result.ready else "NOT READY"
            self.logger.info(
                "Dry Run completed: %s (VRAM: %.1fGB available, est. image: %.1fGB)",
                status,
                result.available_vram_gb or 0,
                result.estimated_image_memory_gb or 0,
            )

        return result

    def _detect_architecture(self, image_path: Path) -> str:
        """이미지 모델 파일로부터 아키텍처 추정 (v0.1 §11)."""
        name = image_path.name.lower()
        for keyword, arch in (
            ("flux", "flux"),
            ("sd3", "sd3"),
            ("stable-diffusion-3", "sd3"),
            ("sdxl", "sdxl"),
            ("sd_xl", "sdxl"),
            ("xl_base", "sdxl"),
            ("sd21", "sd21"),
            ("sd_21", "sd21"),
            ("sd15", "sd15"),
            ("sd_15", "sd15"),
            ("v1-5", "sd15"),
        ):
            if keyword in name:
                return arch
        return "sdxl"

    def _estimate_llm_memory(self, llm_path: Path) -> float | None:
        """LLM 메모리 사용량 추정 (GB)."""
        try:
            size_bytes = llm_path.stat().st_size
            size_gb = size_bytes / (1024**3)
        except Exception:
            return None

        name = llm_path.name.lower()
        for key in self.LLM_ESTIMATED_SIZES_GB:
            if key in name:
                return self.LLM_ESTIMATED_SIZES_GB[key]
        return round(size_gb * 1.2, 1)

    def _validate(
        self,
        result: DryRunResult,
        width: int,
        height: int,
        steps: int,
        cfg: float,
        seed: int,
    ) -> None:
        """검증 체크 및 결과 설정."""
        # 모델 파일 존재 확인
        if result.image_path and not result.image_path.exists():
            result.errors.append(f"이미지 모델 파일을 찾을 수 없습니다: {result.image_path}")

        if result.llm_path and not result.llm_path.exists():
            result.errors.append(f"LLM 모델 파일을 찾을 수 없습니다: {result.llm_path}")

        # 아키텍처 지원 여부
        if not self.engine.image.can_handle(result.architecture):
            result.errors.append(
                f"지원하지 않는 아키텍처: {result.architecture}"
            )

        total_est = (result.estimated_llm_memory_gb or 0) + (
            result.estimated_image_memory_gb or 0
        )

        # 메모리 전략 (v0.1 §8.2)
        strategy = self.engine.image.plan_strategy(
            result.architecture, width, height, steps
        )
        result.memory_strategy = strategy.describe()
        result.offload_mode = strategy.offload.value
        if strategy.suggested_width:
            result.suggested_resolution = (
                f"{strategy.suggested_width}x{strategy.suggested_height}"
            )

        # VRAM 검증 (예산 정책 + 실제 사용 가능량)
        budget = self.engine.vram_budget
        result.vram_budget = budget.describe()

        ok, message = budget.can_fit(total_est)
        uses_offload = strategy.uses_offload

        if not ok and not uses_offload:
            if result.total_vram_gb and total_est > result.total_vram_gb:
                result.errors.append(
                    f"예상 VRAM 사용량 ({total_est:.1f} GB)이 "
                    f"전체 VRAM ({result.total_vram_gb:.1f} GB)을 초과합니다"
                )
            else:
                result.errors.append(f"VRAM 예산 초과 — {message}")
        elif strategy.tier.value == "impossible":
            result.errors.append(f"메모리 부족 — {strategy.reason}")
        else:
            if not ok:
                result.warnings.append(
                    f"VRAM 예산 초과 — 시스템 RAM을 사용해 실행합니다 ({strategy.speed_hint})"
                )
            elif result.available_vram_gb and total_est > result.available_vram_gb:
                result.warnings.append(
                    f"VRAM 여유 부족: 예상 {total_est:.1f} GB, "
                    f"사용 가능 {result.available_vram_gb:.1f} GB"
                )
            if strategy.suggested_resolution:
                result.warnings.append(
                    f"메모리 절약 설정이 적용됩니다: {result.suggested_resolution}"
                )

        # 파라미터 검증
        if width * height > 2048 * 2048:
            result.warnings.append("해상도가 높아 OOM 위험이 있습니다")
        if steps > 50:
            result.warnings.append("Steps가 많아 생성 시간이 오래 걸립니다")
        if cfg < 5.0:
            result.warnings.append("CFG가 낮아 프롬프트 반영도가 낮을 수 있습니다")

        # CPU Safe Mode
        if result.hardware_backend == "cpu":
            result.warnings.append("CPU 모드: 생성 속도가 느릴 수 있습니다")
            result.warnings.append("Memory 제한으로 인해 OOM 위험이 높습니다")

        result.ready = len(result.errors) == 0


class ModelValidator:
    """Model 파일 검증기 (v.01 §28, PHASE 11 Model Validation)."""

    MIN_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

    def __init__(self, logger=None):
        self.logger = logger

    def validate_model(self, model_path: Path) -> ModelValidationResult:
        """모델 파일 검증."""
        import os

        if not model_path.exists():
            return ModelValidationResult(
                model_path=model_path,
                valid=False,
                model_type="unknown",
                architecture="unknown",
                file_size_gb=0.0,
                errors=[f"파일을 찾을 수 없습니다: {model_path}"],
            )

        file_size = model_path.stat().st_size
        file_size_gb = round(file_size / (1024**3), 2)

        result = ModelValidationResult(
            model_path=model_path,
            valid=True,
            model_type=self._detect_model_type(model_path),
            architecture=self._detect_architecture(model_path),
            file_size_gb=file_size_gb,
        )

        if file_size < self.MIN_FILE_SIZE_BYTES:
            result.errors.append(f"파일 크기가 너무 작습니다 ({file_size_gb} GB < 10MB)")
            result.valid = False

        if model_path.suffix.lower() in (".gguf",):
            self._validate_gguf(model_path, result)
        elif model_path.suffix.lower() in (".safetensors", ".ckpt"):
            self._validate_safetensors_or_ckpt(model_path, result)
        else:
            result.warnings.append("알 수 없는 파일 형식입니다")

        return result

    def _detect_model_type(self, path: Path) -> str:
        name = path.name.lower()
        if name.endswith(".gguf"):
            return "llm_gguf"
        if name.endswith((".safetensors", ".ckpt", ".pt")):
            return "image_model"
        return "unknown"

    def _detect_architecture(self, path: Path) -> str:
        name = path.name.lower()
        for keyword, arch in (
            ("flux", "flux"),
            ("sd3", "sd3"),
            ("stable-diffusion-3", "sd3"),
            ("sdxl", "sdxl"),
            ("sd_xl", "sdxl"),
            ("xl_base", "sdxl"),
            ("sd21", "sd21"),
            ("sd_21", "sd21"),
            ("sd15", "sd15"),
            ("sd_15", "sd15"),
            ("v1-5", "sd15"),
        ):
            if keyword in name:
                return arch
        for keyword, arch in (("qwen", "qwen"), ("llama", "llama"), ("gemma", "gemma")):
            if keyword in name:
                return arch
        return "unknown"

    def _validate_gguf(self, path: Path, result: ModelValidationResult) -> None:
        """GGUF 파일 검증 (헤더 체크)."""
        try:
            with open(path, "rb") as f:
                magic = f.read(4)
            if magic != b"GGUF":
                result.errors.append("GGUF 마법Bytes가 올바르지 않습니다 (파일 손상)")
                result.valid = False
            else:
                result.warnings.append("GGUF 헤더 검증 완료")
        except Exception as e:
            result.errors.append(f"GGUF 파일 읽기 실패: {e}")
            result.valid = False

    def _validate_safetensors_or_ckpt(self, path: Path, result: ModelValidationResult) -> None:
        """SAFETENSORS/CKPT 파일 검증."""
        try:
            import safetensors
            if path.suffix.lower() == ".safetensors":
                from safetensors import safe_open
                with safe_open(path, framework="pt") as f:
                    if not f.keys():
                        result.errors.append("safetensors 파일에 키가 없습니다 (파일 손상)")
                        result.valid = False
                result.warnings.append("safetensors 메타데이터 검증 완료")
        except ImportError:
            result.warnings.append("safetensors 미설치: 검증 생략")
        except Exception as e:
            result.errors.append(f"파일 검증 중 오류: {e}")
            result.valid = False
