from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from threading import Thread
from types import TracebackType
from typing import NamedTuple
from zipfile import ZipFile

from scripts.exploratory_runtime import HACS_ARCHIVE_URL, OPENSPRINKLER_ARCHIVE_URL


class ArchiveResponse(BytesIO):
    def __enter__(self) -> ArchiveResponse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def archive(entries: dict[str, str]) -> bytes:
    result = BytesIO()
    with ZipFile(result, "w") as archive_file:
        for name, content in entries.items():
            archive_file.writestr(name, content)
    return result.getvalue()


def valid_archives() -> dict[str, bytes]:
    opensprinkler_root = "hass-opensprinkler-fee462ce022aba267ffcabab078652414f7d7111"
    return {
        HACS_ARCHIVE_URL: archive(
            {"manifest.json": '{"domain":"hacs"}', "__init__.py": ""}
        ),
        OPENSPRINKLER_ARCHIVE_URL: archive(
            {
                f"{opensprinkler_root}/custom_components/opensprinkler/manifest.json": (
                    '{"domain":"opensprinkler"}'
                ),
                f"{opensprinkler_root}/custom_components/opensprinkler/__init__.py": "",
            }
        ),
    }


class RecordedRequest(NamedTuple):
    path: str
    headers: dict[str, str]
    body: bytes


@contextmanager
def onboarding_server(
    *, user_done: bool
) -> Iterator[tuple[str, list[RecordedRequest]]]:
    requests: list[RecordedRequest] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(RecordedRequest(self.path, dict(self.headers), b""))
            self._respond([{"step": "user", "done": user_done}])

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append(RecordedRequest(self.path, dict(self.headers), body))
            response = (
                {"auth_code": "local-auth-code"}
                if self.path == "/api/onboarding/users"
                else {"access_token": "returned-access-token", "token_type": "Bearer"}
            )
            self._respond(response)

        def _respond(
            self, payload: list[dict[str, bool | str]] | dict[str, str]
        ) -> None:
            content = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, format: str, *args: str) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}", requests
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
