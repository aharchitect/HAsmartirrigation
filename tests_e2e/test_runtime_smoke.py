from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests_e2e.runtime import HomeAssistantRuntime


def test_integration_loads_without_setup_failure(
    ha_runtime: HomeAssistantRuntime,
) -> None:
    entries = ha_runtime.client.get(
        "/api/config/config_entries/entry?domain=smart_irrigation"
    ).json()
    error_log = ha_runtime.client.get("/api/error_log").text

    assert len(entries) == 1
    assert entries[0]["state"] == "loaded"
    assert "Error setting up entry Smart Irrigation" not in error_log
    assert "Failed to set up Smart Irrigation" not in error_log


def test_panel_asset_is_javascript(ha_runtime: HomeAssistantRuntime) -> None:
    response = ha_runtime.client.get("/api/panel_custom/smart_irrigation")

    assert "javascript" in response.headers["content-type"].lower()
    assert "<html" not in response.text[:512].lower()
    assert "smart-irrigation" in response.text


def test_services_are_registered_and_safe_mutation_works(
    ha_runtime: HomeAssistantRuntime,
) -> None:
    services = ha_runtime.client.get("/api/services").json()
    domain = next(item for item in services if item["domain"] == "smart_irrigation")

    response = ha_runtime.client.post(
        "/api/services/smart_irrigation/set_all_buckets",
        {"new_bucket_value": -3.0},
    )
    zones = ha_runtime.websocket_command({"type": "smart_irrigation/zones"})

    assert "reset_all_buckets" in domain["services"]
    assert "set_all_buckets" in domain["services"]
    assert response.json() == []
    assert zones[0]["bucket"] == -3.0


def test_websocket_config_zone_and_entity_platforms_are_available(
    ha_runtime: HomeAssistantRuntime,
) -> None:
    config = ha_runtime.websocket_command({"type": "smart_irrigation/config"})
    zones = ha_runtime.websocket_command({"type": "smart_irrigation/zones"})
    states = ha_runtime.client.get("/api/states").json()
    entity_ids = {state["entity_id"] for state in states}

    assert config["use_weather_service"] is False
    assert zones[0]["name"] == "Runtime Zone"
    assert zones[0]["state"] == "disabled"
    assert "sensor.smart_irrigation_runtime_zone" in entity_ids
    assert "number.smart_irrigation_runtime_zone_multiplier" in entity_ids
    assert "button.smart_irrigation_runtime_zone_reset_bucket" in entity_ids
    assert "binary_sensor.smart_irrigation_runtime_zone_irrigation_needed" in entity_ids


def test_mutation_survives_graceful_restart(ha_runtime: HomeAssistantRuntime) -> None:
    ha_runtime.client.post("/api/smart_irrigation/zones", {"id": 7, "multiplier": 1.7})

    ha_runtime.restart()
    zones = ha_runtime.websocket_command({"type": "smart_irrigation/zones"})
    entries = ha_runtime.client.get(
        "/api/config/config_entries/entry?domain=smart_irrigation"
    ).json()

    assert zones[0]["multiplier"] == 1.7
    assert entries[0]["state"] == "loaded"
