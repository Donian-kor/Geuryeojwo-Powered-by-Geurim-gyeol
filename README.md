# Geuryeojwo v0.1

**Local AI Image Studio — Powered by Geurim-gyeol**

Geuryeojwo is a standalone Python application for local prompt enhancement and image generation. The application does not start or call ComfyUI, LM Studio, Ollama, Stable Diffusion WebUI, Docker, or another local AI server.

## Architecture

`PySide6 GUI → Geurim-gyeol Engine → Local GGUF LLM → Prompt Engine → Memory Manager → Native Diffusers Image Engine → PNG/JSON`

**Geurim-gyeol** is the internal orchestration engine, not a model. It manages hardware detection, model discovery, prompt policy, LLM lifecycle, memory cleanup, image-model lifecycle, generation, and metadata.

## v0.1 model layout

```text
models/
├── llm/         # GGUF prompt-enhancement models
├── checkpoints/ # local Diffusers directories or supported SD single-file checkpoints
├── vae/         # optional VAE assets
└── lora/        # reserved for v0.1 extension adapters
```

The first native single-file path in v0.1 covers SD1.5/SD2.1/SDXL-style Stable Diffusion checkpoints through Diffusers. Flux and other architectures use the adapter boundary and should be supplied as a Diffusers-compatible local directory until a dedicated adapter is added.

## Run

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

No external AI server should be running or configured.

### GPU (권장) — CUDA 빌드 설치

기본 `pip install torch`는 **CPU 전용 빌드**가 설치되어 GPU를 사용하지 못합니다.
GPU를 사용하려면 PyTorch 공식 CUDA 인덱스로 설치해야 합니다.

```bash
# CUDA 13 (RTX 50-series / Blackwell 권장)
pip install torch --index-url https://download.pytorch.org/whl/cu130

# CUDA 12.8 (RTX 40-series 이하)
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

설치 후 확인:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

`True`가 나오면 GPU를 사용합니다. `False`면 CPU 폴백(float32)으로 동작하며
실행 시 GUI 상단에 원인과 해결 방법이 표시됩니다.

### 폴백 동작 (v0.1 §7)

| 환경 | device | 정밀도 | 비고 |
|---|---|---|---|
| CUDA | `cuda` | float16 | VRAM 감지, OOM 보호 적용 |
| Apple Silicon | `mps` | float16 | VRAM 미지원 |
| 그 외 | `cpu` | float32 | 속도 저하, 해상도·steps 제한 필요 |

## Memory lifecycle

1. Detect CUDA/MPS/CPU.
2. Load the optional GGUF LLM in-process.
3. Generate an optimized image prompt.
4. Unload the LLM and clear Python/accelerator caches.
5. Load the image model in-process.
6. Generate and save PNG + JSON metadata.
7. Unload the image pipeline and clear caches.

## Output

Images are written to `outputs/YYYY-MM-DD/` with a matching JSON metadata file containing prompt, seed, model, dimensions, steps, CFG, engine version, and elapsed time.

Sessions are written to `sessions/YYYY-MM-DD/HHmmss-N/` and contain `session.json` plus a copy of each generated image and its metadata.

## Configuration

| File | Purpose |
|---|---|
| `config/image_profiles.json` | Per-architecture model profiles (VRAM estimate, steps, sampler) |
| `config/prompt_profiles.json` | Per-architecture prompt style (tag/sentence) and negative policy |
| `config/negative_dictionary.json` | Negative prompt tag dictionary |
| `config/llm_profiles.json` | LLM capability profile (context, temperature, multilingual) |
| `config/user_models.json` | User Override — force an architecture for a specific filename |
| `config/app_config.json` | Application settings |

Architecture detection priority: user override → explicit config → registry → filename heuristic → default.

## Test

```bash
pytest
```

The suite covers hardware detection, memory lifecycle, prompt policy, model registry and override, task state machine, error/OOM recovery, session/output persistence, and adapter contracts.
