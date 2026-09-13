# Exploratory Docker Runtime Design

**Date:** 2026-09-12
**Status:** Approved in conversation; written-spec review pending

## Goal

Add a persistent Docker Compose Home Assistant environment for interactive and exploratory testing. It must expose the repository's local custom integrations, include HACS and the pinned OpenSprinkler integration, and coexist with the existing disposable `pytest`/Testcontainers E2E suite.

## Non-Goals

- Replace or weaken `make test-e2e`.
- Change production integration behavior.
- Run HACS fully offline.
- Automate GitHub OAuth or store a GitHub token in the repository.
- Commit exploratory Home Assistant state to Git.

## Architecture

The repository will provide a dedicated Compose file for two services:

- `homeassistant`: the Home Assistant image pinned by `requirements.test.txt`, exposed at `http://localhost:8123`, with persistent state under `.e2e-exploratory/config/`.
- `opensprinkler-mock`: the existing standard-library mock controller, built from the repository and attached to the same private Compose network under the alias `opensprinkler-mock`.

The existing Testcontainers fixture remains the authoritative automated runtime. The Compose stack is a separate manual surface and does not share its config directory, containers, network, or lifecycle.

## Local Component Mounts

The complete repository `custom_components/` directory is mounted read-only into the HA container. This keeps local code changes visible after a Home Assistant restart without copying the repository into a generated directory.

HACS and the pinned `hass-opensprinkler` integration are mounted as nested paths from `.e2e-exploratory/custom_components/`, so their files are not hidden by the repository mount. The local runtime directory is ignored by Git and may be deleted and recreated.

The OpenSprinkler mock is a separate service rather than a custom component and is never installed into Home Assistant's component tree.

## Bootstrap

`make exploratory-setup` will:

1. Create the ignored exploratory directories.
2. Write a minimal persistent Home Assistant configuration if one does not exist.
3. Download and install a pinned HACS release archive, currently HACS `2.0.5`, if HACS is not already present.
4. Download and stage the pinned OpenSprinkler source at commit `fee462ce022aba267ffcabab078652414f7d7111` if it is not already present.
5. Start the Compose stack.
6. Create the initial Home Assistant user through the local onboarding API if onboarding is still active.

The bootstrap is idempotent: existing config, HACS, external integration files, and user state are preserved. Downloads use versioned URLs and fail clearly without deleting an existing working installation.

HACS activation remains a documented manual browser step after bootstrap: add HACS from HA's integration UI and complete GitHub device OAuth. HACS requires outbound access to GitHub and its data service during normal operation.

## Commands

The Makefile will expose:

- `make exploratory-setup`: prepare and start the environment.
- `make exploratory-up`: start an already-prepared environment.
- `make exploratory-logs`: follow Home Assistant and mock logs.
- `make exploratory-shell`: open a shell in the Home Assistant container.
- `make exploratory-down`: stop and remove containers without deleting persistent state.
- `make exploratory-reset`: explicitly delete exploratory state after confirmation or an explicit force flag.

The existing `make test-e2e` and `make test-e2e-debug` commands keep their current behavior.

## Preconfiguration

The bootstrap creates the initial HA user automatically using credentials supplied through environment variables or documented development defaults. Credentials are never written into tracked files or diagnostic artifacts.

The OpenSprinkler integration is staged but not configured automatically in HA. Exploratory users may configure it through the UI against `http://opensprinkler-mock:8080`, or use the existing automated fixture for deterministic config-flow coverage.

## Diagnostics and Safety

Compose logs remain available through Docker. The exploratory state directory is ignored and is not copied into the existing sanitized E2E artifact path. No command prints passwords or GitHub tokens. Reset is separate from down so stopping the stack does not destroy exploratory state.

## Testing

Tests will cover:

- Compose file structure, service names, mounts, network alias, and health/start dependencies.
- Bootstrap URL/version selection and idempotent behavior using local HTTP fixtures or mocked downloads.
- Configuration generation without secrets in tracked files.
- Persistent state across stop/start.
- Local Smart Irrigation visibility and OpenSprinkler mock reachability from HA.
- Existing repository tests and disposable `make test-e2e` after the addition.
