from __future__ import annotations

import json
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Final, NewType
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from websocket import WebSocket, create_connection

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

AccessToken = NewType("AccessToken", str)

_HTTP_TIMEOUT: Final = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)


class WebSocketCommandError(Exception):
    def __init__(self, command: JsonObject, response: JsonObject) -> None:
        self.command = command
        self.response = response
        super().__init__()

    def __str__(self) -> str:
        return f"Home Assistant WebSocket command failed: {self.response!r}"


class WebSocketProtocolError(Exception):
    def __init__(self, expected: str, response: JsonObject) -> None:
        self.expected = expected
        self.response = response
        super().__init__()

    def __str__(self) -> str:
        return f"expected {self.expected}, received {self.response!r}"


class HomeAssistantWebSocket(AbstractContextManager["HomeAssistantWebSocket"]):
    def __init__(self, base_url: str, token: AccessToken) -> None:
        parsed = urlparse(base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        websocket_url = urlunparse(
            (scheme, parsed.netloc, "/api/websocket", "", "", "")
        )
        self._connection: WebSocket = create_connection(
            websocket_url,
            timeout=30,
            http_proxy_host=None,
            http_proxy_port=None,
        )
        self._next_id = 1
        required = self._receive()
        if required.get("type") != "auth_required":
            raise WebSocketProtocolError("auth_required", required)
        self._connection.send(json.dumps({"type": "auth", "access_token": token}))
        authenticated = self._receive()
        if authenticated.get("type") != "auth_ok":
            raise WebSocketProtocolError("auth_ok", authenticated)

    def _receive(self) -> JsonObject:
        message = json.loads(self._connection.recv())
        if not isinstance(message, dict):
            raise WebSocketProtocolError("JSON object", {"received": repr(message)})
        return message

    def command(self, command: JsonObject) -> JsonValue:
        command_id = self._next_id
        self._next_id += 1
        self._connection.send(json.dumps({"id": command_id, **command}))
        while True:
            response = self._receive()
            if response.get("id") != command_id:
                continue
            if response.get("success") is not True:
                raise WebSocketCommandError(command, response)
            return response.get("result")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._connection.close()


class HomeAssistantRuntimeClient(AbstractContextManager["HomeAssistantRuntimeClient"]):
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = AccessToken(token)
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {token}"},
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
        )

    def get(self, path: str) -> httpx.Response:
        response = self._client.get(urljoin(f"{self.base_url}/", path.lstrip("/")))
        response.raise_for_status()
        return response

    def post(self, path: str, payload: JsonObject | None = None) -> httpx.Response:
        response = self._client.post(
            urljoin(f"{self.base_url}/", path.lstrip("/")), json=payload
        )
        response.raise_for_status()
        return response

    def post_service(self, domain: str, service: str, payload: JsonObject) -> JsonValue:
        return self.post(f"/api/services/{domain}/{service}", payload).json()

    def websocket(self) -> HomeAssistantWebSocket:
        return HomeAssistantWebSocket(self.base_url, self._token)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._client.close()
