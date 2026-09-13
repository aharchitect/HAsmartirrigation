from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from subprocess import CompletedProcess

import pytest

import scripts.exploratory_commands as exploratory_commands
from tests.exploratory_runtime_support import onboarding_server

REPOSITORY = Path(__file__).parents[1]


def test_run_compose_passes_version_from_test_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    (tmp_path / "requirements.test.txt").write_text(
        "homeassistant==2026.9.1\n", encoding="utf-8"
    )
    calls: list[tuple[Sequence[str], Path, Mapping[str, str]]] = []

    def record_run(
        command: Sequence[str], *, cwd: Path, env: Mapping[str, str], check: bool
    ) -> CompletedProcess[str]:
        assert check is True
        calls.append((command, cwd, env))
        return CompletedProcess(command, 0)

    monkeypatch.setattr(exploratory_commands.subprocess, "run", record_run)

    # When
    exploratory_commands.run_compose(tmp_path, ("up", "-d"), {})

    # Then
    assert exploratory_commands.read_home_assistant_version(tmp_path) == "2026.9.1"
    assert calls[0][0] == (
        "docker",
        "compose",
        "-f",
        "docker-compose.exploratory.yml",
        "up",
        "-d",
    )
    assert calls[0][1] == tmp_path
    assert calls[0][2]["HOME_ASSISTANT_VERSION"] == "2026.9.1"


def test_reset_runtime_requires_force_and_removes_only_exploratory_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    runtime = tmp_path / ".e2e-exploratory"
    runtime.mkdir()
    sibling = tmp_path / "keep-me"
    sibling.write_text("preserved", encoding="utf-8")
    compose_arguments: list[tuple[str, ...]] = []

    def record_compose(
        repository: Path, arguments: tuple[str, ...], env: Mapping[str, str]
    ) -> None:
        assert repository == tmp_path
        assert env == {"FORCE": "1"}
        compose_arguments.append(arguments)

    monkeypatch.setattr(exploratory_commands, "run_compose", record_compose)

    # When / Then
    with pytest.raises(exploratory_commands.ResetRefusedError):
        exploratory_commands.reset_runtime(tmp_path, {})
    exploratory_commands.reset_runtime(tmp_path, {"FORCE": "1"})
    assert compose_arguments == [("down",)]
    assert not runtime.exists()
    assert sibling.read_text(encoding="utf-8") == "preserved"


def test_reset_runtime_propagates_state_deletion_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    runtime = tmp_path / ".e2e-exploratory"
    runtime.mkdir()
    events: list[str] = []

    def record_compose(
        repository: Path, arguments: tuple[str, ...], env: Mapping[str, str]
    ) -> None:
        assert repository == tmp_path
        assert arguments == ("down",)
        assert env == {"FORCE": "1"}
        events.append("down")

    def fail_remove(path: Path, *, ignore_errors: bool = False) -> None:
        events.append("delete")
        if ignore_errors:
            return
        raise PermissionError(path)

    monkeypatch.setattr(exploratory_commands, "run_compose", record_compose)
    monkeypatch.setattr(exploratory_commands.shutil, "rmtree", fail_remove)

    # When / Then
    with pytest.raises(PermissionError):
        exploratory_commands.reset_runtime(tmp_path, {"FORCE": "1"})
    assert events == ["down", "delete"]


def test_setup_runtime_prepares_starts_and_onboards_with_environment_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, socket_enabled: None
) -> None:
    # Given
    events: list[str] = []
    username = "configured-user"
    password = "configured-password"
    env = {
        "EXPLORATORY_HA_USERNAME": username,
        "EXPLORATORY_HA_PASSWORD": password,
    }
    monkeypatch.setattr(
        exploratory_commands,
        "prepare_files",
        lambda repository, environment: events.append("prepare"),
    )
    monkeypatch.setattr(
        exploratory_commands,
        "run_compose",
        lambda repository, arguments, environment: events.append("compose-up"),
    )

    # When
    with onboarding_server(user_done=False) as (base_url, requests):
        created = exploratory_commands.setup_runtime(tmp_path, env, base_url=base_url)

    # Then
    assert created is True
    assert events == ["prepare", "compose-up"]
    assert json.loads(requests[1].body)["username"] == username
    assert json.loads(requests[1].body)["password"] == password


@pytest.mark.parametrize(
    ("target", "command"),
    [
        ("exploratory-setup", "setup"),
        ("exploratory-up", "up"),
        ("exploratory-logs", "logs"),
        ("exploratory-shell", "shell"),
        ("exploratory-down", "down"),
        ("exploratory-reset", "reset"),
    ],
)
def test_make_exploratory_target_routes_to_runtime_command(
    target: str, command: str
) -> None:
    # Given / When
    result = subprocess.run(
        ("make", "--no-print-directory", "-n", target),
        cwd=REPOSITORY,
        env={**os.environ, "FORCE": "1"},
        check=False,
        capture_output=True,
        text=True,
    )

    # Then
    assert result.returncode == 0
    assert (
        f"./.venv/bin/python scripts/exploratory_commands.py {command}" in result.stdout
    )
