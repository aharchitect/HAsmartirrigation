from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_HA_REQUIREMENT: Final = re.compile(
    r"^homeassistant==(?P<version>[^\s#]+)$", re.MULTILINE
)
_SAFE_CONFIG_FILES: Final = ("configuration.yaml", "automations.yaml", "scripts.yaml")
_SAFE_RUNTIME_FILES: Final = ("home-assistant.log",)
_SECRET_VALUE: Final = re.compile(
    r"(?i)(authorization\s*:\s*bearer\s+|"
    r"[\"']?(?:access_token|refresh_token|client_secret|api_key|password|pw|token)"
    r"[\"']?\s*[:=]\s*[\"']?)([^\"'\s,&}]+)"
)
_JWT: Final = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_REDACTED: Final = "[REDACTED]"


@dataclass(frozen=True, slots=True)
class RuntimeDiagnostics:
    home_assistant_logs: str
    opensprinkler_logs: str
    opensprinkler_metadata: str

    def console_text(self) -> str:
        sanitized = self.sanitized()
        return (
            "Home Assistant container logs:\n"
            f"{sanitized.home_assistant_logs}\n"
            "OpenSprinkler mock logs:\n"
            f"{sanitized.opensprinkler_logs}\n"
            "OpenSprinkler mock metadata:\n"
            f"{sanitized.opensprinkler_metadata}"
        )

    def sanitized(self) -> RuntimeDiagnostics:
        return RuntimeDiagnostics(
            home_assistant_logs=_sanitize_diagnostic_text(self.home_assistant_logs),
            opensprinkler_logs=_sanitize_diagnostic_text(self.opensprinkler_logs),
            opensprinkler_metadata=_sanitize_diagnostic_text(
                self.opensprinkler_metadata
            ),
        )


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
    config_path: Path, destination: Path, diagnostics: RuntimeDiagnostics
) -> None:
    sanitized = diagnostics.sanitized()
    destination.mkdir(parents=True, exist_ok=True)
    for filename in _SAFE_CONFIG_FILES + _SAFE_RUNTIME_FILES:
        source = config_path / filename
        if source.is_file():
            contents = source.read_text(encoding="utf-8", errors="replace")
            (destination / filename).write_text(
                _sanitize_diagnostic_text(contents), encoding="utf-8"
            )
    (destination / "container.log").write_text(
        sanitized.home_assistant_logs, encoding="utf-8"
    )
    (destination / "opensprinkler-mock.log").write_text(
        sanitized.opensprinkler_logs, encoding="utf-8"
    )
    (destination / "opensprinkler-metadata.json").write_text(
        sanitized.opensprinkler_metadata, encoding="utf-8"
    )


def _sanitize_diagnostic_text(contents: str) -> str:
    without_named_secrets = _SECRET_VALUE.sub(rf"\1{_REDACTED}", contents)
    return _JWT.sub(_REDACTED, without_named_secrets)
