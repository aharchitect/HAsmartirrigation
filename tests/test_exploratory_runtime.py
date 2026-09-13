import json
import os
import subprocess
from pathlib import Path
from urllib.parse import parse_qs

import pytest
import yaml

import scripts.exploratory_commands as exploratory_commands
import scripts.exploratory_runtime as exploratory_runtime
from scripts.exploratory_runtime import (
    HACS_ARCHIVE_URL,
    OPENSPRINKLER_ARCHIVE_URL,
    ArchiveValidationError,
    ExploratoryPaths,
    create_initial_user,
    prepare_files,
)
from tests.exploratory_runtime_support import (
    ArchiveResponse,
    archive,
    onboarding_server,
    valid_archives,
)

COMPOSE_FILE = Path(__file__).parents[1] / "docker-compose.exploratory.yml"
REPOSITORY = COMPOSE_FILE.parent


def test_compose_homeassistant_uses_persistent_private_runtime() -> None:
    # Given / When
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    homeassistant = compose["services"]["homeassistant"]

    # Then
    assert set(compose["services"]) == {"homeassistant", "opensprinkler-mock"}
    assert homeassistant["image"] == (
        "ghcr.io/home-assistant/home-assistant:${HOME_ASSISTANT_VERSION}"
    )
    assert homeassistant["ports"] == ["127.0.0.1:8123:8123"]
    assert homeassistant["volumes"] == [
        ".e2e-exploratory/config:/config",
        "./custom_components:/config/local_custom_components:ro",
    ]
    assert homeassistant["networks"] == ["exploratory"]
    assert homeassistant["depends_on"] == {
        "opensprinkler-mock": {"condition": "service_healthy"}
    }
    assert "network_mode" not in homeassistant
    assert compose["networks"] == {"exploratory": {"driver": "bridge"}}


def test_compose_opensprinkler_mock_uses_existing_private_service() -> None:
    # Given / When
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    mock = compose["services"]["opensprinkler-mock"]

    # Then
    assert mock["image"] == "python:3.14-alpine"
    assert mock["volumes"] == [
        "./tests_e2e/opensprinkler_mock.py:/app/opensprinkler_mock.py:ro"
    ]
    assert mock["command"] == "python -u /app/opensprinkler_mock.py --serve"
    assert mock["expose"] == ["8080"]
    assert mock["networks"] == {"exploratory": {"aliases": ["opensprinkler-mock"]}}
    assert mock["healthcheck"]
    assert "network_mode" not in mock


def test_paths_are_scoped_to_exploratory_runtime(tmp_path: Path) -> None:
    # Given
    repository = tmp_path / "repository"

    # When
    paths = ExploratoryPaths.from_repository(repository)

    # Then
    assert paths.root == repository / ".e2e-exploratory"
    assert paths.config == paths.root / "config"
    assert paths.custom_components == paths.config / "custom_components"
    assert paths.hacs == paths.custom_components / "hacs"
    assert paths.opensprinkler == paths.custom_components / "opensprinkler"


def test_archive_urls_are_version_pinned() -> None:
    # Given / When / Then
    assert HACS_ARCHIVE_URL == (
        "https://github.com/hacs/integration/releases/download/2.0.5/hacs.zip"
    )
    assert OPENSPRINKLER_ARCHIVE_URL == (
        "https://github.com/vinteo/hass-opensprinkler/archive/"
        "fee462ce022aba267ffcabab078652414f7d7111.zip"
    )


def test_prepare_files_generates_config_and_live_component_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    repository = tmp_path / "repository"
    for component in ("smart_irrigation", "companion_component"):
        component_path = repository / "custom_components" / component
        component_path.mkdir(parents=True)
        (component_path / "manifest.json").write_text("{}", encoding="utf-8")
    archives = valid_archives()
    requested_urls: list[str] = []

    def open_archive(url: str, *, timeout: float) -> ArchiveResponse:
        requested_urls.append(url)
        assert timeout > 0
        return ArchiveResponse(archives[url])

    monkeypatch.setattr(exploratory_runtime, "urlopen", open_archive)
    credentials = {
        "EXPLORATORY_HA_USERNAME": "runtime-user",
        "EXPLORATORY_HA_PASSWORD": "never-write-this-password",
        "GITHUB_TOKEN": "never-write-this-token",
    }

    # When
    paths = prepare_files(repository, credentials)

    # Then
    configuration = (paths.config / "configuration.yaml").read_text(encoding="utf-8")
    for section in (
        "homeassistant:",
        "http:",
        "api:",
        "auth:",
        "config:",
        "frontend:",
        "onboarding:",
        "automation: !include automations.yaml",
        "script: !include scripts.yaml",
    ):
        assert section in configuration
    assert all(value not in configuration for value in credentials.values())
    for component in ("smart_irrigation", "companion_component"):
        link = paths.custom_components / component
        assert link.is_symlink()
        assert link.readlink() == Path(f"/config/local_custom_components/{component}")
    assert requested_urls == [HACS_ARCHIVE_URL, OPENSPRINKLER_ARCHIVE_URL]


def test_prepare_files_is_idempotent_and_preserves_existing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    repository = tmp_path / "repository"
    local_component = repository / "custom_components" / "smart_irrigation"
    local_component.mkdir(parents=True)
    (local_component / "manifest.json").write_text("{}", encoding="utf-8")
    archives = valid_archives()
    requested_urls: list[str] = []

    def open_archive(url: str, *, timeout: float) -> ArchiveResponse:
        requested_urls.append(url)
        assert timeout > 0
        return ArchiveResponse(archives[url])

    monkeypatch.setattr(exploratory_runtime, "urlopen", open_archive)
    paths = prepare_files(repository, {})
    existing_configuration = "homeassistant:\n  name: Existing runtime\n"
    (paths.config / "configuration.yaml").write_text(
        existing_configuration, encoding="utf-8"
    )
    hacs_marker = paths.hacs / "preserve-me"
    opensprinkler_marker = paths.opensprinkler / "preserve-me"
    hacs_marker.write_text("hacs", encoding="utf-8")
    opensprinkler_marker.write_text("opensprinkler", encoding="utf-8")

    # When
    repeated_paths = prepare_files(repository, {})

    # Then
    assert repeated_paths == paths
    assert requested_urls == [HACS_ARCHIVE_URL, OPENSPRINKLER_ARCHIVE_URL]
    assert (paths.config / "configuration.yaml").read_text(
        encoding="utf-8"
    ) == existing_configuration
    assert hacs_marker.read_text(encoding="utf-8") == "hacs"
    assert opensprinkler_marker.read_text(encoding="utf-8") == "opensprinkler"


def test_prepare_files_rejects_archive_members_outside_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    repository = tmp_path / "repository"
    (repository / "custom_components").mkdir(parents=True)
    malicious_archive = archive(
        {
            "manifest.json": '{"domain":"hacs"}',
            "../escaped": "unsafe",
        }
    )
    monkeypatch.setattr(
        exploratory_runtime,
        "urlopen",
        lambda url, *, timeout: ArchiveResponse(malicious_archive),
    )

    # When / Then
    with pytest.raises(ArchiveValidationError):
        prepare_files(repository, {})
    assert not (repository / ".e2e-exploratory" / "escaped").exists()


def test_prepare_files_rejects_archive_without_expected_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    repository = tmp_path / "repository"
    (repository / "custom_components").mkdir(parents=True)
    archive_without_manifest = archive({"__init__.py": ""})
    monkeypatch.setattr(
        exploratory_runtime,
        "urlopen",
        lambda url, *, timeout: ArchiveResponse(archive_without_manifest),
    )

    # When / Then
    with pytest.raises(ArchiveValidationError):
        prepare_files(repository, {})


def test_create_initial_user_uses_bearer_free_onboarding_exchange(
    capsys: pytest.CaptureFixture[str], socket_enabled: None
) -> None:
    # Given
    username = "runtime-user"
    password = "never-print-this-password"

    # When
    with onboarding_server(user_done=False) as (base_url, requests):
        created = create_initial_user(base_url, username, password)

    # Then
    assert created is True
    assert [request.path for request in requests] == [
        "/api/onboarding",
        "/api/onboarding/users",
        "/auth/token",
    ]
    assert all("Authorization" not in request.headers for request in requests)
    assert json.loads(requests[1].body) == {
        "client_id": f"{base_url}/",
        "language": "en",
        "name": username,
        "password": password,
        "username": username,
    }
    assert parse_qs(requests[2].body.decode()) == {
        "client_id": [f"{base_url}/"],
        "code": ["local-auth-code"],
        "grant_type": ["authorization_code"],
    }
    captured = capsys.readouterr()
    assert password not in captured.out
    assert "returned-access-token" not in captured.out


def test_create_initial_user_is_noop_when_onboarding_is_complete(
    socket_enabled: None,
) -> None:
    # Given / When
    with onboarding_server(user_done=True) as (base_url, requests):
        created = create_initial_user(base_url, "runtime-user", "runtime-password")

    # Then
    assert created is False
    assert [request.path for request in requests] == ["/api/onboarding"]


def test_make_exploratory_reset_reaches_guard_when_force_is_missing() -> None:
    # Given
    environment = {key: value for key, value in os.environ.items() if key != "FORCE"}

    # When
    result = subprocess.run(
        ("make", "--silent", "exploratory-reset"),
        cwd=REPOSITORY,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    # Then
    assert result.returncode != 0
    assert "Exploratory reset requires FORCE=1" in result.stderr
    assert "Traceback" not in result.stderr


def test_setup_runtime_retries_when_ha_resets_readiness_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    attempts = 0
    monkeypatch.setattr(exploratory_commands, "prepare_files", lambda *_: None)
    monkeypatch.setattr(exploratory_commands, "run_compose", lambda *_: None)

    def create_user(*_: str) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionResetError(104, "Connection reset by peer")
        return True

    monkeypatch.setattr(exploratory_commands, "create_initial_user", create_user)

    # When
    created = exploratory_commands.setup_runtime(tmp_path, {})

    # Then
    assert created is True
    assert attempts == 2
