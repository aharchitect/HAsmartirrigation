from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests_e2e.runtime import HomeAssistantRuntime


def test_mapped_zone_runs_for_five_minutes(
    ha_runtime: HomeAssistantRuntime,
) -> None:
    # Given: zone 7 is mapped to the real OpenSprinkler integration by the fixture.

    # When: Smart Irrigation requests an explicit five-minute run.
    result = ha_runtime.client.post_service(
        "smart_irrigation",
        "run_opensprinkler_zone",
        {"zone_id": 7, "run_seconds": 300, "queue_option": "append"},
    )

    # Then: Home Assistant accepts the service and the controller receives 300 seconds.
    assert result == []
    request = ha_runtime.opensprinkler_mock.wait_for_request("/cm")
    assert request["sid"] == 0
    assert request["en"] == 1
    assert request["t"] == 300
    assert request["qo"] == 0
