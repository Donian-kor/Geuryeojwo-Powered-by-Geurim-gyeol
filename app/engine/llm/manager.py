from __future__ import annotations
from pathlib import Path

class LocalLLM:
    """Optional in-process GGUF runtime. No server/API is used."""
    def __init__(self, model_path: Path, device: str, logger):
        self.model_path = model_path
        self.device = device
        self.logger = logger
        self.model = None

    def load(self):
        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise RuntimeError("llama-cpp-python is not installed. Install requirements.txt first.") from e
        n_gpu_layers = -1 if self.device == "cuda" else 0
        self.model = Llama(model_path=str(self.model_path), n_ctx=4096, n_gpu_layers=n_gpu_layers, verbose=False)
        return self

    def generate(self, system: str, user: str, temperature: float = 0.7, max_tokens: int = 500) -> str:
        if self.model is None:
            raise RuntimeError("Local LLM is not loaded")
        out = self.model.create_chat_completion(
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
            temperature=temperature, max_tokens=max_tokens,
        )
        return out["choices"][0]["message"]["content"].strip()

    def unload(self):
        self.model = None
