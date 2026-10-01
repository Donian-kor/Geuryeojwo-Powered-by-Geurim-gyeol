"""모델 파일 내용 기반 분석 테스트 (v0.1 §9, §11)."""
import json

import pytest
import torch
from safetensors.torch import save_file

from app.engine.models.inspector import (
    ComponentKind,
    inspect_file,
    read_tensor_keys,
)


@pytest.fixture
def make_safetensors(tmp_path):
    """헤더만 가진 가짜 safetensors를 만든다."""

    def _make(spec, name="test.safetensors"):
        path = tmp_path / name
        tensors = {k: torch.zeros(*shape, dtype=torch.float16) for k, shape in spec}
        save_file(tensors, str(path))
        return path

    return _make


SD15 = [
    ("model.diffusion_model.input_blocks.0.0.weight", (320, 4, 3, 3)),
    ("model.diffusion_model.down_blocks.0.resnets.0.in_layers.0.weight", (320, 320, 3, 3)),
    ("model.diffusion_model.out.0.weight", (4, 320, 3, 3)),
    ("first_stage_model.encoder.conv_in.weight", (128, 3, 3, 3)),
    ("first_stage_model.decoder.conv_out.weight", (3, 128, 3, 3)),
    ("cond_stage_model.transformer.text_model.embeddings.token_embedding.weight", (49408, 768)),
]

SDXL = [
    ("model.diffusion_model.input_blocks.0.0.weight", (320, 9, 3, 3)),
    ("model.diffusion_model.add_embedding.linear_1.weight", (320, 2816)),
    ("model.diffusion_model.add_embedding.linear_2.weight", (1280, 320)),
    ("model.diffusion_model.out.0.weight", (4, 320, 3, 3)),
    ("first_stage_model.encoder.conv_in.weight", (128, 3, 3, 3)),
    ("cond_stage_model.transformer.text_model.embeddings.token_embedding.weight", (49408, 768)),
]

FLUX = [
    ("x_embedder.proj.weight", (3072, 64, 16, 16)),
    ("transformer_blocks.0.attn.to_k.weight", (3072, 3072)),
    ("final_layer.linear.weight", (64, 3072)),
    ("context_embedder.weight", (3072, 4096)),
]

SD3 = [
    ("pos_embed", (1, 2048, 64)),
    ("transformer_blocks.0.attn.to_q.weight", (1536, 1536)),
    ("x_embedder.proj.weight", (1536, 16, 2, 2)),
]

VAE = [
    ("encoder.conv_in.weight", (128, 3, 3, 3)),
    ("decoder.conv_out.weight", (3, 128, 3, 3)),
]
@pytest.mark.parametrize("spec,expected_arch", [
    (SD15, "sd15"),
    (SDXL, "sdxl"),
    (FLUX, "flux"),
    (SD3, "sd3"),
])
def test_bundled_checkpoint_architecture(spec, expected_arch, make_safetensors):
    """번들 체크포인트가 헤더만으로 정확한 아키텍처로 판별된다."""
    path = make_safetensors(spec, f"{expected_arch}.safetensors")
    result = inspect_file(path)
    assert result.kind == ComponentKind.UNET
    assert result.architecture == expected_arch


def test_filename_does_not_affect_detection(make_safetensors):
    """파일명이 아무리 어색해도 내용으로 판별된다 (v0.1 §11)."""
    path = make_safetensors(SDXL, "completely_unrelated_name.safetensors")
    assert inspect_file(path).architecture == "sdxl"


@pytest.mark.parametrize("spec,expected", [
    ([("first_stage_model.encoder.conv_in.weight", (128, 3, 3, 3)),
      ("first_stage_model.decoder.conv_out.weight", (3, 128, 3, 3))],
     ComponentKind.VAE),
    (VAE, ComponentKind.VAE),
    ([("text_model.embeddings.token_embedding.weight", (49408, 768))],
     ComponentKind.CLIP),
    ([("cond_stage_model.transformer.text_model.embeddings.weight", (1,))],
     ComponentKind.CLIP),
    ([("visual.proj.weight", (1024, 768))], ComponentKind.CLIP_VISION),
    ([("lora_unet_down.weight", (16, 320, 3, 3)),
      ("lora_unet_up.weight", (320, 16, 1, 1))], ComponentKind.LORA),
    ([("lora_te_down.weight", (16, 768)),
      ("lora_te_up.weight", (768, 16))], ComponentKind.LORA),
])
def test_component_classification(spec, expected, make_safetensors):
    """컴포넌트 유형이 정확히 분류된다."""
    path = make_safetensors(spec, "c.safetensors")
    assert inspect_file(path).kind == expected


def test_separate_components_detected(make_safetensors):
    """단일 파일(번들)과 분리 파일 모두 지원된다."""
    unet = make_safetensors(SD15, "unet.safetensors")
    vae = make_safetensors(VAE, "vae.safetensors")
    clip = make_safetensors(
        [("text_model.embeddings.token_embedding.weight", (49408, 768))], "clip.safetensors"
    )

    assert inspect_file(unet).kind == ComponentKind.UNET
    assert inspect_file(vae).kind == ComponentKind.VAE
    assert inspect_file(clip).kind == ComponentKind.CLIP


def test_diffusers_directory_detected(tmp_path):
    """model_index.json이 있으면 Diffusers 폴더로 인식한다."""
    folder = tmp_path / "flux1-dev"
    folder.mkdir()
    (folder / "model_index.json").write_text(json.dumps({
        "_class_name": "FluxPipeline",
        "transformer": ["diffusers", "FluxTransformer2DModel"],
    }), encoding="utf-8")

    result = inspect_file(folder)
    assert result.kind == ComponentKind.DIFFUSERS_DIR
    assert result.architecture == "flux"


def test_gguf_detected(tmp_path):
    """GGUF는 매직바로 LLM임을 인식한다."""
    path = tmp_path / "qwen.gguf"
    path.write_bytes(b"GGUF" + b"\0" * 128)
    result = inspect_file(path)
    assert result.kind == ComponentKind.GGUF
    assert result.architecture == "llm"


def test_corrupted_gguf_flagged(tmp_path):
    """손상된 GGUF는 오류로 보고한다 (v0.1 §28)."""
    path = tmp_path / "broken.gguf"
    path.write_bytes(b"XXXX" + b"\0" * 128)
    result = inspect_file(path)
    assert result.kind == ComponentKind.UNKNOWN
    assert result.error


def test_corrupted_safetensors_flagged(tmp_path):
    """손상된 safetensors는 예외 대신 오류 결과를 반환한다."""
    path = tmp_path / "broken.safetensors"
    path.write_bytes(b"not a safetensors file")
    result = inspect_file(path)
    assert result.kind == ComponentKind.UNKNOWN
    assert result.error


def test_header_read_is_fast(make_safetensors):
    """헤더만 읽으므로 파일 크기와 무관하게 빠르다 (v0.1 §9)."""
    import time

    spec = [(f"w{i}", (1024, 1024)) for i in range(64)]
    path = make_safetensors(spec, "big.safetensors")

    t0 = time.perf_counter()
    keys = read_tensor_keys(path)
    elapsed = (time.perf_counter() - t0) * 1000

    assert len(keys) == 64
    assert elapsed < 500, f"헤더 읽기가 너무 느림: {elapsed:.1f}ms"


def test_unknown_file_returns_unknown(make_safetensors):
    path = make_safetensors([("totally.unrelated.key", (1,))], "x.safetensors")
    assert inspect_file(path).kind == ComponentKind.UNKNOWN