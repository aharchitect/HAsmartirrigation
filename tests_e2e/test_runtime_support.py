from __future__ import annotations

from pathlib import Path

from tests_e2e.runtime_support import (
    copy_sanitized_artifacts,
    home_assistant_version,
    runtime_parent,
)


def test_home_assistant_version_comes_from_test_requirements(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.test.txt"
    requirements.write_text(
        "pytest==9.0.3\nhomeassistant==2026.8.3\n", encoding="utf-8"
    )

    version = home_assistant_version(requirements)

    assert version == "2026.8.3"


def test_artifacts_exclude_auth_and_database_files(tmp_path: Path) -> None:
    config = tmp_path / "config"
    storage = config / ".storage"
    storage.mkdir(parents=True)
    (config / "configuration.yaml").write_text("homeassistant:\n", encoding="utf-8")
    (config / "home-assistant.log").write_text("runtime log", encoding="utf-8")
    (config / "home-assistant_v2.db").write_text("database", encoding="utf-8")
    (storage / "auth").write_text("secret token", encoding="utf-8")
    (storage / "auth_provider.homeassistant").write_text("password", encoding="utf-8")
    (storage / "smart_irrigation.storage").write_text("zone data", encoding="utf-8")
    destination = tmp_path / "artifacts"

    copy_sanitized_artifacts(config, destination, "container logs")

    assert (destination / "configuration.yaml").is_file()
    assert (destination / "home-assistant.log").is_file()
    assert (destination / "container.log").read_text(
        encoding="utf-8"
    ) == "container logs"
    assert (destination / ".storage" / "smart_irrigation.storage").is_file()
    assert not (destination / ".storage" / "auth").exists()
    assert not (destination / ".storage" / "auth_provider.homeassistant").exists()
    assert not (destination / "home-assistant_v2.db").exists()


def test_runtime_parent_is_inside_repository_for_confined_docker(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()

    parent = runtime_parent(repository)

    assert parent == repository / ".e2e-runtime"
    assert parent.is_dir()
