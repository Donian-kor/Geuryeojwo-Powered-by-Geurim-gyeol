"""배포한 기본 워크플로가 실제로 그림을 만드는지 확인.

테스트는 '값이 잘 들어갔는지' 만 본다. 이 스크립트는 진짜로 ComfyUI 에
제출해 그림 파일이 나오는지 끝까지 확인한다. (모델 이름을 비워 둔
기본 워크플로가 '설치 안 됨' 으로 막히지 않는지도 함께 본다)

사용법:
    .venv\\Scripts\\python.exe tools\\smoke_base_workflow.py sdxl
    .venv\\Scripts\\python.exe tools\\smoke_base_workflow.py --all
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.comfy.model_family import compatible_models, workflow_family
from app.comfy.workflow import collect_extra, load_workflow
from app.engine.comfy_engine import GeurimGyeolEngine

BASE = ROOT / "workflows" / "base"
MODELS_DIR = Path(
    "C:/Users/donian/AppData/Local/Comfy-Desktop/ComfyUI-Shared/models"
)

# 계열별 생성 조건. 가벼운 것부터.
CASES = {
    "sdxl": dict(prompt="a cute orange cat, studio photo", width=512,
                 height=512, steps=8, cfg=7.0),
    "zanime": dict(prompt="a cute orange cat, studio photo", width=512,
                  height=512, steps=8, cfg=1.1),
    "qwen-image": dict(prompt="a cute orange cat, studio photo", width=512,
                       height=512, steps=12, cfg=1.0),
    # ERNIE 는 모델이 Base / Turbo 로 나뉘고 최적값이 정반대다.
    # (Base 50스텝 cfg 4.0, Turbo 8스텝 cfg 1.0 — 각 HF 모델카드 권장값)
    "ernie": dict(prompt="a cute orange cat, studio photo", width=512,
                  height=512, steps=50, cfg=4.0),
    "ernie-turbo": dict(prompt="a cute orange cat, studio photo", width=512,
                        height=512, steps=8, cfg=1.0),
    "flux": dict(prompt="a cute orange cat, studio photo", width=512,
                 height=512, steps=8, cfg=1.0),
}


def log(msg: str) -> None:
    print(msg, flush=True)


def _get_json(url: str, timeout: float = 20.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run(name: str) -> bool:
    case = CASES[name]
    wf = load_workflow(BASE / f"{name}.json")
    family = workflow_family(wf, MODELS_DIR)
    log(f"== {name}  (계열={family or '판별불가'})")

    engine = GeurimGyeolEngine(ROOT)
    # build_request 가 이 워크플로를 본다. 먼저 골라 주지 않으면
    # '선택된 워크플로가 없습니다' 로 막힌다.
    engine.active_workflow = wf
    options = engine.model_options() or {}

    # 계열에 맞는 설치 모델을 고른다. (GUI 가 하는 일과 같은 경로)
    # 계열 + 변형에 맞는 설치 모델을 고른다. (GUI 가 하는 일과 같은 경로)
    # 워크플로가 "variant" 를 밝히면 그 변형 모델을, 아니면 목록 첫 번째를 쓴다.
    folder = "checkpoints"
    kinds = wf.parameters
    if any(k == "unet" for k in kinds):
        folder = "diffusion_models"
    picks: dict[str, str] = {}
    for key, kind in kinds.items():
        if not getattr(kind, "kind", "").startswith("model:"):
            continue
        f = kind.kind.split(":", 1)[1]
        names = options.get(f) or []
        ok = compatible_models(names, family, MODELS_DIR, f,
                               wf.meta.get("variant", ""))
        if not ok:
            log(f"   건너뜀 — {family} 계열 모델이 없다 "
                f"({f}: {', '.join(names) or '목록 없음'})")
            return None  # type: ignore[return-value]
        picks[key] = ok[0]
        log(f"   {key} → {picks[key]}  (전체 {len(names)}개 중 {family}"
            f"{'/' + wf.meta['variant'] if wf.meta.get('variant') else ''} 일치)")

    picks["sampler"] = "euler"
    picks["scheduler"] = "normal"
    extra = collect_extra(wf.parameters, picks)

    req = engine.build_request(
        prompt=case["prompt"],
        negative_prompt="",
        width=case["width"], height=case["height"],
        steps=case["steps"], cfg=case["cfg"], seed=12345,
        extra=extra, enhance_prompt=False,
    )
    started = time.perf_counter()
    result = engine.generate(req, on_progress=lambda *a: None)
    elapsed = time.perf_counter() - started

    if not result.success:
        log(f"   실패 — {result.error}")
        return False
    path = Path(result.image_path)
    size_kb = path.stat().st_size / 1024 if path.exists() else 0
    log(f"   성공 — {path.name}  {size_kb:.0f}KB  {elapsed:.1f}초")
    if size_kb < 5:
        log("   경고 — 파일이 너무 작다. 빈 이미지일 수 있다.")
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="기본 워크플로 실제 생성 확인")
    ap.add_argument("name", nargs="?", default="sdxl",
                    choices=list(CASES) + ["--all"])
    ap.add_argument("--all", action="store_true", help="설치된 계열 모두")
    args = ap.parse_args()

    names = list(CASES) if args.all else [args.name]
    results: dict[str, bool | None] = {}
    for name in names:
        try:
            results[name] = run(name)
        except Exception as exc:
            log(f"== {name}  오류 — {exc}")
            results[name] = False
        log("")

    done = [k for k, v in results.items() if v is not None]
    bad = [k for k, v in results.items() if v is False]
    skipped = [k for k, v in results.items() if v is None]
    log(f"성공 {len(done) - len(bad)}/{len(done)}  "
        f"실패 {len(bad)}  모델없음 {len(skipped)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())