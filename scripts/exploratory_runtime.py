from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile, ZipInfo

HACS_VERSION: Final = "2.0.5"
OPENSPRINKLER_COMMIT: Final = "fee462ce022aba267ffcabab078652414f7d7111"
HACS_ARCHIVE_URL: Final = (
    f"https://github.com/hacs/integration/releases/download/{HACS_VERSION}/hacs.zip"
)
OPENSPRINKLER_ARCHIVE_URL: Final = (
    "https://github.com/vinteo/hass-opensprinkler/archive/"
    f"{OPENSPRINKLER_COMMIT}.zip"
)
_OPENSPRINKLER_ARCHIVE_ROOT: Final = f"hass-opensprinkler-{OPENSPRINKLER_COMMIT}"
_DOWNLOAD_TIMEOUT_SECONDS: Final = 60.0
_ONBOARDING_TIMEOUT_SECONDS: Final = 5.0
_SYMLINK_FILE_TYPE: Final = 0o120000
_FILE_TYPE_MASK: Final = 0o170000
_CONFIGURATION: Final = """homeassistant:
  name: Smart Irrigation Exploratory

http:
api:
auth:
config:
frontend:
onboarding:

automation: !include automations.yaml
script: !include scripts.yaml
"""


@dataclass(frozen=True, slots=True)
class ExploratoryPaths:
    root: Path
    config: Path
    custom_components: Path
    hacs: Path
    opensprinkler: Path

    @classmethod
    def from_repository(cls, repository: Path) -> ExploratoryPaths:
        root = repository / ".e2e-exploratory"
        config = root / "config"
        custom_components = config / "custom_components"
        return cls(
            root=root,
            config=config,
            custom_components=custom_components,
            hacs=custom_components / "hacs",
            opensprinkler=custom_components / "opensprinkler",
        )


@dataclass(frozen=True, slots=True)
class ArchiveValidationError(Exception):
    archive: str
    detail: str

    def __str__(self) -> str:
        return f"Invalid {self.archive} archive: {self.detail}"


@dataclass(frozen=True, slots=True)
class OnboardingResponseError(Exception):
    operation: str

    def __str__(self) -> str:
        return f"Home Assistant returned an invalid {self.operation} response"


def prepare_files(repository: Path, env: Mapping[str, str]) -> ExploratoryPaths:
    paths = ExploratoryPaths.from_repository(repository)
    paths.custom_components.mkdir(parents=True, exist_ok=True)
    _write_missing_configuration(paths.config)
    _stage_hacs(paths)
    _stage_opensprinkler(paths)
    _link_local_components(repository, paths)
    return paths


def create_initial_user(base_url: str, username: str, password: str) -> bool:
    client_id = f"{base_url.rstrip('/')}/"
    onboarding = _request_json(Request(f"{base_url}/api/onboarding"), "onboarding")
    if not isinstance(onboarding, list):
        raise OnboardingResponseError("onboarding")
    user_pending = any(
        step.get("step") == "user" and step.get("done") is False
        for step in onboarding
        if isinstance(step, dict)
    )
    if not user_pending:
        return False

    user_payload = json.dumps(
        {
            "client_id": client_id,
            "language": "en",
            "name": username,
            "password": password,
            "username": username,
        }
    ).encode()
    user_request = Request(
        f"{base_url}/api/onboarding/users",
        data=user_payload,
        headers={"Content-Type": "application/json"},
    )
    user_response = _request_json(user_request, "user creation")
    if not isinstance(user_response, dict) or not isinstance(
        auth_code := user_response.get("auth_code"), str
    ):
        raise OnboardingResponseError("user creation")

    token_request = Request(
        f"{base_url}/auth/token",
        data=urlencode(
            {
                "client_id": client_id,
                "code": auth_code,
                "grant_type": "authorization_code",
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    _request_json(token_request, "token exchange")
    return True


def _request_json(request: Request, operation: str):
    try:
        with urlopen(request, timeout=_ONBOARDING_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except json.JSONDecodeError as error:
        raise OnboardingResponseError(operation) from error


def _write_missing_configuration(config: Path) -> None:
    configuration = config / "configuration.yaml"
    if not configuration.exists():
        configuration.write_text(_CONFIGURATION, encoding="utf-8")
    for included_file in ("automations.yaml", "scripts.yaml"):
        (config / included_file).touch(exist_ok=True)


def _stage_hacs(paths: ExploratoryPaths) -> None:
    if paths.hacs.exists():
        return
    with tempfile.TemporaryDirectory(dir=paths.root, prefix="hacs-") as temporary:
        extracted = _download_and_extract(
            HACS_ARCHIVE_URL, Path(temporary), archive_name="HACS"
        )
        _require_manifest(extracted / "manifest.json", "HACS")
        shutil.move(extracted, paths.hacs)


def _stage_opensprinkler(paths: ExploratoryPaths) -> None:
    if paths.opensprinkler.exists():
        return
    with tempfile.TemporaryDirectory(
        dir=paths.root, prefix="opensprinkler-"
    ) as temporary:
        extracted = _download_and_extract(
            OPENSPRINKLER_ARCHIVE_URL,
            Path(temporary),
            archive_name="OpenSprinkler",
        )
        source = (
            extracted
            / _OPENSPRINKLER_ARCHIVE_ROOT
            / "custom_components"
            / "opensprinkler"
        )
        _require_manifest(source / "manifest.json", "OpenSprinkler")
        shutil.move(source, paths.opensprinkler)


def _download_and_extract(url: str, temporary: Path, archive_name: str) -> Path:
    archive_path = temporary / "archive.zip"
    extracted = temporary / "extracted"
    extracted.mkdir()
    with (
        urlopen(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response,
        archive_path.open("wb") as archive_file,
    ):
        shutil.copyfileobj(response, archive_file)
    with ZipFile(archive_path) as archive:
        _extract_safely(archive, extracted, archive_name)
    return extracted


def _extract_safely(archive: ZipFile, destination: Path, archive_name: str) -> None:
    members = archive.infolist()
    for member in members:
        _validate_archive_member(member, archive_name)
    for member in members:
        relative = PurePosixPath(member.filename)
        target = destination.joinpath(*relative.parts)
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)


def _validate_archive_member(member: ZipInfo, archive_name: str) -> None:
    relative = PurePosixPath(member.filename)
    file_type = (member.external_attr >> 16) & _FILE_TYPE_MASK
    if (
        not member.filename
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in member.filename
        or file_type == _SYMLINK_FILE_TYPE
    ):
        raise ArchiveValidationError(archive_name, member.filename)


def _require_manifest(manifest: Path, archive_name: str) -> None:
    if not manifest.is_file():
        raise ArchiveValidationError(archive_name, f"missing {manifest.name}")


def _link_local_components(repository: Path, paths: ExploratoryPaths) -> None:
    local_components = repository / "custom_components"
    for component in sorted(local_components.iterdir()):
        if not component.is_dir():
            continue
        link = paths.custom_components / component.name
        if link.exists() or link.is_symlink():
            continue
        link.symlink_to(Path("/config/local_custom_components") / component.name)
