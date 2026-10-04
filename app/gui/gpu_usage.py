"""상태바용 GPU 사용률 조회.

ComfyUI 의 /system_stats 는 VRAM 용량만 알려주고 GPU 사용률은 주지 않는다.
NVIDIA GPU 는 nvidia-smi 가 유일한 표준 경로라 그것을 쓴다.

주의: 1초마다 nvidia-smi 를 새로 띄우면(프로세스 생성 ~수십 ms) 상태바 갱신이
계속 지연된다. 한 번만 띄워 두고 stdout 을 줄 단위로 읽어 쓴다.
"""
from __future__ import annotations

import re
import subprocess
import threading


class GpuUsageReader:
    """nvidia-smi 를 상주시켜 GPU 사용률(%) 을 읽는다.

    Attributes:
        available: nvidia-smi 를 찾았고 정상적으로 돌고 있는가.
    """

    # nounits 를 쓰면 출력이 '6' 처럼 숫자만, 안 쓰면 '6 %' 가 된다.
    # 둘 다 받아야 하므로 % 는 선택 사항으로 둔다.
    # 메모리를 함께 물으면 '6, 1024, 24576' 처럼 쉼표로 나뉘어 나온다.
    _NUM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%?\s*$")

    def __init__(self, index: int = 0, gpu_name: str = ""):
        self.index = index
        self.gpu_name = gpu_name
        self.available = False
        self._attempted = False
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._percent: float | None = None
        self._vram_used_mb: float | None = None
        self._vram_total_mb: float | None = None

    # ---------------------------------------------------------------- 수명주기

    def start(self) -> None:
        """감시 프로세스를 띄운다. 이미 떠 있으면 아무것도 하지 않는다."""
        if self._proc is not None and self._proc.poll() is None:
            return
        # 실패했어도 다시 시도하지 않는다 (1초마다 실패하면 콘솔을 띄우려 한다)
        if self._attempted and self._proc is None:
            return
        self._attempted = True
        try:
            self._proc = subprocess.Popen(
                [
                    "nvidia-smi",
                    f"--id={self.index}",
                    # 사용률과 VRAM 을 한 번에 읽는다.
                    # 따로 물으면 프로세스를 하나 더 띄워야 하는데,
                    # 그게 상태바 갱신을 매번 늦춘다.
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                    "-l", "1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_no_window(),
            )
        except (OSError, ValueError):
            # nvidia-smi 가 없으면(AMD/Intel/터치패드만 있는 노트북) 조용히 끈다
            self._proc = None
            self.available = False
            return

        self.available = True
        self._thread = threading.Thread(
            target=self._pump, name="nvidia-smi-reader", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """감시 프로세스를 정리한다.

        시도 표시를 지워 다시 start() 할 수 있게 한다. 지우지 않으면
        stop() 한 번으로 그 리더는 영영 켜지지 않는다 (start() 의 가드에
        걸린다). 부르는 쪽은 closeEvent 뿐이고 그때는 타이머도 멈추므로
        매 초 재시도가 되살아나지는 않는다.
        """
        proc = self._proc
        thread = self._thread
        self._proc = None
        self._thread = None
        self._attempted = False
        self.available = False
        self._percent = None
        self._vram_used_mb = None
        self._vram_total_mb = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
        except Exception:
            # 종료 실패로 프로그램이 멈추면 안 된다
            pass
        finally:
            # 회귀 근거: 읽는 스레드가 for line in proc.stdout 으로 파이프를
            # 순회하는 중 stdout 을 닫으면 그대로 access violation 으로 죽는다.
            # (창을 닫을 때 nvidia-smi 가 아직 한 줄을 내보내는 타이밍)
            # 프로세스를 끝내면 파이프가 EOF 에 닿아 순회가 스스로 끝난다.
            # 스레드가 완전히 종료된 뒤에만 파이프를 닫는다.
            if thread is not None and thread.is_alive():
                # 프로세스 종료 후 파이프 EOF 도달까지 넉넉히 대기
                thread.join(timeout=5)
            # 스레드가 여전히 살아있다면(이론상 드물다) 파이프 닫기를 건너뛰고
            # OS가 정리하도록 둔다. 강제 닫기는 access violation 유발.
            if proc.stdout is not None:
                try:
                    proc.stdout.close()
                except Exception:
                    pass

    # ---------------------------------------------------------------- 읽기

    def percent(self) -> float | None:
        """최근 사용률(%). 아직 한 줄도 못 읽었으면 None."""
        with self._lock:
            return self._percent

    def vram(self) -> tuple[float | None, float | None]:
        """최근 VRAM 을 (사용 MB, 전체 MB) 로 돌려준다.

        ComfyUI 의 /system_stats 는 '새로고침' 을 누를 때만 갱신되므로
        상태바에 그대로 쓰면 옛 값이 계속 보인다. nvidia-smi 를 상주시켜
        두면 그 틈 없이 읽을 수 있다.

        Returns:
            값을 아직 못 읽었거나 형식이 달라졌으면 (None, None).
        """
        with self._lock:
            return self._vram_used_mb, self._vram_total_mb

    def vram_gb(self) -> tuple[float | None, float | None]:
        """VRAM 을 GB 단위로 돌려준다."""
        used, total = self.vram()
        if used is None or total is None:
            return None, None
        return used / 1024.0, total / 1024.0

    @property
    def started(self) -> bool:
        """시도를 한 번이라도 했는가 (nvidia-smi 부재로 실패했을 때도 True).

        매 초 재시도하지 않기 위한 표시다.
        """
        return self._attempted

    def _pump(self) -> None:
        """stdout 을 읽어 사용률과 VRAM 을 계속 저장한다 (스레드)."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                parsed = self._parse_line(line)
                if parsed is None:
                    continue
                percent, used_mb, total_mb = parsed
                with self._lock:
                    self._percent = percent
                    if used_mb is not None and total_mb is not None:
                        self._vram_used_mb = used_mb
                        self._vram_total_mb = total_mb
                if self._proc is None:
                    # stop() 이 불렸는데 아직 종료 신호가 안 왔을 수 있다
                    break
        except Exception:
            # 파이프가 끊겼으면 조용히 끈다
            self.available = False

    @classmethod
    def _parse_line(
        cls, line: str
    ) -> tuple[float, float | None, float | None] | None:
        """nvidia-smi 출력 한 줄을 (사용률, 사용 MB, 전체 MB) 로 읽는다.

        필드가 하나뿐인 '6' 형식과 셋인 '6, 1024, 24576' 형식을 모두 받는다.
        둘 다 하는 이유는 --query-gpu 에 무엇을 넣었느냐에 따라 형식이
        달라지는데, 어느 쪽이든 숫자만 있으면 쓸 수 있기 때문이다.

        Returns:
            읽을 수 없으면 None. (숫자가 아닌 줄은 오탐이 아니라 '없음' 이다)
        """
        values: list[float] = []
        for part in line.split(","):
            match = cls._NUM.match(part)
            if match is None:
                return None
            values.append(float(match.group(1)))
        if not values:
            return None
        if len(values) >= 3:
            return values[0], values[1], values[2]
        return values[0], None, None


def _no_window() -> int:
    """Windows 에서 콘솔 창이 뜨지 않도록 하는 플래그."""
    import sys

    if sys.platform != "win32":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)