from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import TracebackType
from typing import Self
from zipfile import ZipFile

import httpx
import pytest

from tests_e2e import conftest as e2e_conftest
from tests_e2e import runtime as runtime_module
from tests_e2e.runtime import RuntimeStartupError, stage_config, start_runtime
from tests_e2e.runtime_support import (
    RuntimeDiagnostics,
    copy_sanitized_artifacts,
    home_assistant_version,
    runtime_parent,
)


@pytest.fixture
def configure_event_loop() -> None:
    return None


@pytest.fixture
def enable_event_loop_debug() -> None:
    return None


def _write_runtime_repository(repository: Path) -> None:
    fixtures = repository / "tests_e2e" / "fixtures"
    fixtures.mkdir(parents=True)
    for filename in ("configuration.yaml", "automations.yaml", "scripts.yaml"):
        (fixtures / filename).write_text("", encoding="utf-8")
    panel = (
        repository
        / "custom_components"
        / "smart_irrigation"
        / "frontend"
        / "dist"
        / "smart-irrigation.js"
    )
    panel.parent.mkdir(parents=True)
    panel.write_text("runtime bundle", encoding="utf-8")


def test_home_assistant_version_comes_from_test_requirements(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.test.txt"
    requirements.write_text(
        "pytest==9.0.3\nhomeassistant==2026.8.3\n", encoding="utf-8"
    )

    version = home_assistant_version(requirements)

    assert version == "2026.8.3"


def test_artifacts_preserve_allowlisted_diagnostics_and_redact_secrets(
    tmp_path: Path,
) -> None:
    # Given: runtime files contain both useful diagnostics and secret-bearing state.
    config = tmp_path / "config"
    storage = config / ".storage"
    storage.mkdir(parents=True)
    (config / "configuration.yaml").write_text("homeassistant:\n", encoding="utf-8")
    (config / "home-assistant.log").write_text(
        "runtime log access_token=ha-file-token", encoding="utf-8"
    )
    (config / "home-assistant_v2.db").write_text("database", encoding="utf-8")
    (storage / "auth").write_text("secret token", encoding="utf-8")
    (storage / "auth_provider.homeassistant").write_text("password", encoding="utf-8")
    (storage / "smart_irrigation.storage").write_text(
        'zone data with "api_key": "weather-secret"', encoding="utf-8"
    )
    (storage / "core.config_entries").write_text(
        'entry with "password": "controller-secret"', encoding="utf-8"
    )
    destination = tmp_path / "artifacts"

    # When: HA and mock diagnostics are preserved through the artifact allowlist.
    copy_sanitized_artifacts(
        config,
        destination,
        RuntimeDiagnostics(
            home_assistant_logs="HA failed Authorization: Bearer ha-access-token",
            opensprinkler_logs="OPENSPRINKLER_READY",
            opensprinkler_metadata='{"accepted_requests":[{"path":"/ja"}]}',
        ),
    )

    # Then: useful diagnostics remain, while secret-bearing files and values do not.
    assert (destination / "configuration.yaml").is_file()
    assert "runtime log" in (destination / "home-assistant.log").read_text(
        encoding="utf-8"
    )
    assert "HA failed" in (destination / "container.log").read_text(encoding="utf-8")
    assert (destination / "opensprinkler-mock.log").read_text(
        encoding="utf-8"
    ) == "OPENSPRINKLER_READY"
    assert (destination / "opensprinkler-metadata.json").read_text(
        encoding="utf-8"
    ) == '{"accepted_requests":[{"path":"/ja"}]}'
    assert not (destination / ".storage" / "auth").exists()
    assert not (destination / ".storage" / "auth_provider.homeassistant").exists()
    assert not (destination / ".storage" / "smart_irrigation.storage").exists()
    assert not (destination / ".storage" / "core.config_entries").exists()
    assert not (destination / "home-assistant_v2.db").exists()
    artifact_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in destination.rglob("*")
        if path.is_file()
    )
    assert "ha-file-token" not in artifact_text
    assert "ha-access-token" not in artifact_text
    assert "weather-secret" not in artifact_text
    assert "controller-secret" not in artifact_text


def test_failed_runtime_reports_and_preserves_ha_and_mock_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # Given: debug artifacts are enabled for a failed runtime with HA and mock state.
    monkeypatch.setenv("E2E_KEEP_ARTIFACTS", "1")
    monkeypatch.setattr(runtime_module.time, "time", lambda: 1234)
    repository = tmp_path / "repository"
    config = tmp_path / "config"
    config.mkdir()
    runtime = _FakeArtifactRuntime(config)

    # When: fixture teardown preserves failure diagnostics.
    destination = runtime_module.preserve_debug_artifacts(repository, runtime, True)

    # Then: console output and sanitized files identify both systems.
    output = capsys.readouterr().out
    assert "Home Assistant container logs:\nHA startup state" in output
    assert "OpenSprinkler mock logs:\nOPENSPRINKLER_READY" in output
    assert '"container_id":"mock-container-id"' in output
    assert destination == repository / ".e2e-artifacts" / "failure-1234"
    assert (destination / "container.log").is_file()
    assert (destination / "opensprinkler-mock.log").is_file()
    assert (destination / "opensprinkler-metadata.json").is_file()


def test_runtime_parent_is_inside_repository_for_confined_docker(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()

    parent = runtime_parent(repository)

    assert parent == repository / ".e2e-runtime"
    assert parent.is_dir()


def test_stage_config_copies_checked_out_opensprinkler_integration(
    tmp_path: Path,
) -> None:
    # Given
    repository = tmp_path / "repository"
    _write_runtime_repository(repository)
    opensprinkler_source = tmp_path / "hass-opensprinkler"
    integration = opensprinkler_source / "custom_components" / "opensprinkler"
    integration.mkdir(parents=True)
    (integration / "manifest.json").write_text(
        '{"domain":"opensprinkler"}', encoding="utf-8"
    )
    (integration / "switch.py").write_text("PLATFORM = 'switch'", encoding="utf-8")
    config_path = tmp_path / "config"

    # When
    stage_config(repository, config_path, opensprinkler_source)

    # Then
    destination = config_path / "custom_components" / "opensprinkler"
    assert (destination / "manifest.json").is_file()
    assert (destination / "switch.py").read_text(encoding="utf-8") == (
        "PLATFORM = 'switch'"
    )


def test_stage_config_rejects_opensprinkler_source_without_manifest(
    tmp_path: Path,
) -> None:
    # Given
    repository = tmp_path / "repository"
    _write_runtime_repository(repository)
    opensprinkler_source = tmp_path / "hass-opensprinkler"
    (opensprinkler_source / "custom_components" / "opensprinkler").mkdir(parents=True)

    # When / Then
    with pytest.raises(RuntimeStartupError, match="OpenSprinkler manifest is missing"):
        stage_config(repository, tmp_path / "config", opensprinkler_source)


def test_runtime_containers_share_one_network_and_close_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given
    events: list[str] = []
    network = _FakeNetwork(events)
    mock = _FakeOpenSprinklerMock(events)
    runtime = _FakeHomeAssistantRuntime(events)
    monkeypatch.setattr(e2e_conftest, "DockerNetwork", lambda: network)
    monkeypatch.setattr(e2e_conftest, "OpenSprinklerMock", lambda: mock)
    monkeypatch.setattr(
        e2e_conftest,
        "start_runtime",
        lambda repository, config_path, runtime_network, opensprinkler_mock: (
            runtime.record_start(runtime_network)
        ),
    )

    # When
    with e2e_conftest._runtime_containers(tmp_path, tmp_path / "config") as result:
        assert result is runtime

    # Then
    assert mock.network is network
    assert runtime.network is network
    assert events == [
        "network-enter",
        "mock-start",
        "runtime-start",
        "runtime-close",
        "mock-close",
        "network-exit",
    ]


def test_start_runtime_attaches_home_assistant_to_shared_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given
    network = _FakeNetwork([])
    container = _FakeDockerContainer()
    monkeypatch.setattr(runtime_module, "DockerContainer", lambda image: container)
    monkeypatch.setattr(
        runtime_module, "home_assistant_version", lambda requirements: "2026.8.3"
    )
    monkeypatch.setattr(runtime_module, "_wait_for_home_assistant", lambda url: None)
    monkeypatch.setattr(runtime_module, "_onboard", lambda url: "token")
    monkeypatch.setattr(
        runtime_module,
        "HomeAssistantRuntimeClient",
        lambda url, token: _FakeRuntimeClient(url),
    )
    monkeypatch.setattr(
        runtime_module,
        "_create_opensprinkler_integration",
        lambda client, base_url: None,
    )
    monkeypatch.setattr(
        runtime_module,
        "_wait_for_opensprinkler_station",
        lambda client: "switch.e2e_station_enabled",
    )
    monkeypatch.setattr(runtime_module, "_create_integration", lambda client: None)
    monkeypatch.setattr(
        runtime_module, "_create_zone", lambda client, station_entity_id: None
    )
    monkeypatch.setattr(runtime_module, "_wait_for_loaded_runtime", lambda client: None)
    opensprinkler_mock = _FakeOpenSprinklerMock([])

    # When
    runtime = start_runtime(tmp_path, tmp_path / "config", network, opensprinkler_mock)

    # Then
    assert container.network is network
    assert runtime.opensprinkler_mock is opensprinkler_mock


def test_opensprinkler_source_archive_is_pinned_and_extracted(
    tmp_path: Path,
) -> None:
    # Given
    archive = BytesIO()
    archive_root = "hass-opensprinkler-fee462ce022aba267ffcabab078652414f7d7111"
    with ZipFile(archive, "w") as source_zip:
        source_zip.writestr(
            f"{archive_root}/custom_components/opensprinkler/manifest.json",
            '{"domain":"opensprinkler"}',
        )
    requested_urls: list[str] = []

    def archive_response(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=archive.getvalue())

    # When
    with httpx.Client(transport=httpx.MockTransport(archive_response)) as client:
        source = e2e_conftest._extract_opensprinkler_source(tmp_path / "source", client)

    # Then
    assert requested_urls == [
        "https://github.com/vinteo/hass-opensprinkler/archive/"
        "fee462ce022aba267ffcabab078652414f7d7111.zip"
    ]
    assert (source / "custom_components" / "opensprinkler" / "manifest.json").is_file()


class _FakeNetwork:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def __enter__(self) -> _FakeNetwork:
        self.events.append("network-enter")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.events.append("network-exit")


class _FakeOpenSprinklerMock:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.network: _FakeNetwork | None = None

    @property
    def base_url(self) -> str:
        return "http://opensprinkler-mock:8080"

    def start(self, network: _FakeNetwork) -> None:
        self.network = network
        self.events.append("mock-start")

    def close(self) -> None:
        self.events.append("mock-close")


class _FakeHomeAssistantRuntime:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.network: _FakeNetwork | None = None

    def record_start(self, network: _FakeNetwork) -> _FakeHomeAssistantRuntime:
        self.network = network
        self.events.append("runtime-start")
        return self

    def close(self) -> None:
        self.events.append("runtime-close")


class _FakeDockerContainer:
    def __init__(self) -> None:
        self.network: _FakeNetwork | None = None

    def with_volume_mapping(self, source: str, destination: str, mode: str) -> Self:
        return self

    def with_bind_ports(self, container: int, host: tuple[str, None]) -> Self:
        return self

    def with_env(self, name: str, value: str) -> Self:
        return self

    def with_network(self, network: _FakeNetwork) -> Self:
        self.network = network
        return self

    def start(self) -> None:
        return None

    def get_exposed_port(self, port: int) -> int:
        return 8123


class _FakeRuntimeClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


class _FakeArtifactOpenSprinklerMock:
    def logs(self) -> str:
        return "OPENSPRINKLER_READY"

    def metadata(self) -> str:
        return '{"container_id":"mock-container-id","accepted_requests":[]}'


class _FakeArtifactRuntime:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.opensprinkler_mock = _FakeArtifactOpenSprinklerMock()

    def logs(self) -> str:
        return "HA startup state"

    def diagnostics(self) -> RuntimeDiagnostics:
        return RuntimeDiagnostics(
            home_assistant_logs=self.logs(),
            opensprinkler_logs=self.opensprinkler_mock.logs(),
            opensprinkler_metadata=self.opensprinkler_mock.metadata(),
        )
