from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import assert_never
from urllib.error import URLError

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.exploratory_runtime import (
    ArchiveValidationError,
    ExploratoryPaths,
    OnboardingResponseError,
    create_initial_user,
    prepare_files,
)

_READINESS_TIMEOUT_SECONDS = 120.0
_READINESS_POLL_SECONDS = 1.0
_DEFAULT_USERNAME = "smart-irrigation"
_DEFAULT_PASSWORD = "smart-irrigation-dev-password"


@dataclass(frozen=True, slots=True)
class HomeAssistantVersionError(Exception):
    requirements: Path

    def __str__(self) -> str:
        return f"No exact Home Assistant pin found in {self.requirements}"


class ResetRefusedError(Exception):
    def __str__(self) -> str:
        return "Exploratory reset requires FORCE=1"


class HomeAssistantReadinessError(Exception):
    def __str__(self) -> str:
        return "Home Assistant did not become ready within 120 seconds"


class Command(StrEnum):
    PREPARE = "prepare"
    SETUP = "setup"
    UP = "up"
    LOGS = "logs"
    SHELL = "shell"
    DOWN = "down"
    RESET = "reset"


def read_home_assistant_version(repository: Path) -> str:
    requirements = repository / "requirements.test.txt"
    for line in requirements.read_text(encoding="utf-8").splitlines():
        if line.startswith("homeassistant=="):
            return line.removeprefix("homeassistant==")
    raise HomeAssistantVersionError(requirements)


def run_compose(
    repository: Path, arguments: tuple[str, ...], env: Mapping[str, str]
) -> None:
    compose_env = {
        **env,
        "HOME_ASSISTANT_VERSION": read_home_assistant_version(repository),
    }
    subprocess.run(
        (
            "docker",
            "compose",
            "-f",
            "docker-compose.exploratory.yml",
            *arguments,
        ),
        cwd=repository,
        env=compose_env,
        check=True,
    )


def reset_runtime(repository: Path, env: Mapping[str, str]) -> None:
    if env.get("FORCE") != "1":
        raise ResetRefusedError
    run_compose(repository, ("down",), env)
    runtime_root = ExploratoryPaths.from_repository(repository).root
    if runtime_root.exists():
        shutil.rmtree(runtime_root)


def setup_runtime(
    repository: Path,
    env: Mapping[str, str],
    base_url: str = "http://localhost:8123",
) -> bool:
    prepare_files(repository, env)
    run_compose(repository, ("up", "-d"), env)
    deadline = time.monotonic() + _READINESS_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            return create_initial_user(
                base_url,
                env.get("EXPLORATORY_HA_USERNAME", _DEFAULT_USERNAME),
                env.get("EXPLORATORY_HA_PASSWORD", _DEFAULT_PASSWORD),
            )
        except (ConnectionResetError, URLError):
            time.sleep(_READINESS_POLL_SECONDS)
    raise HomeAssistantReadinessError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the exploratory HA runtime")
    parser.add_argument("command", choices=tuple(Command))
    command = Command(parser.parse_args(argv).command)
    repository = Path(__file__).resolve().parents[1]
    env = os.environ
    try:
        match command:
            case Command.PREPARE:
                prepare_files(repository, env)
            case Command.SETUP:
                setup_runtime(repository, env)
            case Command.UP:
                run_compose(repository, ("up", "-d"), env)
            case Command.LOGS:
                run_compose(
                    repository,
                    ("logs", "--follow", "homeassistant", "opensprinkler-mock"),
                    env,
                )
            case Command.SHELL:
                run_compose(
                    repository,
                    (
                        "exec",
                        "homeassistant",
                        "sh",
                        "-c",
                        "if [ -x /bin/bash ]; then exec /bin/bash; else exec /bin/sh; fi",
                    ),
                    env,
                )
            case Command.DOWN:
                run_compose(repository, ("down",), env)
            case Command.RESET:
                reset_runtime(repository, env)
            case unreachable:
                assert_never(unreachable)
    except (
        ArchiveValidationError,
        HomeAssistantReadinessError,
        HomeAssistantVersionError,
        OnboardingResponseError,
        ResetRefusedError,
    ) as error:
        print(error, file=sys.stderr)
        return 1
    except URLError:
        print(
            "A required network request failed; check connectivity and retry",
            file=sys.stderr,
        )
        return 1
    except subprocess.CalledProcessError:
        print(
            "Docker Compose command failed; inspect the service logs", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
