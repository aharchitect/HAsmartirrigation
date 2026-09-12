# OpenSprinkler E2E Test Design

## Goal

Verify end to end that Smart Irrigation can start a mapped OpenSprinkler station
for five minutes through Home Assistant's HACS OpenSprinkler integration.

## Scope

This slice covers one deterministic station and one Smart Irrigation zone. The
test prepares the mapping, triggers the existing Smart Irrigation control path,
and verifies the request received by a mock controller. Scheduling, queue
variants, stop commands, and detailed status are separate scenarios.

## Architecture

The E2E environment contains Home Assistant, the HACS
`vinteo/hass-opensprinkler` custom integration, and a deterministic mock
OpenSprinkler HTTP server attached to the same Docker network. Home Assistant
uses the stable hostname `opensprinkler-mock`, ensuring the controller request
comes from HA rather than the test process.

The mock records requests in memory and returns the minimum valid controller
responses required by the real HACS integration.

## Controller Contract

The HACS integration first requests:

```text
GET /ja?pw=MD5("test-password")
```

The mock returns a controller payload containing one enabled station named
`E2E Station`, MAC `001122334455`, and an idle station status.

For an appended five-minute run, the integration sends:

```text
GET /cm?pw=MD5("test-password")&sid=0&en=1&t=300&qo=0
```

The query is validated semantically, independent of parameter ordering. The
mock returns `{"result": 1}` and records the request. Subsequent `/ja`
responses may report station 0 as running so the integration can refresh state.

## Home Assistant Preparation

The runtime setup will stage Smart Irrigation and a pinned, reproducible ref of
the HACS OpenSprinkler integration, start the mock controller, create the
OpenSprinkler config entry with URL `http://opensprinkler-mock:8080`, password
`test-password`, SSL verification disabled, and name `E2E OpenSprinkler`, then
create the Smart Irrigation entry and deterministic zone. The zone is mapped to
the discovered `switch.e2e_station_enabled` entity through the supported bridge
configuration path.

The test waits for both config entries and the mapped station entity to be
loaded before triggering the run.

## Trigger and Assertions

The black-box trigger uses the existing Smart Irrigation service path, which is
the stable equivalent of the UI action:

```yaml
service: smart_irrigation.run_opensprinkler_zone
data:
  zone_id: 7
  run_seconds: 300
  queue_option: append
```

The test asserts that the HA call succeeds and that the mock receives exactly
one successful `/cm` command with the expected password hash, station index
`0`, enable flag `1`, duration `300`, and append encoding `qo=0`.

## Failure Handling

The mock returns errors for unsupported paths or invalid requests and retains
the request plus validation error for diagnostics. Mock logs are included in
the existing sanitized runtime artifact flow on failure. Startup failures
identify whether HA, the HACS integration, or the mock failed to become ready.

## Acceptance Criteria

- The test runs against a real Home Assistant container.
- The HACS OpenSprinkler integration issues the controller request.
- Home Assistant reaches the mock through the dedicated Docker network alias.
- A mapped Smart Irrigation zone starts for exactly 300 seconds.
- The mock proves receipt of the expected `/cm` command and queue encoding.
- Existing unit tests and E2E runtime smoke tests remain passing.
