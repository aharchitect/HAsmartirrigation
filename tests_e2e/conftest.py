from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests_e2e.runtime import preserve_debug_artifacts, stage_config, start_runtime
from tests_e2e.runtime_support import runtime_parent

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests_e2e.runtime import HomeAssistantRuntime


@pytest.fixture(scope="session")
def ha_runtime(request: pytest.FixtureRequest) -> Iterator[HomeAssistantRuntime]:
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(
        prefix="smart-irrigation-e2e-", dir=runtime_parent(repository)
    ) as temporary:
        config_path = Path(temporary) / "config"
        stage_config(repository, config_path)
        runtime = start_runtime(repository, config_path)
        try:
            yield runtime
        finally:
            failed = request.session.testsfailed > 0
            if failed:
                print(runtime.logs())
            try:
                preserve_debug_artifacts(repository, runtime, failed)
            finally:
                runtime.close()
