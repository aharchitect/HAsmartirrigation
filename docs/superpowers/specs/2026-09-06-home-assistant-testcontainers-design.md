# Home Assistant Testcontainers Runtime Test Design

## Goal

Add a deterministic, Docker-backed runtime test layer that boots a real Home
Assistant Container, installs the Smart Irrigation custom component, and
asserts its public runtime behaviour. The layer targets Ubuntu developers with
Docker and runs automatically in GitHub Actions.

This layer supplements the existing fast pytest suite. It does not replace
unit, mocked Home Assistant, hassfest, lint, or frontend build checks.

## Non-goals

- Do not call real weather providers or require developer API keys.
- Do not test physical devices, Bluetooth, USB hardware, HA add-ons, or Home
  Assistant Supervisor functionality.
- Do not add full browser UI automation in the first phase.
- Do not make a long-lived developer container the automated test mechanism.

## Architecture

The E2E suite uses Python Testcontainers and its generic container API to run
one Home Assistant Core container per test session. The image is pinned to the
same Home Assistant version declared in `requirements.test.txt`; an upgrade
changes both values in one pull request.

The fixture creates a fresh temporary Home Assistant configuration directory.
It writes a minimal deterministic `configuration.yaml`, creates the required
test auth and config-entry state, and makes the repository component available
at `/config/custom_components/smart_irrigation`. The checked-in frontend
bundle must be present before the suite starts.

The Home Assistant container exposes its internal port 8123 through a mapped
host port. Tests obtain that mapped endpoint from Testcontainers rather than
assuming a fixed port. The fixture waits for a real readiness endpoint before
running assertions, with a bounded startup timeout. On startup or assertion
failure it captures container logs and preserves the generated HA config when
the debug option is enabled.

The test client calls the Home Assistant HTTP and WebSocket APIs using a
test-only, pre-seeded authentication credential. Tests never perform manual
onboarding and never use a developer's personal token.

## Test Layout

The implementation adds these files:

- `requirements.e2e.txt`: Testcontainers and the HTTP/WebSocket client
  dependencies used only by runtime tests.
- `tests_e2e/conftest.py`: temporary config construction, component install,
  Testcontainers lifecycle, readiness polling, API client setup, and failure
  diagnostics.
- `tests_e2e/fixtures/`: minimal HA configuration and deterministic runtime
  fixtures, including a no-weather integration configuration.
- `tests_e2e/test_runtime_smoke.py`: first runtime tests.
- `Makefile`: `test-e2e` and a debug target that keeps artifacts for inspection.
- `.github/workflows/e2e.yml` or a dedicated E2E job: Ubuntu Docker execution.
- `.gitignore`: generated E2E artifacts and retained failure logs.

`setup.cfg` continues to select the existing fast suite. The E2E suite runs
only through its explicit Make target and CI job, keeping normal feedback
fast.

## Phase 1 Test Matrix

All Phase 1 tests are offline and use weather services disabled.

1. Home Assistant starts with the component installed and records no Smart
   Irrigation setup failure.
2. Smart Irrigation's panel JavaScript is served from the registered static
   path.
3. Expected `smart_irrigation` services are registered and a safe service can
   be called through the HA API.
4. The integration's supported WebSocket baseline commands return valid
   configuration and zone responses.
5. A deterministic config-entry fixture loads the integration and exposes the
   expected baseline entities.
6. After a controlled Home Assistant restart, persisted integration data is
   still available and the integration loads cleanly.

The restart uses a graceful stop timeout. Home Assistant needs time to close
its SQLite database, so tests must not depend on Docker's default short stop
timeout.

## Isolation and Dependencies

Each test session receives an isolated temporary HA configuration directory
and container. Tests cannot read the developer's normal HA configuration,
credentials, database, or networked devices. The container should use normal
bridge networking and a mapped port, not host networking, to avoid port
collisions and permit CI execution.

The initial suite includes no external weather traffic. A later phase may add
a local HTTP stub container for provider-client contracts; that stub must be
started by Testcontainers and expose only deterministic fixture responses.

The Python dependencies are separated from `requirements.test.txt` so the
existing unit-test environment does not pay the Testcontainers cost. The E2E
requirements remain version-pinned or constrained consistently with the
repository's current test stack.

## Local Developer Workflow

The standard local workflow remains:

```bash
make test
make test-e2e
```

`make test-e2e` builds the frontend bundle when needed, installs the E2E
requirements, and invokes only `tests_e2e/`. A separate debug target retains
the temporary HA config and emits the container identifier and mapped URL so a
developer can inspect a failing instance. The standard target always cleans
up containers and temporary files.

Docker Engine must be available to the user running the command. Testcontainers
connects to that daemon directly. The suite must fail with an actionable
message when Docker is unavailable rather than silently skipping runtime
coverage.

## CI

Run the E2E suite in a dedicated Ubuntu GitHub Actions job after the fast test
job establishes its baseline. The job checks out the component, installs
`requirements.e2e.txt`, builds the frontend bundle, and runs `make test-e2e`.
GitHub-hosted Ubuntu runners provide Docker; the job must not use Docker in
Docker or mount a Docker socket.

Initially, run the E2E job for pull requests and pushes to the development
branches. Keep it separately reported because its image pull and HA startup
time are materially slower than pytest. Upload retained failure logs and the
sanitized generated HA configuration as workflow artifacts when the job fails.

## Acceptance Criteria

- `make test-e2e` starts a fresh pinned Home Assistant container on Ubuntu
  using Testcontainers and completes without manual interaction.
- The test fixture installs the current repository component and never reads
  a developer's existing Home Assistant config directory.
- All six Phase 1 behaviours are asserted through real Home Assistant HTTP or
  WebSocket runtime surfaces.
- The suite makes no request to an external weather provider and requires no
  real secret.
- A failing container startup or assertion produces useful logs and, in debug
  mode, inspectable generated configuration.
- CI runs the runtime suite as a separate Docker-capable job and uploads
  sanitized diagnostics on failure.
- Existing pytest, hassfest, Ruff, Black, and release packaging behaviours
  remain unchanged except for the explicit frontend build required by the E2E
  workflow.
