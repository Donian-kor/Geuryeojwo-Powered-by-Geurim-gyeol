"""WebSocket 실행 흐름 통합 테스트.

B2 는 monkeypatch 로 검증할 수 없다. 실제 소켓이 있어야
"완료 신호를 놓치지 않는다" 와 "남의 이벤트를 무시한다" 를
확인할 수 있으므로, 테스트 안에서 가짜 ComfyUI 서버를 띄운다.

네트워크는 127.0.0.1 의 임시 포트만 쓰고 외부에는 접속하지 않는다.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.comfy.client import ComfyClient, ComfyUIError
from app.comfy.config import ComfyUIConfig

pytest.importorskip("websockets")


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _client(port: int) -> ComfyClient:
    config = ComfyUIConfig(host="127.0.0.1", port=port)
    config.timeout_seconds = 20
    config.connect_timeout_seconds = 5
    return ComfyClient(config)


def _history_with(filename: str):
    async def fake(prompt_id):
        return {prompt_id: {"outputs": {"8": {"images": [
            {"filename": filename, "subfolder": "", "type": "output"}
        ]}}}}
    return fake


def _path_of(websocket) -> str:
    """웹소켓 핸들러가 요청 경로를 알려주는 API 가 버전마다 다르다."""
    request = getattr(websocket, "request", None)
    return getattr(request, "path", "") or ""


async def _serve(handler):
    """127.0.0.1 의 임의 포트에 WebSocket 서버를 띄우고 (server, port) 반환."""
    import websockets.asyncio.server as ws_server

    server = await ws_server.serve(handler, "127.0.0.1", 0, ping_interval=None)
    port = next(iter(server.sockets)).getsockname()[1]
    return server, port


async def _shutdown(server):
    server.close()
    try:
        await server.wait_closed()
    except Exception:
        pass


def test_websocket_opens_before_prompt_is_posted():
    """WS 연결이 POST /prompt 보다 먼저 성립해야 한다.

    회귀: POST 를 먼저 하면 빠른 워크플로의 완료 신호가
    연결 전에 지나가 timeout_seconds 만큼 멈춘 뒤 오탐된다.
    """
    order: list[str] = []

    async def scenario():
        connected = asyncio.Event()
        box: dict = {}

        async def handler(websocket):
            if "/ws" not in _path_of(websocket):
                return
            order.append("ws_open")
            box["ws"] = websocket
            connected.set()
            try:
                async for _ in websocket:
                    pass
            except Exception:
                pass

        server, port = await _serve(handler)
        try:
            client = _client(port)

            async def fake_post(path, payload=None, timeout=None):
                order.append(f"post:{path}")
                assert connected.is_set(), (
                    "POST 전에 WebSocket 이 열리지 않았다 — 완료 신호를 놓친다"
                )
                assert payload.get("client_id"), "client_id 가 있어야 한다"
                # 실행이 즉시 끝나는 경우를 흉내낸다
                await box["ws"].send(json.dumps({
                    "type": "executing",
                    "data": {"prompt_id": "p-abc", "node": None},
                }))
                return _FakeResponse({"prompt_id": "p-abc"})

            client._post = fake_post
            client.get_history = _history_with("x.png")

            await client.run({"3": {"class_type": "KSampler", "inputs": {}}})
        finally:
            await _shutdown(server)

    asyncio.run(scenario())
    assert order[0] == "ws_open", f"실제 순서: {order}"
    assert "post:/prompt" in order


def test_foreign_prompt_events_are_ignored():
    """다른 prompt 의 완료 신호로 오인하지 않는다.

    같은 ComfyUI 를 다른 프로그램이 쓰는 중이면 남의
    executing+node=null 로 여기서도 완료로 판정할 수 있다.
    """
    async def scenario():
        mine = "p-mine"
        box: dict = {}

        async def handler(websocket):
            if "/ws" not in _path_of(websocket):
                return
            box["ws"] = websocket
            try:
                async for _ in websocket:
                    pass
            except Exception:
                pass

        server, port = await _serve(handler)
        try:
            client = _client(port)

            async def fake_post(path, payload=None, timeout=None):
                ws = box["ws"]
                # 남의 완료 신호를 먼저, 내 것으로 오인하기 쉬운 순서로
                await ws.send(json.dumps({"type": "executing",
                                         "data": {"prompt_id": "p-other", "node": None}}))
                await asyncio.sleep(0.05)
                await ws.send(json.dumps({"type": "executing",
                                         "data": {"prompt_id": mine, "node": "3"}}))
                await asyncio.sleep(0.05)
                await ws.send(json.dumps({"type": "executing",
                                         "data": {"prompt_id": mine, "node": None}}))
                return _FakeResponse({"prompt_id": mine})

            client._post = fake_post
            client.get_history = _history_with("ok.png")

            images = await client.run({"3": {"class_type": "KSampler", "inputs": {}}})
            return [i["filename"] for i in images]
        finally:
            await _shutdown(server)

    assert asyncio.run(scenario()) == ["ok.png"]


def test_execution_error_message_is_surfaced():
    """execution_error 의 메시지가 그대로 전달된다."""
    async def scenario():
        mine = "p-err"
        box: dict = {}

        async def handler(websocket):
            if "/ws" not in _path_of(websocket):
                return
            box["ws"] = websocket
            try:
                async for _ in websocket:
                    pass
            except Exception:
                pass

        server, port = await _serve(handler)
        try:
            client = _client(port)

            async def fake_post(path, payload=None, timeout=None):
                await box["ws"].send(json.dumps({
                    "type": "execution_error",
                    "data": {"prompt_id": mine, "exception_message": "CUDA out of memory"},
                }))
                return _FakeResponse({"prompt_id": mine})

            client._post = fake_post

            with pytest.raises(ComfyUIError, match="CUDA out of memory"):
                await client.run({"3": {"class_type": "KSampler", "inputs": {}}})
        finally:
            await _shutdown(server)

    asyncio.run(scenario())


def test_progress_percentage_is_mapped_to_10_90():
    """progress 값이 10~90% 구간으로 매핑된다 (§6)."""
    seen: list[int] = []

    async def scenario():
        mine = "p-prog"
        box: dict = {}

        async def handler(websocket):
            if "/ws" not in _path_of(websocket):
                return
            box["ws"] = websocket
            try:
                async for _ in websocket:
                    pass
            except Exception:
                pass

        server, port = await _serve(handler)
        try:
            client = _client(port)

            async def fake_post(path, payload=None, timeout=None):
                ws = box["ws"]
                for value in (0, 5, 10):
                    await ws.send(json.dumps({
                        "type": "progress",
                        "data": {"prompt_id": mine, "value": value, "max": 10},
                    }))
                    await asyncio.sleep(0.03)
                await ws.send(json.dumps({"type": "executing",
                                         "data": {"prompt_id": mine, "node": None}}))
                return _FakeResponse({"prompt_id": mine})

            client._post = fake_post
            client.get_history = _history_with("p.png")

            def on_progress(percent, message):
                seen.append(percent)

            await client.run(
                {"3": {"class_type": "KSampler", "inputs": {}}},
                on_progress=on_progress,
            )
        finally:
            await _shutdown(server)

    asyncio.run(scenario())
    assert 10 in seen, f"progress 매핑 실패: {seen}"
    assert 90 in seen, f"progress 상한(90%) 이 지켜지지 않았다: {seen}"
    assert max(seen) <= 100
