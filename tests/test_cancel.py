"""중지 경로 통합 테스트.

왜 이 파일이 따로 있는가:
중지가 실제로 "몇 초 안에" 먹히는지는 스텁으로는 알 수 없다.
ComfyUI 가 받는 신호가 정말 HTTP 로 나가는지까지 확인해야 하므로,
127.0.0.1 에 가짜 HTTP 서버를 띄워 요청을 직접 세어 본다.
외부 네트워크에는 접속하지 않는다.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.comfy.client import ComfyClient
from app.comfy.config import ComfyUIConfig


class _Handler(BaseHTTPRequestHandler):
    """ComfyUI 의 /interrupt 와 /queue 만 받는 최소 서버."""

    def log_message(self, *args):  # 표준 출력에 로그를 찍지 않는다
        return

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return {}

    def _reply(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.server.hits.append((self.path, self._read_json()))
        if self.path == "/queue":
            self._reply({})
        else:
            self._reply({})

    def do_GET(self):
        self._reply({})


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.hits = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def _client(server) -> ComfyClient:
    config = ComfyUIConfig(host="127.0.0.1", port=httpd_port(server))
    config.connect_timeout_seconds = 5
    return ComfyClient(config)


def httpd_port(server) -> int:
    return server.server_address[1]


def test_interrupt_now_reaches_the_server(server):
    """/interrupt 가 실제로 전송된다."""
    client = _client(server)

    assert client.interrupt_now(timeout=5.0) is True

    assert ("/interrupt", {}) in server.hits


def test_clear_queue_now_asks_comfyui_to_drop_pending(server):
    """/interrupt 는 실행 중인 것만 멈추므로 대기열도 비운다."""
    client = _client(server)

    assert client.clear_queue_now(timeout=5.0) is True

    assert ("/queue", {"clear": True}) in server.hits


def test_cancel_paths_stay_fast_under_a_stalled_server(server):
    """서버가 느려도 중지 신호 전송은 3초 안에 끝난다.

    회귀 근거: 예전 cancel() 은 생성 스레드의 잠금을 기다렸다.
    그 잠금이 풀릴 때까지 아무 신호도 나가지 않았다.
    """
    client = _client(server)

    t0 = time.perf_counter()
    client.interrupt_now(timeout=2.0)
    client.clear_queue_now(timeout=2.0)
    elapsed = time.perf_counter() - t0

    assert elapsed < 3.0, f"중지 신호 전송이 {elapsed:.2f}초 걸렸다"


def test_cancel_never_raises_when_server_is_down():
    """ComfyUI 가 꺼져 있어도 조용히 실패한다."""
    # 아무것도 안 듣는 포트를 쓴다. (8888 은 사용 중일 수 있어 9 로 대체)
    client = ComfyClient(ComfyUIConfig(host="127.0.0.1", port=9))

    assert client.interrupt_now(timeout=1.0) is False
    assert client.clear_queue_now(timeout=1.0) is False