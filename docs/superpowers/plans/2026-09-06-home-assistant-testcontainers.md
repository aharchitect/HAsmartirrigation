# Home Assistant Testcontainers Runtime Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline Testcontainers-based E2E suite that boots a pinned Home Assistant Container and validates Smart Irrigation through real HTTP and WebSocket runtime surfaces.

**Architecture:** Keep the existing mocked pytest suites as the fast layer and add an explicit `tests_e2e/` layer. A session fixture creates isolated HA configuration/auth state, mounts the current integration into `/config`, starts a mapped-port Home Assistant Container, waits for readiness, and exposes authenticated API clients. Failure diagnostics preserve logs/config only when requested.

**Tech Stack:** Python, pytest, Testcontainers Python generic containers, Home Assistant Container, HTTP client, WebSocket client, Docker Engine, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-06-home-assistant-testcontainers-design.md`

## Global Constraints

- Use the Home Assistant version pinned in `requirements.test.txt`; update the dependency and container image together.
- Run entirely offline in Phase 1; weather services are disabled and no real secrets are used.
- Use a temporary HA configuration and mapped port 8123; never read or modify a developer's normal HA configuration.
- Keep E2E tests outside the default `setup.cfg` test paths and invoke them explicitly.
- Preserve existing pytest, hassfest, Ruff, Black, frontend, and release behaviour.
- Use graceful container shutdown with a timeout sufficient for Home Assistant's SQLite database.
- Do not use host networking, Docker-in-Docker, a mounted Docker socket in CI, browser automation, or physical devices.

---

### Task 1: Add E2E dependency and test entry points

**Files:**
- Create: `requirements.e2e.txt`
- Modify: `Makefile`
- Modify: `.gitignore`

**Interfaces:**
- Produces `make test-e2e` for the standard runtime suite and `make test-e2e-debug` for retained artifacts.
- Produces an isolated dependency file consumed only by E2E execution.

- [ ] **Step 1: Define the E2E dependency boundary**

Create `requirements.e2e.txt` with the existing test stack included first, followed by pinned/constrained Testcontainers and the chosen HTTP/WebSocket client packages. Do not add these dependencies to the normal runtime manifest.

- [ ] **Step 2: Add explicit Make targets**

Add `.PHONY` entries and targets with these behaviours:

```make
test-e2e:
	./.venv/bin/python -m pytest tests_e2e/ -v

test-e2e-debug:
	E2E_KEEP_ARTIFACTS=1 ./.venv/bin/python -m pytest tests_e2e/ -v -s
```

The targets must not silently skip when Docker is unavailable.

- [ ] **Step 3: Ignore generated E2E artifacts**

Add the chosen repository-local artifact directory, such as `.e2e-artifacts/`, to `.gitignore`. Do not ignore source fixtures or test files.

- [ ] **Step 4: Verify configuration-only changes**

Run:

```bash
make help
git diff --check
```

Expected: both targets appear in help and the diff has no whitespace errors.

### Task 2: Build isolated Home Assistant fixture lifecycle

**Files:**
- Create: `tests_e2e/__init__.py`
- Create: `tests_e2e/conftest.py`
- Create: `tests_e2e/fixtures/configuration.yaml`
- Create: `tests_e2e/fixtures/automations.yaml`
- Create: `tests_e2e/fixtures/scripts.yaml`

**Interfaces:**
- Produces a session-scoped `ha_runtime` fixture containing the base URL, authenticated HTTP client, WebSocket connection helper, and temporary config path.
- Produces deterministic fixture setup without manual onboarding or external network calls.

- [ ] **Step 1: Add the minimal HA configuration fixtures**

Create a minimal `configuration.yaml` that enables the core defaults required by the integration, sets deterministic latitude/longitude/elevation/time zone, disables weather-provider setup, and points HA at the normal fixture files. Keep all values test-only.

- [ ] **Step 2: Implement temporary config creation**

In `tests_e2e/conftest.py`, create a `tempfile.TemporaryDirectory` per session, copy the fixture YAML files into it, and copy the repository's `custom_components/smart_irrigation/` directory into `<temp>/custom_components/smart_irrigation/`. Ensure the tracked frontend `dist/smart-irrigation.js` is included.

- [ ] **Step 3: Implement deterministic auth/config state**

Create the minimum HA storage files required for a test user and long-lived token, or use the supported HA initialization mechanism that produces equivalent state. Keep the generated token in fixture scope only. Seed a Smart Irrigation config entry with weather disabled and a stable entry identifier.

- [ ] **Step 4: Start and stop the Testcontainers instance**

Construct a generic Testcontainers container using the exact HA image tag aligned with `requirements.test.txt`, bind the temporary config to `/config`, expose port 8123, set the graceful stop timeout, and start it before yielding the fixture. Stop/remove it in teardown regardless of test outcome.

- [ ] **Step 5: Add readiness and failure diagnostics**

Poll the mapped HTTP endpoint until Home Assistant responds as ready, using a bounded timeout. On startup/test failure, capture container logs; when `E2E_KEEP_ARTIFACTS=1`, copy the generated config into `.e2e-artifacts/`. Fail with a message that includes the mapped URL and Docker availability guidance.

- [ ] **Step 6: Verify fixture startup in isolation**

Run:

```bash
pytest tests_e2e/ -q
```

Expected: the fixture can start and tear down a real HA container; failures include container logs rather than a silent timeout.

### Task 3: Add authenticated HTTP and WebSocket client helpers

**Files:**
- Modify: `tests_e2e/conftest.py`
- Create: `tests_e2e/ha_client.py`

**Interfaces:**
- `HomeAssistantRuntimeClient.base_url: str`
- `HomeAssistantRuntimeClient.get(path: str) -> Response`
- `HomeAssistantRuntimeClient.websocket() -> ContextManager[WebSocket]`
- `HomeAssistantRuntimeClient.wait_for_state(entity_id: str) -> dict[str, object]`

- [ ] **Step 1: Write client contract tests with a local fake server**

Test URL construction, bearer authorization, WebSocket authentication, response status handling, and command correlation against a local test server. These tests must not start Home Assistant or contact Ollama/weather services.

- [ ] **Step 2: Implement the HTTP client**

Implement a small client that joins the Testcontainers mapped URL with API paths and sends `Authorization: Bearer <fixture-token>`. Keep request timeout values explicit and bounded.

- [ ] **Step 3: Implement the WebSocket command helper**

Connect to `/api/websocket`, wait for `auth_required`, send the token, verify `auth_ok`, send incrementing command IDs, and return the matching result. Close the socket during fixture teardown.

- [ ] **Step 4: Verify client tests**

Run:

```bash
pytest tests_e2e/test_ha_client.py -v
```

Expected: all client contract tests pass without Docker.

### Task 4: Add Phase 1 runtime smoke tests

**Files:**
- Create: `tests_e2e/test_runtime_smoke.py`

**Interfaces:**
- Consumes the `ha_runtime` fixture from Task 2 and client methods from Task 3.
- Produces externally observable assertions for startup, panel, services, WebSocket data, entities, and persistence.

- [ ] **Step 1: Add startup/load assertion**

Assert that the readiness endpoint succeeds and that the authenticated HA error/log surface contains no Smart Irrigation setup failure.

- [ ] **Step 2: Add panel asset assertion**

Request the registered Smart Irrigation frontend asset and assert a successful response with JavaScript content. This validates the checked-in frontend artifact and static path registration.

- [ ] **Step 3: Add service registration/call assertion**

Fetch the service registry, assert representative Smart Irrigation services are present, then call one safe offline service and assert a successful HA response.

- [ ] **Step 4: Add WebSocket baseline assertions**

Call the integration's baseline WebSocket commands for configuration and zones. Assert successful command results and the expected response shape, including an empty deterministic zone collection when no zone is seeded.

- [ ] **Step 5: Add config-entry/entity assertion**

Assert that the seeded config entry is loaded and that representative sensor/number/button/binary-sensor entities are available through `/api/states` or the entity registry. Do not assert unstable timestamps or generated presentation text.

- [ ] **Step 6: Add controlled restart persistence assertion**

Change one deterministic persisted integration value through the real API, gracefully restart the same container, wait for readiness again, and assert that the value and integration load state remain available.

- [ ] **Step 7: Verify the runtime suite**

Run:

```bash
make test-e2e
```

Expected: all Phase 1 tests pass offline using only the pinned HA image and local repository files.

### Task 5: Integrate frontend build and CI execution

**Files:**
- Create: `.github/workflows/e2e.yml`
- Modify: `Makefile`
- Modify: `README.md`
- Modify: `CONTRIBUTING.md`

**Interfaces:**
- CI invokes the same `make test-e2e` command as local development.
- Documentation explains Docker prerequisites, first-run image pull, standard execution, and debug artifacts.

- [ ] **Step 1: Make the E2E target validate the frontend artifact**

Ensure `make test-e2e` runs the frontend build from `custom_components/smart_irrigation/frontend/` before pytest, without changing the normal `make test` path.

- [ ] **Step 2: Add the dedicated Ubuntu workflow**

Create a workflow that checks out the repository, installs the project/test/E2E dependencies, runs the frontend `npm ci` and `npm run build`, and invokes `make test-e2e`. Use the existing development branch and pull-request triggers. Do not add Docker-in-Docker or socket mounts.

- [ ] **Step 3: Upload sanitized failure artifacts**

Configure the workflow to upload `.e2e-artifacts/` only on failure. Ensure the artifact contains no tokens, API keys, personal config, or host paths that expose private infrastructure.

- [ ] **Step 4: Document the developer workflow**

Document:

```bash
make test
make test-e2e
make test-e2e-debug
```

State that Docker Engine is required, the first run pulls the pinned HA image, and debug mode retains temporary configuration/logs.

- [ ] **Step 5: Verify CI-facing commands locally**

Run:

```bash
npm ci --prefix custom_components/smart_irrigation/frontend
npm run build --prefix custom_components/smart_irrigation/frontend
make test-e2e
```

Expected: the frontend bundle builds and the runtime suite passes using the same commands CI will execute.

### Task 6: Run complete verification and review the change

**Files:**
- Verify all files created or modified by Tasks 1-5.

- [ ] **Step 1: Run diagnostics on changed Python files**

Run the configured Python diagnostics/LSP check on `tests_e2e/` and any changed Python files. Resolve errors caused by the implementation; record unrelated pre-existing diagnostics.

- [ ] **Step 2: Run the existing test and quality suites**

Run:

```bash
make test
make lint
./.venv/bin/black --check custom_components/smart_irrigation/ tests_e2e/
```

Expected: existing tests and quality checks remain green.

- [ ] **Step 3: Run hassfest and package checks**

Run the repository's hassfest validation and release packaging checks without altering release metadata. Confirm E2E-only files are not included in the release component ZIP.

- [ ] **Step 4: Exercise cleanup and failure retention**

Run one successful E2E invocation and verify no container/config artifact remains. Run the debug target or a deliberately selected failing test, verify logs/config are retained, and inspect them for secrets.

- [ ] **Step 5: Review scope and repository state**

Inspect `git diff`, `git status --short`, and all changed files. Confirm the pre-existing `.gitignore` modification is not overwritten and that no unrelated refactoring or generated secret has been added.
