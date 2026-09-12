from __future__ import annotations

import hashlib
import hmac
import json
import socket
import sys
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Final, Literal, NotRequired, TypedDict
from urllib.parse import parse_qs, urlsplit

if __name__ != "__main__":
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.network import Network as DockerNetwork
    from testcontainers.core.wait_strategies import LogMessageWaitStrategy

    from tests_e2e.container_runtime import container_logs

_PASSWORD_HASH: Final = hashlib.md5(b"test-password").hexdigest()  # noqa: S324
_CONTAINER_ALIAS: Final = "opensprinkler-mock"
_CONTAINER_PORT: Final = 8080
_JOURNAL_PREFIX: Final = "OPENSPRINKLER_ACCEPTED "
_IMAGE: Final = "python:3.14-alpine"
_REQUEST_TIMEOUT_SECONDS: Final = 10.0
_REQUEST_POLL_SECONDS: Final = 0.05


class ControllerRequest(TypedDict):
    path: Literal["/ja", "/cm"]
    sid: NotRequired[int]
    en: NotRequired[int]
    t: NotRequired[int]
    qo: NotRequired[int]


type JsonValue = str | int | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ControllerResponse:
    status_code: int
    payload: JsonObject


@dataclass(frozen=True, slots=True)
class ControllerRequestError(Exception):
    status_code: int
    code: str

    def __str__(self) -> str:
        return self.code


def parse_controller_request(target: str) -> ControllerRequest:
    parsed = urlsplit(target)
    if parsed.path not in {"/ja", "/cm"}:
        raise ControllerRequestError(404, "unsupported_path")

    query = parse_qs(parsed.query, keep_blank_values=True)
    expected_keys = {"pw"} if parsed.path == "/ja" else {"pw", "sid", "en", "t", "qo"}
    if set(query) != expected_keys or any(
        len(values) != 1 for values in query.values()
    ):
        raise ControllerRequestError(400, "invalid_parameters")
    if not hmac.compare_digest(query["pw"][0], _PASSWORD_HASH):
        raise ControllerRequestError(401, "invalid_password")

    if parsed.path == "/ja":
        return {"path": "/ja"}

    try:
        sid, en, duration, queue_option = (
            int(query[name][0]) for name in ("sid", "en", "t", "qo")
        )
    except ValueError as error:
        raise ControllerRequestError(400, "invalid_parameters") from error
    if (sid, en, duration, queue_option) != (0, 1, 300, 0):
        raise ControllerRequestError(400, "invalid_command")
    return {
        "path": "/cm",
        "sid": sid,
        "en": en,
        "t": duration,
        "qo": queue_option,
    }


def handle_controller_request(
    target: str, accepted_requests: list[ControllerRequest]
) -> ControllerResponse:
    try:
        request = parse_controller_request(target)
    except ControllerRequestError as error:
        return ControllerResponse(
            status_code=error.status_code,
            payload={"result": 0, "error": error.code},
        )

    accepted_requests.append(request)
    if request["path"] == "/cm":
        return ControllerResponse(status_code=200, payload={"result": 1})
    return ControllerResponse(
        status_code=200,
        payload={
            "settings": {
                "devt": 0,
                "nbrd": 0,
                "en": 1,
                "mac": "001122334455",
                "ps": [[0, 0, 0]],
                "lrun": [0, 0, 0, 0],
                "rdst": 0,
            },
            "options": {"fwv": 219, "tz": 48},
            "status": {"sn": [0], "nstations": 1},
            "programs": {"pd": []},
            "stations": {
                "snames": ["E2E Station"],
                "stn_dis": [0],
                "stn_grp": [0],
            },
        },
    )


class OpenSprinklerMock:
    def __init__(self) -> None:
        self._container: DockerContainer | None = None
        self._host_port: int | None = None

    @property
    def base_url(self) -> str:
        return f"http://{_CONTAINER_ALIAS}:{_CONTAINER_PORT}"

    def start(self, network: DockerNetwork) -> None:
        module_path = Path(__file__).resolve()
        container = (
            DockerContainer(_IMAGE)
            .with_volume_mapping(module_path, "/app/opensprinkler_mock.py", "ro")
            .with_command("python -u /app/opensprinkler_mock.py --serve")
            .with_exposed_ports(_CONTAINER_PORT)
            .with_network(network)
            .with_network_aliases(_CONTAINER_ALIAS)
            .waiting_for(LogMessageWaitStrategy("OPENSPRINKLER_READY"))
        )
        container.start()
        self._container = container
        self._host_port = int(container.get_exposed_port(_CONTAINER_PORT))

    def wait_until_ready(self) -> None:
        if self._host_port is None:
            raise RuntimeError("OpenSprinkler mock has not been started")
        with socket.create_connection(("127.0.0.1", self._host_port), timeout=2):
            return

    def logs(self) -> str:
        if self._container is None:
            return ""
        return container_logs(self._container)

    def metadata(self) -> str:
        container_id = "unavailable"
        if self._container is not None:
            wrapped = self._container.get_wrapped_container()
            if wrapped is not None:
                container_id = wrapped.id
        return json.dumps(
            {
                "base_url": self.base_url,
                "container_id": container_id,
                "accepted_requests": self.requests(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def requests(self) -> list[dict[str, object]]:
        requests: list[dict[str, object]] = []
        for line in self.logs().splitlines():
            if line.startswith(_JOURNAL_PREFIX):
                requests.append(json.loads(line.removeprefix(_JOURNAL_PREFIX)))
        return requests

    def wait_for_request(self, path: str) -> dict[str, object]:
        deadline = time.monotonic() + _REQUEST_TIMEOUT_SECONDS
        latest_request: dict[str, object] | None = None
        while True:
            requests = self.requests()
            if requests:
                latest_request = requests[-1]
            for request in requests:
                if request.get("path") == path:
                    return request
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"timed out waiting for {path}; latest request: {latest_request!r}"
                )
            time.sleep(_REQUEST_POLL_SECONDS)

    def close(self) -> None:
        if self._container is not None:
            self._container.stop()
            self._container = None
            self._host_port = None


_SERVER_REQUESTS: list[ControllerRequest] = []


class _ControllerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        previous_count = len(_SERVER_REQUESTS)
        response = handle_controller_request(self.path, _SERVER_REQUESTS)
        if len(_SERVER_REQUESTS) > previous_count:
            print(
                _JOURNAL_PREFIX + json.dumps(_SERVER_REQUESTS[-1], sort_keys=True),
                flush=True,
            )
        body = json.dumps(response.payload, separators=(",", ":")).encode()
        self.send_response(response.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def _serve() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", _CONTAINER_PORT), _ControllerHandler)
    print("OPENSPRINKLER_READY", flush=True)
    server.serve_forever()


if __name__ == "__main__" and sys.argv[1:] == ["--serve"]:
    _serve()
