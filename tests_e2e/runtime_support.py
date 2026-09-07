from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Final

_HA_REQUIREMENT: Final = re.compile(
    r"^homeassistant==(?P<version>[^\s#]+)$", re.MULTILINE
)
_SAFE_CONFIG_FILES: Final = ("configuration.yaml", "automations.yaml", "scripts.yaml")
_SAFE_RUNTIME_FILES: Final = ("home-assistant.log",)
_SAFE_STORAGE_FILES: Final = ("smart_irrigation.storage", "core.config_entries")


class HomeAssistantVersionError(Exception):
    def __init__(self, requirements_path: Path) -> None:
        self.requirements_path = requirements_path
        super().__init__()

    def __str__(self) -> str:
        return f"no exact Home Assistant pin found in {self.requirements_path}"


def home_assistant_version(requirements_path: Path) -> str:
    contents = requirements_path.read_text(encoding="utf-8")
    match = _HA_REQUIREMENT.search(contents)
    if match is None:
        raise HomeAssistantVersionError(requirements_path)
    return match.group("version")


def runtime_parent(repository: Path) -> Path:
    parent = repository / ".e2e-runtime"
    parent.mkdir(exist_ok=True)
    return parent


def copy_sanitized_artifacts(
    config_path: Path, destination: Path, container_logs: str
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for filename in _SAFE_CONFIG_FILES + _SAFE_RUNTIME_FILES:
        source = config_path / filename
        if source.is_file():
            shutil.copy2(source, destination / filename)
    storage_destination = destination / ".storage"
    for filename in _SAFE_STORAGE_FILES:
        source = config_path / ".storage" / filename
        if source.is_file():
            storage_destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, storage_destination / filename)
    (destination / "container.log").write_text(container_logs, encoding="utf-8")
