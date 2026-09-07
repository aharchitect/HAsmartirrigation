from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import httpx
import pytest
from websockets.sync.server import ServerConnection, serve

from tests_e2e.ha_client import HomeAssistantRuntimeClient

if TYPE_CHECKING:
    from collections.abc import Generator


class _HttpHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.headers.get("Authorization") != "Bearer runtime-token":
            self.send_response(401)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"path": self.path}).encode())

    def log_message(self, format: str, *args: str) -> None:
        return


@contextmanager
def _http_server() -> Generator[str, None, None]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HttpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@contextmanager
def _websocket_server() -> Generator[str, None, None]:
    def handler(connection: ServerConnection) -> None:
        connection.send(json.dumps({"type": "auth_required", "ha_version": "2026.8.3"}))
        assert json.loads(connection.recv()) == {
            "type": "auth",
            "access_token": "runtime-token",
        }
        connection.send(json.dumps({"type": "auth_ok", "ha_version": "2026.8.3"}))
        command = json.loads(connection.recv())
        connection.send(
            json.dumps({"id": command["id"] + 1, "type": "result", "success": True})
        )
        connection.send(
            json.dumps(
                {
                    "id": command["id"],
                    "type": "result",
                    "success": True,
                    "result": {"echo": command["type"]},
                }
            )
        )

    with serve(handler, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.socket.getsockname()
            yield f"http://{host}:{port}"
        finally:
            server.shutdown()
            thread.join()


def test_get_joins_path_and_sends_bearer_token() -> None:
    with (
        _http_server() as base_url,
        HomeAssistantRuntimeClient(base_url, "runtime-token") as client,
    ):
        response = client.get("/api/test?value=1")

    assert response.json() == {"path": "/api/test?value=1"}


def test_get_raises_for_error_status() -> None:
    with (
        _http_server() as base_url,
        HomeAssistantRuntimeClient(base_url, "wrong-token") as client,
        pytest.raises(httpx.HTTPStatusError, match="401"),
    ):
        client.get("/api/test")


def test_websocket_authenticates_and_correlates_command_results() -> None:
    with (
        _websocket_server() as base_url,
        HomeAssistantRuntimeClient(base_url, "runtime-token") as client,
        client.websocket() as websocket,
    ):
        result = websocket.command({"type": "smart_irrigation/config"})

    assert result == {"echo": "smart_irrigation/config"}
