from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path
from typing import Final

import httpx
from docker.errors import DockerException
from testcontainers.core.container import DockerContainer

from tests_e2e.container_runtime import (
    STOP_TIMEOUT_SECONDS,
    container_logs,
    remove_container,
)
from tests_e2e.ha_client import HomeAssistantRuntimeClient, JsonObject, JsonValue
from tests_e2e.runtime_support import copy_sanitized_artifacts, home_assistant_version

_CONTAINER_PORT: Final = 8123
_STARTUP_TIMEOUT_SECONDS: Final = 180
_CLIENT_ID: Final = "http://localhost:8123/"
_USERNAME: Final = "smart-irrigation-e2e"
_PASSWORD: Final = "smart-irrigation-e2e-password"


class RuntimeStartupError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__()

    def __str__(self) -> str:
        return self.detail


class HomeAssistantRuntime:
    def __init__(
        self,
        container: DockerContainer,
        client: HomeAssistantRuntimeClient,
        config_path: Path,
    ) -> None:
        self.container = container
        self.client = client
        self.config_path = config_path

    @property
    def base_url(self) -> str:
        return self.client.base_url

    @property
    def container_id(self) -> str:
        return self.container.get_wrapped_container().id

    def websocket_command(self, command: JsonObject) -> JsonValue:
        with self.client.websocket() as websocket:
            return websocket.command(command)

    def restart(self) -> None:
        wrapped = self.container.get_wrapped_container()
        wrapped.stop(timeout=STOP_TIMEOUT_SECONDS)
        wrapped.start()
        mapped_port = self.container.get_exposed_port(_CONTAINER_PORT)
        self.client.base_url = f"http://127.0.0.1:{mapped_port}"
        _wait_for_home_assistant(self.base_url)
        _wait_for_loaded_runtime(self.client)

    def logs(self) -> str:
        return container_logs(self.container)

    def close(self) -> None:
        try:
            self.client.__exit__(None, None, None)
        finally:
            remove_container(self.container)


def stage_config(repository: Path, config_path: Path) -> None:
    fixture_path = repository / "tests_e2e" / "fixtures"
    config_path.mkdir(parents=True)
    for filename in ("configuration.yaml", "automations.yaml", "scripts.yaml"):
        shutil.copy2(fixture_path / filename, config_path / filename)
    source = repository / "custom_components" / "smart_irrigation"
    destination = config_path / "custom_components" / "smart_irrigation"
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("node_modules", "__pycache__", "tests"),
    )
    panel = destination / "frontend" / "dist" / "smart-irrigation.js"
    if not panel.is_file():
        raise RuntimeStartupError(f"frontend bundle is missing: {panel}")


def start_runtime(repository: Path, config_path: Path) -> HomeAssistantRuntime:
    version = home_assistant_version(repository / "requirements.test.txt")
    image = f"ghcr.io/home-assistant/home-assistant:{version}"
    try:
        container = (
            DockerContainer(image)
            .with_volume_mapping(str(config_path), "/config", "rw")
            .with_bind_ports(_CONTAINER_PORT, ("127.0.0.1", None))
            .with_env("TZ", "UTC")
        )
    except DockerException as error:
        raise RuntimeStartupError(
            "Docker Engine is unavailable. Start Docker and verify that the current "
            "user can access its daemon."
        ) from error
    try:
        container.start()
        base_url = f"http://127.0.0.1:{container.get_exposed_port(_CONTAINER_PORT)}"
        _wait_for_home_assistant(base_url)
        token = _onboard(base_url)
        client = HomeAssistantRuntimeClient(base_url, token)
        _create_integration(client)
        _create_zone(client)
        _wait_for_loaded_runtime(client)
        runtime = HomeAssistantRuntime(container, client, config_path)
        if os.environ.get("E2E_KEEP_ARTIFACTS") == "1":
            print(f"HA runtime {runtime.container_id} at {runtime.base_url}")
        return runtime
    except (
        DockerException,
        httpx.HTTPError,
        RuntimeStartupError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        logs = container_logs(container)
        if logs:
            print(logs, file=sys.stderr)
        try:
            if os.environ.get("E2E_KEEP_ARTIFACTS") == "1":
                destination = (
                    repository
                    / ".e2e-artifacts"
                    / f"startup-failure-{int(time.time())}"
                )
                copy_sanitized_artifacts(config_path, destination, logs)
                print(f"Sanitized E2E artifacts: {destination}", file=sys.stderr)
        finally:
            remove_container(container)
        raise RuntimeStartupError(
            f"Home Assistant runtime startup failed: {error}. "
            "Ensure Docker Engine is running and accessible."
        ) from error


def preserve_debug_artifacts(
    repository: Path, runtime: HomeAssistantRuntime, failed: bool
) -> Path | None:
    if os.environ.get("E2E_KEEP_ARTIFACTS") != "1":
        return None
    status = "failure" if failed else "debug"
    destination = repository / ".e2e-artifacts" / f"{status}-{int(time.time())}"
    copy_sanitized_artifacts(runtime.config_path, destination, runtime.logs())
    print(f"Sanitized E2E artifacts: {destination}")
    return destination


def _wait_for_home_assistant(base_url: str) -> None:
    deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
    last_error = "no response"
    with httpx.Client(timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(f"{base_url}/api/onboarding")
                if response.status_code == 200:
                    return
                last_error = f"HTTP {response.status_code}"
            except httpx.HTTPError as error:
                last_error = str(error)
            time.sleep(1)
    raise RuntimeStartupError(f"timed out waiting for {base_url}: {last_error}")


def _onboard(base_url: str) -> str:
    with httpx.Client(timeout=30.0) as client:
        user_response = client.post(
            f"{base_url}/api/onboarding/users",
            json={
                "client_id": _CLIENT_ID,
                "name": "Smart Irrigation E2E",
                "username": _USERNAME,
                "password": _PASSWORD,
                "language": "en",
            },
        )
        user_response.raise_for_status()
        auth_code = user_response.json()["auth_code"]
        token_response = client.post(
            f"{base_url}/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "client_id": _CLIENT_ID,
            },
        )
        token_response.raise_for_status()
        return str(token_response.json()["access_token"])


def _create_integration(client: HomeAssistantRuntimeClient) -> None:
    flow = client.post(
        "/api/config/config_entries/flow", {"handler": "smart_irrigation"}
    ).json()
    result = client.post(
        f"/api/config/config_entries/flow/{flow['flow_id']}",
        {"name": "Runtime Test"},
    ).json()
    if result.get("type") != "create_entry":
        raise RuntimeStartupError(f"config flow did not create an entry: {result!r}")


def _create_zone(client: HomeAssistantRuntimeClient) -> None:
    client.post(
        "/api/smart_irrigation/zones",
        {
            "id": 7,
            "name": "Runtime Zone",
            "size": 100.0,
            "throughput": 10.0,
            "state": "disabled",
            "module": 1,
            "mapping": 0,
            "multiplier": 1.0,
            "lead_time": 0.0,
            "maximum_duration": 3600.0,
            "maximum_bucket": 24.0,
            "drainage_rate": 50.8,
        },
    )


def _wait_for_loaded_runtime(client: HomeAssistantRuntimeClient) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        entries = client.get(
            "/api/config/config_entries/entry?domain=smart_irrigation"
        ).json()
        states = client.get("/api/states").json()
        if (
            entries
            and entries[0].get("state") == "loaded"
            and any(
                state.get("entity_id") == "sensor.smart_irrigation_runtime_zone"
                for state in states
            )
        ):
            return
        time.sleep(0.25)
    raise RuntimeStartupError(
        "Smart Irrigation entry or deterministic entities did not load"
    )
