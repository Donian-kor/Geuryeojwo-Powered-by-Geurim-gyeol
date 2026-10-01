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

### VRAM 한도 설정 (v0.1 §8.4)

기본값은 **8 GB(보수적)** 입니다. 자기 PC 사양을 몰라도 안전하게 동작하도록
의도적으로 낮게 잡았습니다. GPU가 더 좋은 환경에서는 GUI 상단의
`VRAM 한도`에서 바꿀 수 있습니다.

| 기준 | 동작 | 권장 대상 |
|---|---|---|
| 기본값 (8 GB, 보수적) | GPU 사양과 무관하게 8 GB 사용 | VRAM 8GB 이하, 또는 사양을 모르는 경우 |
| 자동 감지 | 감지된 VRAM에서 0.8 GB를 뺀 값 | 자신의 GPU에 맞추고 싶을 때 (권장) |
| 사용자 지정 | 입력한 값 사용 | 정확한 수치를 알고 있을 때 |
| 제한 없음 | 예산 검사 생략 | 16GB 이상 고사양 PC |

두 가지 검사를 모두 통과해야 모델이 로드됩니다.

1. **예산 검사** — 선택한 기준(기본 8GB 등) 이내인가
2. **실제 GPU 검사** — 물리적으로 설치된 VRAM을 넘지 않는가

> `제한 없음`이어도 2번 검사는 항상 적용됩니다. 8GB GPU에 Flux(9GB)를
> 강제로 로드할 수는 없습니다.

`config/app_config.json`의 `memory` 항목에 저장됩니다.

```json
"memory": {
  "vram_limit_mode": "default",
  "vram_limit_gb": 8.0,
  "safety_margin_gb": 0.5
}
```

### 메모리 전략 — VRAM 부족 시 시스템 RAM 사용 (v0.1 §8.2)

ComfyUI의 `SHARED` VRAMState처럼, VRAM이 부족하면 **시스템 RAM으로 넘겨서
대신 실행**합니다. 사용자가 선택할 필요 없이 자동으로 결정됩니다.

| 단계 | 조건 | 동작 | 속도 |
|---|---|---|---|
| `full` | VRAM 예산에 들어감 | 모델 전체를 VRAM에 | 최고 |
| `offload` | VRAM 초과, RAM 여유 | 가중치를 RAM에 두고 필요 시 VRAM으로 | 20~30% 느림 |
| `reduced` | VRAM·RAM 모두 부족 | 해상도 75% + offload | 그보다 느림 |
| `impossible` | 둘 다 부족 | 실행 불가 + 안내 | — |

offload 방식은 세 가지를 지원하며 기본은 `model_cpu_offload`입니다.

- `model_cpu` (기본) — 컴포넌트 단위 오프로드. 안정적
- `group` — diffusers 0.35+ 그룹 오프로드. 가장 빠르고 효율적
- `sequential` — 레이어 단위. 가장 강하게 절약하지만 매우 느림

> offload를 쓸 때는 `.to(device)`를 호출하지 않습니다. 둘을 같이 쓰면
> diffusers가 오류를 냅니다. 코드가 이 제약을 자동으로 처리합니다.

GUI에서 눈으로 확인할 수 있습니다.

- 하단 상태바: `RAM: 15.4/31.1GB (50%)` · `VRAM: 2.1/7.9GB (27%)` 실시간 표시
- Model Information 패널: `System RAM` / `VRAM Budget` / `Memory Strategy`
- Dry Run: 사용할 전략과 적용될 해상도를 미리 안내

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
