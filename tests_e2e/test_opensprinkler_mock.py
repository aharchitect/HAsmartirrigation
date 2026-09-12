from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests_e2e import opensprinkler_mock as opensprinkler_mock_module
from tests_e2e.opensprinkler_mock import (
    ControllerRequest,
    OpenSprinklerMock,
    handle_controller_request,
    parse_controller_request,
)

PASSWORD_HASH = "dfb450efddbb5387197c84460623675b"


@pytest.fixture
def configure_event_loop() -> None:
    return None


@pytest.fixture
def enable_event_loop_debug() -> None:
    return None


def test_run_station_records_expected_query() -> None:
    accepted_requests: list[ControllerRequest] = []
    target = f"/cm?qo=0&t=300&pw={PASSWORD_HASH}&en=1&sid=0"

    response = handle_controller_request(target, accepted_requests)

    assert response.status_code == 200
    assert response.payload == {"result": 1}
    assert accepted_requests == [{"path": "/cm", "sid": 0, "en": 1, "t": 300, "qo": 0}]


def test_parse_run_station_query_is_order_independent() -> None:
    target = f"/cm?t=300&en=1&qo=0&sid=0&pw={PASSWORD_HASH}"

    request = parse_controller_request(target)

    assert request == {"path": "/cm", "sid": 0, "en": 1, "t": 300, "qo": 0}


def test_controller_state_returns_one_idle_enabled_station() -> None:
    accepted_requests: list[ControllerRequest] = []

    response = handle_controller_request(f"/ja?pw={PASSWORD_HASH}", accepted_requests)

    assert response.status_code == 200
    assert response.payload["settings"]["en"] == 1
    assert response.payload["settings"]["mac"] == "001122334455"
    assert response.payload["settings"]["ps"] == [[0, 0, 0]]
    assert response.payload["settings"]["lrun"] == [0, 0, 0, 0]
    assert response.payload["settings"]["rdst"] == 0
    assert response.payload["options"]["tz"] == 48
    assert response.payload["status"] == {"sn": [0], "nstations": 1}
    assert response.payload["stations"]["snames"] == ["E2E Station"]
    assert response.payload["programs"] == {"pd": []}
    assert accepted_requests == [{"path": "/ja"}]


def test_wait_for_request_returns_matching_journal_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a journal that receives the station command after its state request.
    journal = iter(
        [
            [{"path": "/ja"}],
            [{"path": "/ja"}, {"path": "/cm", "sid": 0, "t": 300}],
        ]
    )
    controller = OpenSprinklerMock()
    monkeypatch.setattr(controller, "requests", lambda: next(journal))
    monkeypatch.setattr(opensprinkler_mock_module.time, "sleep", lambda _: None)

    # When: the command path is awaited.
    request = controller.wait_for_request("/cm")

    # Then: the matching request is returned without waiting for its duration.
    assert request == {"path": "/cm", "sid": 0, "t": 300}


def test_wait_for_request_timeout_reports_latest_journal_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a journal containing only the latest controller state request.
    controller = OpenSprinklerMock()
    monkeypatch.setattr(controller, "requests", lambda: [{"path": "/ja"}])
    monotonic = iter([0.0, 11.0])
    monkeypatch.setattr(
        opensprinkler_mock_module,
        "time",
        SimpleNamespace(monotonic=monotonic.__next__, sleep=lambda _: None),
    )

    # When / Then: timeout diagnostics identify the missing path and latest request.
    with pytest.raises(
        RuntimeError,
        match=r"/cm.*latest request: \{'path': '/ja'\}",
    ):
        controller.wait_for_request("/cm")


@pytest.mark.parametrize(
    ("target", "expected_status", "expected_error"),
    [
        (
            f"/unsupported?pw={PASSWORD_HASH}",
            404,
            "unsupported_path",
        ),
        ("/ja?pw=incorrect", 401, "invalid_password"),
        (
            f"/cm?pw={PASSWORD_HASH}&sid=1&en=1&t=300&qo=0",
            400,
            "invalid_command",
        ),
        (
            f"/cm?pw={PASSWORD_HASH}&sid=0&en=1&t=300",
            400,
            "invalid_parameters",
        ),
    ],
)
def test_invalid_request_returns_explicit_error_without_journaling(
    target: str,
    expected_status: int,
    expected_error: str,
) -> None:
    accepted_requests: list[ControllerRequest] = []

    response = handle_controller_request(target, accepted_requests)

    assert response.status_code == expected_status
    assert response.payload == {"result": 0, "error": expected_error}
    assert accepted_requests == []


def test_mock_diagnostics_include_container_state_and_accepted_journal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a running mock with one accepted, credential-free request.
    controller = OpenSprinklerMock()
    controller._container = _FakeDiagnosticContainer()
    monkeypatch.setattr(controller, "requests", lambda: [{"path": "/ja"}])

    # When: failure diagnostics are collected.
    logs = controller.logs()
    metadata = json.loads(controller.metadata())

    # Then: operators can identify the mock and its accepted request state.
    assert logs.splitlines() == [
        "OPENSPRINKLER_READY",
        'OPENSPRINKLER_ACCEPTED {"path":"/ja"}',
    ]
    assert metadata == {
        "base_url": "http://opensprinkler-mock:8080",
        "container_id": "mock-container-id",
        "accepted_requests": [{"path": "/ja"}],
    }
    assert "password" not in controller.metadata()
    assert "token" not in controller.metadata()


class _FakeDiagnosticContainer:
    def get_logs(self) -> tuple[bytes, bytes]:
        return (
            b'OPENSPRINKLER_READY\nOPENSPRINKLER_ACCEPTED {"path":"/ja"}',
            b"",
        )

    def get_wrapped_container(self) -> _FakeWrappedContainer:
        return _FakeWrappedContainer()


class _FakeWrappedContainer:
    id = "mock-container-id"
