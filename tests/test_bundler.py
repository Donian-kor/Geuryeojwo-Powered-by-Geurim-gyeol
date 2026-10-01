"""모델 번들 조립 테스트 (v0.1 §9).

"폴더 하나 = 모델 하나" 구조에서 컴포넌트가 제대로 분류되는지 검증한다.
"""
import json

import pytest

from app.engine.models.bundler import build_bundle
from app.engine.models.scanner import ModelScanner

SDXL = [
    ("model.diffusion_model.input_blocks.0.0.weight", (320, 9, 3, 3)),
    ("model.diffusion_model.add_embedding.linear_1.weight", (320, 2816)),
    ("model.diffusion_model.out.0.weight", (4, 320, 3, 3)),
    ("first_stage_model.encoder.conv_in.weight", (128, 3, 3, 3)),
    ("cond_stage_model.transformer.text_model.embeddings.weight", (49408, 768)),
]

SD15 = [
    ("model.diffusion_model.input_blocks.0.0.weight", (320, 4, 3, 3)),
    ("model.diffusion_model.out.0.weight", (4, 320, 3, 3)),
]

VAE = [
    ("encoder.conv_in.weight", (128, 3, 3, 3)),
    ("decoder.conv_out.weight", (3, 128, 3, 3)),
]

LORA = [
    ("lora_unet_down.weight", (16, 320, 3, 3)),
    ("lora_unet_up.weight", (320, 16, 1, 1)),
]


def test_single_file_bundle(models_root, make_safetensors_file):
    """파일 하나만 있는 폴더도 번들로 조립된다."""
    folder = models_root / "MyModel"
    make_safetensors_file(folder, "whatever.safetensors", SDXL)

    bundle = build_bundle(folder)
    assert bundle is not None
    assert bundle.kind == "image"
    assert bundle.architecture == "sdxl"
    assert bundle.is_valid is True
    assert bundle.load_target == folder / "whatever.safetensors"


def test_folder_name_is_irrelevant(models_root, make_safetensors_file):
    """폴더 이름이 아무리 어색해도 헤더로 판별한다."""
    folder = models_root / "완전_무관한_이름_123"
    make_safetensors_file(folder, "x.safetensors", SD15)

    bundle = build_bundle(folder)
    assert bundle.architecture == "sd15"
    assert bundle.name == "완전_무관한_이름_123"


def test_llm_folder_detected(models_root):
    """GGUF가 있는 폴더는 LLM 번들로 인식한다."""
    folder = models_root / "Qwen"
    folder.mkdir()
    (folder / "qwen.gguf").write_bytes(b"GGUF" + b"\0" * 64)

    bundle = build_bundle(folder)
    assert bundle.kind == "llm"
    assert bundle.architecture == "llm"
    assert bundle.load_target.suffix == ".gguf"


def test_diffusers_folder_detected(models_root):
    """model_index.json이 있는 폴더는 Diffusers 모델로 인식한다."""
    folder = models_root / "flux1-dev"
    folder.mkdir()
    (folder / "model_index.json").write_text(json.dumps({
        "_class_name": "FluxPipeline",
    }), encoding="utf-8")

    bundle = build_bundle(folder)
    assert bundle.is_diffusers_dir is True
    assert bundle.architecture == "flux"
def test_optional_vae_and_lora_in_flat_folder(models_root, make_safetensors_file):
    """서브폴더 없이 VAE/LoRA를 함께 두어도 인식한다."""
    folder = models_root / "Full"
    make_safetensors_file(folder, "model.safetensors", SDXL)
    make_safetensors_file(folder, "custom_vae.safetensors", VAE)
    make_safetensors_file(folder, "style.safetensors", LORA)

    bundle = build_bundle(folder)
    assert bundle.architecture == "sdxl"
    assert bundle.vae is not None
    assert len(bundle.loras) == 1


def test_optional_subfolders_also_work(models_root, make_safetensors_file):
    """정돈용 서브폴더(vae/, lora/)도 동일하게 동작한다."""
    folder = models_root / "Organized"
    make_safetensors_file(folder, "model.safetensors", SDXL)
    make_safetensors_file(folder / "vae", "custom.safetensors", VAE)
    make_safetensors_file(folder / "lora", "style.safetensors", LORA)

    bundle = build_bundle(folder)
    assert bundle.architecture == "sdxl"
    assert bundle.vae is not None
    assert len(bundle.loras) == 1


def test_subfolder_vae_wins_over_flat(models_root, make_safetensors_file):
    """번들 ckpt에 VAE가 들어 있어도 전용 VAE를 우선한다."""
    folder = models_root / "WithVae"
    make_safetensors_file(folder, "model.safetensors", SDXL)  # first_stage_model 포함
    make_safetensors_file(folder / "vae", "custom.safetensors", VAE)

    bundle = build_bundle(folder)
    assert bundle.vae.name == "custom.safetensors"


def test_scanner_returns_bundles(models_root, make_safetensors_file):
    """스캐너가 번들을 반환한다."""
    make_safetensors_file(models_root / "Img", "m.safetensors", SDXL)
    llm = models_root / "Llm"
    llm.mkdir()
    (llm / "m.gguf").write_bytes(b"GGUF" + b"\0" * 32)

    scanner = ModelScanner(models_root)
    images = scanner.scan_image()
    llms = scanner.scan_llm()

    assert len(images) == 1
    assert images[0].architecture == "sdxl"
    assert len(llms) == 1
    assert len(scanner.scan_all()) == 2


def test_scanner_ignores_hidden_folders(models_root, make_safetensors_file):
    """숨김 폴더는 무시한다."""
    make_safetensors_file(models_root / ".hidden", "m.safetensors", SDXL)
    make_safetensors_file(models_root / "Visible", "m.safetensors", SDXL)

    bundles = ModelScanner(models_root).scan_all()
    assert [b.name for b in bundles] == ["Visible"]


def test_find_bundle_by_file_and_folder(models_root, make_safetensors_file):
    """파일 경로나 폴더 경로로 번들을 찾는다."""
    folder = models_root / "Findable"
    path = make_safetensors_file(folder, "m.safetensors", SDXL)

    scanner = ModelScanner(models_root)
    assert scanner.find_bundle(path).name == "Findable"
    assert scanner.find_bundle(folder).name == "Findable"


def test_bundle_describe_shows_components(models_root, make_safetensors_file):
    """표시 문자열에 컴포넌트가 포함된다."""
    folder = models_root / "Described"
    make_safetensors_file(folder, "m.safetensors", SDXL)
    make_safetensors_file(folder, "v.safetensors", VAE)
    make_safetensors_file(folder, "l.safetensors", LORA)

    text = build_bundle(folder).describe()
    assert "sdxl" in text
    assert "VAE" in text
    assert "LoRA" in text


def test_separate_clip_warns(models_root, make_safetensors_file):
    """분리 텍스트 인코더는 경고와 함께 무시된다."""
    folder = models_root / "Separated"
    make_safetensors_file(folder, "unet.safetensors", SD15)
    make_safetensors_file(folder, "clip.safetensors", [
        ("text_model.embeddings.token_embedding.weight", (49408, 768)),
    ])

    bundle = build_bundle(folder)
    assert bundle is not None
    assert any("텍스트 인코더" in w for w in bundle.warnings)


def test_empty_folder_returns_none(models_root):
    """모델이 없으면 None."""
    folder = models_root / "Empty"
    folder.mkdir()
    assert build_bundle(folder) is None


def test_folder_without_model_returns_none(models_root):
    """모델 파일이 없으면 None."""
    folder = models_root / "Docs"
    folder.mkdir()
    (folder / "readme.txt").write_text("설명", encoding="utf-8")
    assert build_bundle(folder) is None