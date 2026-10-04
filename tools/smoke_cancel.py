"""중지 경로 최소 재현 스크립트.

pytest 와 달리 GUI 를 실제로 띄워 "중지" 버튼이 잠금을 기다리지 않는지,
ComfyUI 로 신호가 나가는지 눈으로 확인한다.

사용법:
    .venv\\Scripts\\python.exe tools\\smoke_cancel.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.engine.comfy_engine import GeurimGyeolEngine  # noqa: E402


class _RecordingClient:
    """가짜 ComfyUI. 보낸 요청을 기록한다."""

    def __init__(self) -> None:
        self.hits: list[str] = []

    def interrupt_now(self, timeout=5.0):
        self.hits.append("/interrupt")
        return True

    def clear_queue_now(self, timeout=5.0):
        self.hits.append("/queue")
        return True


def check_gui_states(app) -> bool:
    """버튼을 눌렀을 때 상태 문구가 '중지 중...' 으로 바뀌는지 확인한다."""
    import app.gui.main_window as mw

    win = mw.MainWindow()
    try:
        win.show()
        app.processEvents()

        calls: list[str] = []
        win.engine.cancel = lambda: calls.append("cancel")

        win.stop()
        app.processEvents()

        text = win.status.text()
        disabled = not win.cancel.isEnabled()

        print(f"중지 후 상태 문구: {text}")
        print(f"중지 버튼 비활성화: {disabled}")
        print(f"엔진 호출 횟수: {len(calls)}")

        # 취소로 끝난 경우 창이 떠야 하는지 확인한다.
        win.fail("사용자가 실행을 중단했습니다", None)
        app.processEvents()
        print(f"취소 실패 처리 후 문구: {win.status.text()}")

        ok = True
        if text != "중지 중...":
            print("[FAIL] '중지 중...' 이 표시되지 않았다")
            ok = False
        if not disabled:
            print("[FAIL] 중지 버튼이 계속 눌린다 (연속 요청 방지 실패)")
            ok = False
        if len(calls) != 1:
            print("[FAIL] 엔진 cancel 이 호출되지 않았다")
            ok = False
        if win.status.text() != "중지됨":
            print("[FAIL] '중지됨' 으로 바뀌지 않았다")
            ok = False
        if not win.generate.isEnabled():
            print("[FAIL] 생성 버튼이 다시 켜지지 않았다")
            ok = False
        return ok
    finally:
        win._closing = True
        win.close()
        del win


def main() -> int:
    app = QApplication.instance() or QApplication([])

    engine = GeurimGyeolEngine(ROOT)
    client = _RecordingClient()
    engine.client = client

    # 생성 스레드가 잠금을 쥔 상태를 흉내낸다. (실제 생성 중과 같다)
    engine._loop_lock.acquire()

    t0 = time.perf_counter()
    engine.cancel()
    elapsed = time.perf_counter() - t0
    engine._loop_lock.release()

    print(f"cancel() 반환 시간: {elapsed * 1000:.1f}ms")

    # 백그라운드 전송이 끝날 때까지 잠깐 기다린다.
    deadline = time.time() + 5
    while len(client.hits) < 2 and time.time() < deadline:
        time.sleep(0.05)

    print(f"전송된 요청: {client.hits}")

    ok = True
    if elapsed >= 0.5:
        print("[FAIL] cancel() 이 생성 잠금을 기다렸다")
        ok = False
    if client.hits != ["/interrupt", "/queue"]:
        print(f"[FAIL] 보낸 요청이 다르다: {client.hits}")
        ok = False

    print(f"살아 있는 스레드 {threading.active_count()}개")

    print("--- GUI ---")
    if not check_gui_states(app):
        ok = False

    engine._close_loop()
    del app
    print(f"[{'OK' if ok else 'FAIL'}] 전체 확인")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())