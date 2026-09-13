# Exploratory Docker Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent Docker Compose Home Assistant environment with live local custom integrations, pinned HACS/OpenSprinkler files, automated HA user bootstrap, and an included OpenSprinkler mock, without changing the disposable pytest E2E runtime.

**Architecture:** A Python standard-library bootstrap prepares ignored `.e2e-exploratory/` state, downloads versioned HACS and OpenSprinkler archives, creates a minimal HA config and live symlink farm, starts Compose, and creates the first HA user through the local onboarding API. Compose runs Home Assistant and the existing mock on one private network; the repository's complete `custom_components/` tree is bind-mounted read-only, while HACS and OpenSprinkler are stored in the persistent config tree.

**Tech Stack:** Docker Compose, Home Assistant Container, Python 3.14 standard library, pytest, PyYAML for test inspection, Make.

**Spec:** `docs/superpowers/specs/2026-09-12-exploratory-docker-runtime-design.md`

## Global Constraints

- Keep `make test-e2e` and `make test-e2e-debug` disposable and unchanged in behavior.
- Use persistent state only under ignored `.e2e-exploratory/`.
- Mount the complete repository `custom_components/` tree read-only for live local changes.
- Pin HACS to release `2.0.5` and OpenSprinkler to commit `fee462ce022aba267ffcabab078652414f7d7111`.
- Do not automate or store GitHub OAuth credentials; HACS activation remains a manual browser step.
- Do not print or commit HA passwords, GitHub tokens, access tokens, or runtime state.
- `exploratory-down` preserves state; `exploratory-reset` is the only destructive command and requires explicit confirmation or `FORCE=1`.
- Do not modify production integration code or add runtime dependencies solely for this environment.

---

## File Map

- Create `scripts/exploratory_runtime.py`: typed paths, pinned archive downloads, safe extraction, config generation, local-component symlinks, onboarding HTTP client, and Compose command helpers.
- Create `docker-compose.exploratory.yml`: persistent Home Assistant and OpenSprinkler mock services, mounts, health checks, network, and local mock command.
- Create `tests/test_exploratory_runtime.py`: unit tests for bootstrap paths, archive handling, idempotency, config generation, and onboarding request behavior.
- Modify `Makefile`: exploratory setup/up/logs/shell/down/reset targets while preserving test targets.
- Modify `.gitignore`: ignore `.e2e-exploratory/` and any local Compose environment files.
- Modify `README.md`: document exploratory setup, login environment variables, HACS OAuth step, and lifecycle commands.

### Task 1: Bootstrap Contracts and Preparation

**Files:**
- Create: `scripts/exploratory_runtime.py`
- Test: `tests/test_exploratory_runtime.py`

**Interfaces:**
- Produce `ExploratoryPaths.from_repository(repository: Path) -> ExploratoryPaths` with `root`, `config`, `custom_components`, `hacs`, and `opensprinkler` paths.
- Produce `prepare_files(repository: Path, env: Mapping[str, str]) -> ExploratoryPaths`; it creates missing directories/configuration, downloads only missing pinned archives, stages HACS/OpenSprinkler, and creates symlinks for every local component.
- Produce `create_initial_user(base_url: str, username: str, password: str) -> bool`; it returns `False` when onboarding is already complete and otherwise creates the user and exchanges the auth code without persisting the returned token.

- [x] **Step 1: Write failing tests for archive pins and runtime paths**

Test `ExploratoryPaths.from_repository()` against a temporary repository and assert exact paths under `.e2e-exploratory/`. Test constants produce `https://github.com/hacs/integration/releases/download/2.0.5/hacs.zip` and the pinned OpenSprinkler commit archive URL.

- [x] **Step 2: Run the focused tests and verify the expected failure**

Run: `./.venv/bin/python -m pytest tests/test_exploratory_runtime.py -k 'paths or archive' -v`

Expected: collection/import failure because `scripts.exploratory_runtime` does not yet exist.

- [x] **Step 3: Write failing tests for safe extraction, config, symlinks, and idempotency**

Mock archive downloads with in-memory ZIP responses. Assert archive members cannot escape the destination, `configuration.yaml` contains no credential values, all local component directories receive links targeting `/config/local_custom_components/<name>`, and a second `prepare_files()` call does not redownload or overwrite existing staged components.

- [x] **Step 4: Implement the minimal typed bootstrap preparation**

Use `urllib.request`, `zipfile`, `pathlib`, and `shutil` only. Validate the expected archive root and manifest before staging. Generate configuration with `homeassistant`, `http`, `api`, `auth`, `config`, `frontend`, `onboarding`, and the existing automation includes. Preserve existing files and use atomic temporary downloads for new archives.

- [x] **Step 5: Run the preparation tests and quality checks**

Run: `./.venv/bin/python -m pytest tests/test_exploratory_runtime.py -k 'paths or archive or prepare' -v`

Expected: all preparation tests pass. Run `./.venv/bin/ruff check scripts/exploratory_runtime.py tests/test_exploratory_runtime.py` and `./.venv/bin/black --check scripts/exploratory_runtime.py tests/test_exploratory_runtime.py`.

Task 1 checkpoint: complete. `create_initial_user()` remains an explicit Task 3 seam, as documented in the Task 1 report; the filesystem/archive preparation itself is complete.

### Task 2: Compose Runtime Contract

**Files:**
- Create: `docker-compose.exploratory.yml`
- Modify: `tests/test_exploratory_runtime.py`

**Interfaces:**
- Compose service `homeassistant` uses the HA version from `requirements.test.txt`, publishes `8123:8123`, mounts `.e2e-exploratory/config:/config`, mounts `./custom_components:/config/local_custom_components:ro`, and joins the private network.
- Compose service `opensprinkler-mock` uses `python:3.14-alpine`, mounts `tests_e2e/opensprinkler_mock.py` read-only, runs `python -u /app/opensprinkler_mock.py --serve`, exposes `8080`, and has network alias `opensprinkler-mock`.
- Compose health checks must make HA wait for the mock's readiness and must not require host networking.

- [x] **Step 1: Add failing Compose contract tests**

Load the Compose YAML and assert both service names, the HA port, persistent config mount, read-only local component mount, mock command, private network, alias, and dependency/health declarations.

- [x] **Step 2: Run the contract test to verify failure**

Run: `./.venv/bin/python -m pytest tests/test_exploratory_runtime.py -k compose -v`

Expected: `FileNotFoundError` for `docker-compose.exploratory.yml`.

- [x] **Step 3: Write the minimal Compose file**

Reference the pinned HA version through the generated Compose environment variable `HOME_ASSISTANT_VERSION`, mount the persistent and local trees, and attach both services to one named network. Keep HACS/OpenSprinkler files in the config tree so the local mount cannot hide them.

- [x] **Step 4: Run Compose validation and contract tests**

Run: `docker compose -f docker-compose.exploratory.yml config`

Expected: exit code 0 with resolved services and mounts. Then run the focused Compose tests and confirm they pass.

Task 2 checkpoint: complete. Compose validation requires `HOME_ASSISTANT_VERSION` until Task 3's bootstrap wires that variable from `requirements.test.txt`.

### Task 3: Onboarding, Make Targets, and Documentation

**Files:**
- Modify: `scripts/exploratory_runtime.py`
- Modify: `Makefile`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `tests/test_exploratory_runtime.py`

**Interfaces:**
- `make exploratory-setup` runs preparation, starts Compose detached, waits for HA `/api/onboarding`, and creates the initial user from `EXPLORATORY_HA_USERNAME` and `EXPLORATORY_HA_PASSWORD` or documented development defaults.
- `make exploratory-up` starts the prepared stack without deleting state.
- `make exploratory-logs` follows both services.
- `make exploratory-shell` opens `/bin/bash` or the image's available shell in Home Assistant.
- `make exploratory-down` stops/removes containers but not `.e2e-exploratory/`.
- `make exploratory-reset` refuses without `FORCE=1` and then removes only `.e2e-exploratory/`.

- [x] **Step 1: Add failing onboarding client tests**

Use a local HTTP fixture to assert the exact onboarding user request, auth-code token exchange, bearer-free bootstrap behavior, and the no-op response when `/api/onboarding` is already complete. Assert passwords and returned access tokens are absent from stdout and tracked configuration.

- [x] **Step 2: Implement onboarding and Compose command helpers**

Use `urllib.request` for local API calls and `subprocess.run` for Compose. Poll only for service readiness with a bounded timeout; do not add controller-run retries or duration sleeps. Return actionable errors and never include credential values in them.

- [x] **Step 3: Add Make targets and ignore rules**

Wire the targets to the script and Compose file. Add `/.e2e-exploratory/` and local environment overrides to `.gitignore`. Keep `test-e2e` target lines untouched.

- [x] **Step 4: Document the exploratory workflow**

Add commands, default/override environment variables, first login, HACS manual OAuth activation, OpenSprinkler mock URL, live-mount restart requirement, persistence behavior, and reset safety to the README.

- [x] **Step 5: Run focused tests and static checks**

Run: `./.venv/bin/python -m pytest tests/test_exploratory_runtime.py -v`

Expected: all bootstrap/Compose contract tests pass. Run Ruff and Black on all changed Python files, plus `docker compose -f docker-compose.exploratory.yml config`.

Task 3 checkpoint: complete. The setup command supplies `HOME_ASSISTANT_VERSION` from `requirements.test.txt`; HACS activation remains the documented manual GitHub OAuth step.

### Task 4: Live Exploratory Runtime Verification

**Files:**
- Modify: `tests/test_exploratory_runtime.py` only if a discovered contract gap needs a regression test.

**Interfaces:**
- The live stack is accessed at `http://localhost:8123` with the configured bootstrap user.
- Home Assistant reaches `http://opensprinkler-mock:8080` over the Compose network.
- Local `smart_irrigation` is loaded from the repository mount, while HACS files persist under `.e2e-exploratory/config/custom_components/hacs`.

- [x] **Step 1: Run exploratory setup against Docker**

Run: `EXPLORATORY_HA_PASSWORD='<local-only password>' make exploratory-setup`

Expected: both containers become healthy, the initial HA user is created, and no credential is printed.

- [ ] **Step 2: Verify interactive surfaces** *(manual prerequisite: browser login, HACS GitHub OAuth, and OpenSprinkler UI configuration were not performed in this session)*

Open `http://localhost:8123`, log in, add HACS through the HA integration UI, complete GitHub device OAuth, and confirm the Smart Irrigation panel is served from the local mount. Configure OpenSprinkler against `http://opensprinkler-mock:8080` and confirm its station is discovered.

- [x] **Step 3: Verify persistence and live local code**

Run `make exploratory-down`, then `make exploratory-up`; confirm the HA user, HACS files, and configured entries remain. Make a harmless local component change, restart HA, and confirm the container loads the mounted source.

- [x] **Step 4: Verify cleanup and regression boundaries**

Run `make exploratory-down` and confirm `.e2e-exploratory/` remains. Run `make test-e2e`, `make test`, `make lint`, and `./.venv/bin/python -m black --check .`.

- [x] **Step 5: Record final verification**

Update the task report/ledger with exact command results, note any Docker or OAuth prerequisites, and confirm `GIT_MASTER=1 git status --short` contains only intended source/docs changes and no exploratory state.

Task 4 checkpoint: complete. Live Compose verification passed; browser-only HACS OAuth and browser OpenSprinkler configuration remain explicit manual prerequisites.
