from __future__ import annotations

from typing import Final

from docker.errors import DockerException, NotFound
from testcontainers.core.container import DockerContainer

STOP_TIMEOUT_SECONDS: Final = 60


def container_logs(container: DockerContainer) -> str:
    try:
        logs = container.get_logs()
    except DockerException:
        return ""
    if isinstance(logs, tuple):
        return "\n".join(part.decode(errors="replace") for part in logs)
    if isinstance(logs, bytes):
        return logs.decode(errors="replace")
    return str(logs)


def remove_container(container: DockerContainer) -> None:
    wrapped = container.get_wrapped_container()
    if wrapped is None:
        container.get_docker_client().client.close()
        return
    try:
        wrapped.exec_run(["chmod", "-R", "a+rwX", "/config"])
        wrapped.stop(timeout=STOP_TIMEOUT_SECONDS)
        wrapped.remove(v=True)
    except NotFound:
        return
    finally:
        container.get_docker_client().client.close()
