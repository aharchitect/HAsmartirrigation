# OpenSprinkler E2E Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Docker-backed E2E test proving that Smart Irrigation starts a mapped OpenSprinkler station for 300 seconds through the real HACS OpenSprinkler Home Assistant integration.

**Architecture:** Start a deterministic stdlib-based mock OpenSprinkler HTTP container and Home Assistant on one isolated Docker network. Stage a pinned checkout of `vinteo/hass-opensprinkler` into the temporary HA configuration, create both config entries, map Smart Irrigation zone 7 to the discovered station, invoke the existing Smart Irrigation service path, and assert the mock's recorded `/cm` request.

**Tech Stack:** Python 3.14, pytest, Testcontainers Python, Docker network, Home Assistant Container, `httpx`, Home Assistant REST API, Python stdlib `http.server`.

**Spec:** `docs/superpowers/specs/2026-09-12-opensprinkler-e2e-design.md`

## Global Constraints

- Use the Home Assistant version pinned in `requirements.test.txt`.
- Use a temporary HA configuration; never read or modify a developer's normal HA configuration.
- Use an isolated user-defined Docker network; never use host networking.
- Use the HACS integration at a pinned commit, not an unpinned branch or a substitute implementation.
- Keep the mock controller protocol limited to the endpoints required by the real integration: `/ja` and `/cm`.
- Keep the five-minute assertion exact: station index `0`, enable `1`, duration `300`, append queue `qo=0`.
- Preserve the existing unit and runtime smoke tests.
- Do not add browser automation in this first slice; the authenticated HA service call is the deterministic black-box equivalent of the Smart Irrigation UI action.

---

### Task 1: Define the mock controller contract with unit tests

**Files:**
- Create: `tests_e2e/opensprinkler_mock.py`
- Create: `tests_e2e/test_opensprinkler_mock.py`

**Interfaces:**
- `OpenSprinklerMock.start(network: DockerNetwork) -> None`
- `OpenSprinklerMock.base_url: str`
- `OpenSprinklerMock.wait_until_ready() -> None`
- `OpenSprinklerMock.requests() -> list[dict[str, object]]`
- `OpenSprinklerMock.close() -> None`

- [ ] **Step 1: Write failing mock behavior tests**

Add tests that exercise the request parser/response contract without Docker:

```python
def test_run_station_records_expected_query():
    request = parse_controller_request(
        "/cm?pw=...&sid=0&en=1&t=300&qo=0"
    )
    assert request == {"path": "/cm", "sid": 0, "en": 1, "t": 300, "qo": 0}
```

Also test that `/ja` returns one station and that invalid paths/parameters
produce an explicit error response.

- [ ] **Step 2: Run the contract tests and confirm failure**

Run:

```bash
./.venv/bin/python -m pytest tests_e2e/test_opensprinkler_mock.py -v
```

Expected: FAIL because the mock parser and response helpers do not exist.

- [ ] **Step 3: Implement the protocol helpers and container**

Implement a small request handler using only the Python standard library. It
must validate `pw == md5("test-password")`, serve `/ja` with the required
controller JSON, accept `/cm` only for `sid=0`, `en=1`, `t=300`, and `qo=0`,
return `{"result": 1}`, and record accepted requests. Package the handler in a
minimal Python container with a Docker-network alias `opensprinkler-mock`.

- [ ] **Step 4: Run the mock unit tests**

Run the command from Step 2. Expected: all contract tests PASS without Docker.

### Task 2: Add HACS integration staging and shared Docker network lifecycle

**Files:**
- Modify: `tests_e2e/runtime.py`
- Modify: `tests_e2e/conftest.py`
- Modify: `tests_e2e/container_runtime.py`
- Modify: `requirements.e2e.txt`

**Interfaces:**
- `stage_config(repository: Path, config_path: Path, opensprinkler_source: Path) -> None`
- `start_runtime(repository: Path, config_path: Path, network: DockerNetwork) -> HomeAssistantRuntime`
- `OpenSprinklerMock` lifecycle is owned by the session fixture.

- [ ] **Step 1: Add a unit test for staging the pinned integration**

Test that staging copies `custom_components/opensprinkler/manifest.json` and
the integration modules into the temporary HA configuration, and rejects a
source without that manifest.

- [ ] **Step 2: Run the staging test and confirm failure**

Run:

```bash
./.venv/bin/python -m pytest tests_e2e/test_runtime_support.py -v
```

Expected: FAIL until staging accepts and copies the external integration.

- [ ] **Step 3: Pin and stage `vinteo/hass-opensprinkler`**

Add one explicit commit SHA constant for the researched integration revision.
Fetch the repository into a temporary source directory during E2E setup and
copy only its `custom_components/opensprinkler/` directory into the HA config.
Fail clearly if fetch, ref checkout, or manifest validation fails.

- [ ] **Step 4: Create and share the Docker network**

Create one user-defined Testcontainers network per E2E session. Start the mock
with alias `opensprinkler-mock`, then start HA on that same network. Extend
cleanup so both containers and the network are removed on success and failure.

- [ ] **Step 5: Verify the lifecycle unit tests**

Run the runtime support tests. Expected: all non-Docker staging and cleanup
tests PASS; Docker-dependent tests remain explicitly marked by their existing
runtime fixture.

### Task 3: Prepare HA config entries, zone mapping, and the failing E2E test

**Files:**
- Modify: `tests_e2e/runtime.py`
- Modify: `tests_e2e/conftest.py`
- Modify: `tests_e2e/ha_client.py`
- Create: `tests_e2e/test_opensprinkler_runtime.py`

**Interfaces:**
- `HomeAssistantRuntime.opensprinkler_mock: OpenSprinklerMock`
- `HomeAssistantRuntimeClient.post_service(domain: str, service: str, payload: JsonObject) -> JsonValue`
- `OpenSprinklerMock.requests() -> list[dict[str, object]]`

- [ ] **Step 1: Write the failing E2E scenario**

Create one test with this acceptance shape:

```python
def test_mapped_zone_runs_for_five_minutes(ha_runtime):
    result = ha_runtime.client.post_service(
        "smart_irrigation",
        "run_opensprinkler_zone",
        {"zone_id": 7, "run_seconds": 300, "queue_option": "append"},
    )
    assert result == []
    request = ha_runtime.opensprinkler_mock.wait_for_request("/cm")
    assert request["sid"] == 0
    assert request["en"] == 1
    assert request["t"] == 300
    assert request["qo"] == 0
```

- [ ] **Step 2: Run the new E2E test and confirm failure**

Run:

```bash
make test-e2e -- tests_e2e/test_opensprinkler_runtime.py -v
```

Expected: FAIL because the runtime does not yet stage/configure the HACS
integration or expose the mock journal.

- [ ] **Step 3: Configure the real HACS OpenSprinkler entry**

After HA onboarding and before Smart Irrigation setup, create the
`opensprinkler` config entry with URL `http://opensprinkler-mock:8080`, password
`test-password`, `verify_ssl: false`, and name `E2E OpenSprinkler`. Wait for the
real integration to create `switch.e2e_station_enabled` from the mock's `/ja`
payload.

- [ ] **Step 4: Configure Smart Irrigation and mapping**

Create the deterministic Smart Irrigation zone with ID `7`, positive duration,
and name `Runtime OpenSprinkler Zone`. Configure the bridge mapping from zone
`7` to `switch.e2e_station_enabled`, enable the bridge, and wait until the
Smart Irrigation config entry is loaded.

- [ ] **Step 5: Implement the authenticated service helper and journal wait**

Add `post_service` to the existing HA client and a bounded
`wait_for_request(path)` method to the mock wrapper. Preserve HA response status
checking and include the latest mock request in timeout diagnostics.

- [ ] **Step 6: Run the focused E2E test**

Run the command from Step 2 with Docker available. Expected: the real HACS
integration performs `/ja`, Smart Irrigation invokes `opensprinkler.run_station`,
and the mock records one valid `/cm` request.

### Task 4: Add failure diagnostics and complete verification

**Files:**
- Modify: `tests_e2e/runtime.py`
- Modify: `tests_e2e/opensprinkler_mock.py`
- Modify: `tests_e2e/test_opensprinkler_runtime.py`
- Modify: `README.md`

**Interfaces:**
- Existing sanitized artifact preservation includes HA and mock logs.

- [ ] **Step 1: Add controller failure-path tests**

Test that an unsupported path, wrong password, and wrong station parameters
return non-success responses without being recorded as accepted controller
commands.

- [ ] **Step 2: Include mock diagnostics in runtime failures**

When HA startup or the E2E test fails, print/copy the mock container logs and
the recorded request journal through the existing sanitized artifact mechanism.
Do not include auth tokens or unrelated host configuration.

- [ ] **Step 3: Run targeted verification**

Run:

```bash
./.venv/bin/python -m pytest tests_e2e/test_opensprinkler_mock.py -v
./.venv/bin/python -m pytest tests_e2e/test_ha_client.py tests_e2e/test_runtime_support.py -v
make test-e2e
```

Expected: mock/client tests pass without external devices; the E2E suite passes
with Docker and local network access.

- [ ] **Step 4: Run repository verification**

Run:

```bash
make test
make lint
./.venv/bin/black --check tests_e2e/
git diff --check
```

Expected: existing unit tests, lint, formatting, and whitespace checks pass.

- [ ] **Step 5: Review changed files and scope**

Inspect all changed files and confirm the implementation is confined to the
mock, E2E runtime, HACS staging, and documentation required for this scenario.
