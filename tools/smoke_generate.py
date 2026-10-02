"""실제 생성 스모크 테스트 — ComfyUI 를 죽이지 않는 실행기.

왜 이게 필요한가
----------------
ComfyUI 는 이미지를 만들 때 모델을 VRAM/RAM 에 올린다. Qwen-Image 2.1 은
확산 모델 4GB + 텍스트 인코더 8.9GB + VAE 로 한 번에 약 13GB 를 끌어다 쓴다.
이 PC 는 물리 메모리 31GB 이고 Comfy Desktop(Electron) 까지 떠 있어서,
생성 직후 메모리가 빠듯해진다. 그 상태에서 ComfyUI 가 먼저 죽고
Comfy Desktop 가 다시 띄운다. 죽은 로그에는 트레이스백 없이
"Using RAM pressure cache" 만 남는다.

그래서 이 스크립트는 네 가지를 지킨다.

1. 실행 전 메모리 검사 — 빈 RAM 이나 커밋 여유가 부족하면 생성을 아예
   시작하지 않는다. 위험한 상황을 만들지 않는 것이 먼저다.
2. 전후로 /free 호출 — 시작 전과 끝난 뒤(실패해도) 모델을 내린다.
   메모리가 누적되지 않아 다음 실행이 안전해진다.
3. 가벼운 워크플로 기본값 — SDXL 체크포인트 하나(512x512, 4스텝).
   자주 돌리는 확인은 이것으로 충분하다.
4. 감시 스레드 — 생성이 도중 ComfyUI 프로세스가 사라지면 기록해,
   "생성이 실패했다"와 "서버가 죽었다"를 구분한다.

사용법
------
    python tools/smoke_generate.py --dry-run       # 안전 검사만(생성 안 함)
    python tools/smoke_generate.py                 # 가벼운 SDXL 생성
    python tools/smoke_generate.py --profile qwen  # 무거운 Qwen 검증

pytest 는 이 경로를 건드리지 않으며 서버에 접속하지도 않는다.
"""
from __future__ import annotations

import argparse
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.comfy.workflow import load_workflow
from app.engine.comfy_engine import GeurimGyeolEngine

GB = 1024 ** 3

# Windows 콘솔이 cp949 라 '—' 같은 문자를 못 출력해 죽을 수 있다.
# 출력은 UTF-8 로 밀어내고, 못 읽는 문자는 대체한다 (로그는 지우지 않는다).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# qwen 은 모델 3개(약 13GB)를 올리므로 여유를 넉넉히 요구한다.
PROFILES = {
    "sdxl": {
        "workflow": ROOT / "tools" / "workflows" / "sdxl-smoke.json",
        "width": 512, "height": 512, "steps": 4,
        "min_free_gb": 8.0, "min_commit_gb": 10.0,
        "desc": "SDXL 체크포인트 하나 (가벼움, 자주 돌림)",
    },
    "qwen": {
        "workflow": None,  # workflows/ 폴더의 qwen 워크플로를 쓴다
        "width": 1024, "height": 1024, "steps": 12,
        "min_free_gb": 14.0, "min_commit_gb": 20.0,
        "desc": "Qwen-Image 2.1 (무거움, 가끔 전체 검증)",
    },
}


def log(msg: str) -> None:
    print(msg, flush=True)


def _mem_state() -> tuple[float, float]:
    """(빈 물리 메모리 GB, 커밋 여유 GB) 를 돌려준다."""
    vm = psutil.virtual_memory()
    free_gb = vm.available / GB
    # 커밋 한계는 물리 메모리 + 페이지를 합친 실제 벽이다.
    # "메모리는 넉넉한데 커밋이 모자라는" 상황을 잡으려면 함께 봐야 한다.
    swap = psutil.swap_memory()
    commit_gb = (swap.free + vm.available) / GB
    return free_gb, commit_gb


def comfy_pids() -> set[int]:
    """현재 떠 있는 ComfyUI 서버 프로세스 pid 집합."""
    pids: set[int] = set()
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = " ".join(p.info.get("cmdline") or [])
            if "ComfyUI" in cl and "main.py" in cl:
                pids.add(p.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def server_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class Watchdog(threading.Thread):
    """생성 중 ComfyUI 프로세스/포트가 사라지는지 지켜본다.

    죽은 시점을 기록해 두면 generate() 실패가 '서버 사망'인지
    '잘못된 요청'인지 구분할 수 있다.
    """

    def __init__(self, host: str, port: int, interval: float = 2.0):
        super().__init__(daemon=True)
        self.host, self.port, self.interval = host, port, interval
        self.start_pids = comfy_pids()
        self.died_at: float | None = None
        self.reason: str = ""
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.wait(self.interval):
            gone = self.start_pids - comfy_pids()
            if gone:
                self.died_at = time.time()
                self.reason = f"ComfyUI 프로세스 종료 (pid {sorted(gone)})"
                return
            # 프로세스는 있으나 포트가 닫힘 — 모델 로딩 중일 수 있으므로
            # 한 번이 아니라 두 번 연속 실패해야 진짜로 본다.
            if not server_port_open(self.host, self.port) and not \
               server_port_open(self.host, self.port, timeout=4.0):
                self.died_at = time.time()
                self.reason = f"ComfyUI 포트 {self.port} 응답 없음"
                return

    def stop(self) -> None:
        self._stop.set()



def preflight(eng: GeurimGyeolEngine, prof: dict, dry: bool) -> bool:
    """안전 조건을 확인한다. 위험하면 False 를 주고 생성하지 않는다."""
    host, port = eng.config.host, eng.config.port

    log("== 실행 전 안전 검사 ==")
    if not server_port_open(host, port):
        log(f"  X ComfyUI({host}:{port}) 접속 불가. 서버를 먼저 켜주세요.")
        return False

    pids = comfy_pids()
    log(f"  · ComfyUI 프로세스 {sorted(pids) if pids else '(목록에 없음)'}")

    # 큐에 진행 중인 작업이 있으면 건드리지 않는다.
    try:
        q = eng._run(eng.client.get_queue())
        if q.get("queue_running"):
            log("  X 진행 중인 생성이 있습니다. 끝난 뒤 다시 실행해주세요.")
            return False
    except Exception:
        pass

    free_gb, commit_gb = _mem_state()
    log(f"  · 빈 물리 메모리 {free_gb:.1f} GB / 커밋 여유 {commit_gb:.1f} GB")
    log(f"  · 필요 최소치    물리 {prof['min_free_gb']:.0f} GB / "
        f"커밋 {prof['min_commit_gb']:.0f} GB")

    if free_gb < prof["min_free_gb"] or commit_gb < prof["min_commit_gb"]:
        log("  X 메모리가 부족합니다. 다른 프로그램을 닫고 다시 시도하세요.")
        log("    (생성을 시작하지 않았습니다 — 서버는 그대로입니다)")
        return False

    log("  O 안전 조건 만족")
    if dry:
        log("--dry-run 이므로 실제 생성은 하지 않습니다.")
    return True


def free_memory(eng: GeurimGyeolEngine) -> None:
    """로드된 모델을 내린다. 실패해도 조용히 넘어간다."""
    try:
        eng._run(eng.client.post_free())
        log("  · 모델 언로드(/free) 요청")
    except Exception:
        pass


def pick_workflow(eng: GeurimGyeolEngine, prof: dict, profile: str):
    """프로필에 맞는 워크플로를 고른다."""
    if profile == "sdxl":
        wf = load_workflow(prof["workflow"])
        if wf is None:
            log(f"  X 워크플로를 읽지 못했습니다: {prof['workflow']}")
            return None
        return wf
    if not eng.workflows:
        eng.refresh_workflows()
    if not eng.workflows:
        log("  X workflows/ 폴더에 워크플로가 없습니다.")
        return None
    return eng.workflows[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="안전한 실제 생성 스모크 테스트")
    ap.add_argument("--profile", choices=list(PROFILES), default="sdxl",
                    help="sdxl=가벼움(기본), qwen=무거운 전체 검증")
    ap.add_argument("--dry-run", action="store_true",
                    help="안전 검사만 하고 생성하지 않는다")
    ap.add_argument("--prompt", default="a cute cat sitting on a desk",
                    help="사용할 프롬프트")
    args = ap.parse_args()

    prof = PROFILES[args.profile]
    log(f"프로필: {args.profile} — {prof['desc']}")

    # 실제 설정(서버 주소 등)은 프로젝트 것을 쓰되, 출력물은 임시 폴더로
    # 빼서 사용자의 outputs/ 를 더럽히지 않게 한다.
    sandbox = Path(tempfile.mkdtemp(prefix="geurim-smoke-"))
    try:
        (sandbox / "config").mkdir(parents=True, exist_ok=True)
        for sub in ("workflows", "outputs", "sessions"):
            (sandbox / sub).mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "config" / "comfyui.json",
                    sandbox / "config" / "comfyui.json")

        eng = GeurimGyeolEngine(sandbox)
        if not preflight(eng, prof, args.dry_run):
            return 2
        if args.dry_run:
            return 0

        wf = pick_workflow(eng, prof, args.profile)
        if wf is None:
            return 2
        eng.active_workflow = wf
        log(f"워크플로: {wf.name}")

        free_memory(eng)  # 시작 전에 한 번 비운다

        dog = Watchdog(eng.config.host, eng.config.port)
        dog.start()
        try:
            log(f"\n생성 시작: {prof['width']}x{prof['height']}, {prof['steps']}스텝")
            req = eng.build_request(
                prompt=args.prompt,
                negative_prompt="blurry, low quality, watermark",
                width=prof["width"], height=prof["height"], steps=prof["steps"],
                cfg=7.0, seed=-1, enhance_prompt=False,
            )

            def on_progress(pct: int, msg: str) -> None:
                log(f"  {pct:3d}% {msg}")

            result = eng.generate(req, on_progress=on_progress)
        finally:
            dog.stop()
            dog.join(timeout=3)
            free_memory(eng)  # 끝난 뒤(실패해도) 반드시 비운다

        log("\n== 결과 ==")
        if dog.died_at:
            log(f"  X 생성 도중 ComfyUI 가 죽었습니다: {dog.reason}")
            log("    (메모리 부족 가능성. qwen 프로필은 특히 무겁습니다)")
            return 3
        if result.success:
            log(f"  O 성공 — {result.image_path}")
            log(f"    소요 {result.elapsed_seconds:.1f}초")
            return 0
        log(f"  X 생성 실패: {result.error}")
        return 1
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
