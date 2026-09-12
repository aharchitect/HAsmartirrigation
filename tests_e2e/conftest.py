from __future__ import annotations

import tempfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import BadZipFile, ZipFile

import httpx
import pytest
from testcontainers.core.network import Network as DockerNetwork

from tests_e2e.opensprinkler_mock import OpenSprinklerMock
from tests_e2e.runtime import (
    OPENSPRINKLER_COMMIT,
    HomeAssistantRuntime,
    RuntimeStartupError,
    preserve_debug_artifacts,
    stage_config,
    start_runtime,
)
from tests_e2e.runtime_support import runtime_parent

if TYPE_CHECKING:
    from collections.abc import Iterator

_OPENSPRINKLER_ARCHIVE_URL = (
    "https://github.com/vinteo/hass-opensprinkler/archive/"
    f"{OPENSPRINKLER_COMMIT}.zip"
)


def _extract_opensprinkler_source(destination: Path, client: httpx.Client) -> Path:
    try:
        response = client.get(_OPENSPRINKLER_ARCHIVE_URL)
        response.raise_for_status()
        with ZipFile(BytesIO(response.content)) as archive:
            archive.extractall(destination)
    except (BadZipFile, httpx.HTTPError, OSError) as error:
        raise RuntimeStartupError(
            f"Unable to fetch pinned OpenSprinkler source: {error}"
        ) from error
    return destination / f"hass-opensprinkler-{OPENSPRINKLER_COMMIT}"


@contextmanager
def _runtime_containers(
    repository: Path, config_path: Path
) -> Iterator[HomeAssistantRuntime]:
    with DockerNetwork() as network:
        opensprinkler_mock = OpenSprinklerMock()
        try:
            opensprinkler_mock.start(network)
            runtime = start_runtime(
                repository, config_path, network, opensprinkler_mock
            )
            try:
                yield runtime
            finally:
                runtime.close()
        finally:
            opensprinkler_mock.close()


@pytest.fixture(scope="session")
def ha_runtime(request: pytest.FixtureRequest) -> Iterator[HomeAssistantRuntime]:
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(
        prefix="smart-irrigation-e2e-", dir=runtime_parent(repository)
    ) as temporary:
        config_path = Path(temporary) / "config"
        source_path = Path(temporary) / "opensprinkler-source"
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            opensprinkler_source = _extract_opensprinkler_source(source_path, client)
        stage_config(repository, config_path, opensprinkler_source)
        with _runtime_containers(repository, config_path) as runtime:
            try:
                yield runtime
            finally:
                failed = request.session.testsfailed > 0
                preserve_debug_artifacts(repository, runtime, failed)
