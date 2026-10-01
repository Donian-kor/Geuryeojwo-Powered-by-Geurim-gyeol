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
