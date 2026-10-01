"""Geurim-gyeol 엔진 (v0.2, ComfyUI 기반).

네이티브 추론 모듈(torch/diffusers 직접 실행)은 v0.2 에서 제거되었다.
모델 실행·VRAM 관리는 전부 ComfyUI 가 담당하고, 이 패키지는
워크플로 중재와 결과 저장만 책임진다.
"""

from .comfy_engine import GenerationRequest, GenerationResult, GeurimGyeolEngine

__all__ = ["GeurimGyeolEngine", "GenerationRequest", "GenerationResult"]
