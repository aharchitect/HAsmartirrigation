"""Unit tests for the OpenSprinkler bridge."""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

COMPONENT_DIR = Path(__file__).parents[1] / "custom_components" / "smart_irrigation"
PACKAGE_NAME = "_smart_irrigation_opensprinkler_unit"

package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(COMPONENT_DIR)]
sys.modules[PACKAGE_NAME] = package

const_spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.const", COMPONENT_DIR / "const.py"
)
const = importlib.util.module_from_spec(const_spec)
sys.modules[f"{PACKAGE_NAME}.const"] = const
const_spec.loader.exec_module(const)

opensprinkler_spec = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.opensprinkler", COMPONENT_DIR / "opensprinkler.py"
)
opensprinkler = importlib.util.module_from_spec(opensprinkler_spec)
sys.modules[f"{PACKAGE_NAME}.opensprinkler"] = opensprinkler
opensprinkler_spec.loader.exec_module(opensprinkler)
OpenSprinklerBridge = opensprinkler.OpenSprinklerBridge


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations():
    """Keep these unit tests out of the Home Assistant integration fixture stack."""
    yield


@pytest.fixture
def hass():
    """Return a minimal Home Assistant mock."""
    hass = Mock()
    hass.services = Mock()
    hass.services.has_service = Mock(return_value=True)
    hass.services.async_call = AsyncMock()
    hass.bus = Mock()
    hass.bus.fire = Mock()
    hass.config_entries = Mock()
    hass.config_entries.async_entries = Mock(return_value=[])
    return hass


@pytest.fixture
def store():
    """Return a minimal Smart Irrigation store mock."""
    store = Mock()
    store.async_get_config = AsyncMock(
        return_value={
            const.CONF_OPENSPRINKLER_INTEGRATION: True,
            const.CONF_OPENSPRINKLER_STATION_MAP: {"1": "switch.front_lawn"},
            const.CONF_OPENSPRINKLER_QUEUE_OPTION: "append",
        }
    )
    store.async_update_config = AsyncMock()
    store.get_zone = Mock(
        return_value={
            const.ZONE_ID: 1,
            const.ZONE_NAME: "Front Lawn",
            const.ZONE_DURATION: 600,
        }
    )
    store.async_get_zones = AsyncMock(
        return_value=[
            {
                const.ZONE_ID: 1,
                const.ZONE_NAME: "Front Lawn",
                const.ZONE_DURATION: 600,
            },
            {
                const.ZONE_ID: 2,
                const.ZONE_NAME: "Beds",
                const.ZONE_DURATION: 0,
            },
        ]
    )
    return store


@pytest.fixture
def bridge(hass, store):
    """Return an initialized bridge subject."""
    coordinator = Mock()
    coordinator.store = store
    return OpenSprinklerBridge(hass, coordinator)


def test_initialize_loads_enabled_configuration(bridge):
    """Test bridge configuration is loaded from Smart Irrigation config."""
    asyncio.run(bridge.async_initialize())

    status = asyncio.run(bridge.async_get_status())

    assert status["enabled"] is True
    assert status["run_station_service_available"] is True
    assert status["queue_option"] == "append"
    assert status["mapped_zones"] == {"1": "switch.front_lawn"}
    assert status["available_stations"] == {}


def test_initialize_enables_bridge_for_configured_opensprinkler(hass, bridge, store):
    """A configured OpenSprinkler integration enables the bridge at startup."""
    store.async_get_config.return_value = {
        const.CONF_OPENSPRINKLER_INTEGRATION: False,
        const.CONF_OPENSPRINKLER_STATION_MAP: {},
    }
    hass.config_entries.async_entries.return_value = [Mock()]

    asyncio.run(bridge.async_initialize())

    store.async_update_config.assert_awaited_once_with(
        {const.CONF_OPENSPRINKLER_INTEGRATION: True}
    )
    assert bridge.is_enabled() is True


def test_status_discovers_available_opensprinkler_stations(hass, bridge, monkeypatch):
    """Test status returns OpenSprinkler station entities for UI selection."""
    opensprinkler_device = Mock(
        id="device_opensprinkler",
        name="OpenSprinkler",
        name_by_user=None,
        manufacturer="OpenSprinkler",
        model="OSPi",
        identifiers={("opensprinkler", "controller-1")},
    )
    kitchen_device = Mock(
        id="device_kitchen",
        name="Kitchen",
        name_by_user=None,
        manufacturer=None,
        model=None,
        identifiers=set(),
    )
    device_registry = Mock(
        devices={
            opensprinkler_device.id: opensprinkler_device,
            kitchen_device.id: kitchen_device,
        }
    )

    entity_entries = [
        Mock(
            entity_id="switch.main_valve_station_enabled",
            device_id="device_opensprinkler",
            name=None,
            original_name="Main Valve Station Enabled",
        ),
        Mock(
            entity_id="switch.irrigation_valve_1_station_enabled",
            device_id="device_opensprinkler",
            name=None,
            original_name="Irrigation Valve 1 Station Enabled",
        ),
        Mock(
            entity_id="switch.irrigation_valve_2_station_enabled",
            device_id="device_opensprinkler",
            name=None,
            original_name="Irrigation Valve 2 Station Enabled",
        ),
        Mock(
            entity_id="switch.irrigation_program_enabled",
            device_id="device_opensprinkler",
            name=None,
            original_name="Irrigation Program Enabled",
        ),
        Mock(
            entity_id="switch.opensprinkler_enabled",
            device_id="device_opensprinkler",
            name=None,
            original_name="OpenSprinkler Enabled",
        ),
        Mock(
            entity_id="sensor.opensprinkler_status",
            device_id="device_opensprinkler",
            name=None,
            original_name="Status",
        ),
        Mock(
            entity_id="switch.kitchen_light",
            device_id="device_kitchen",
            name=None,
            original_name="Kitchen Light",
        ),
    ]
    entity_registry = Mock(
        entities={entry.entity_id: entry for entry in entity_entries}
    )

    homeassistant = types.ModuleType("homeassistant")
    helpers = types.ModuleType("homeassistant.helpers")
    device_registry_module = types.ModuleType("homeassistant.helpers.device_registry")
    entity_registry_module = types.ModuleType("homeassistant.helpers.entity_registry")
    device_registry_module.async_get = Mock(return_value=device_registry)
    entity_registry_module.async_get = Mock(return_value=entity_registry)
    entity_registry_module.async_entries_for_device = Mock(
        side_effect=lambda registry, device_id: [
            entry
            for entry in registry.entities.values()
            if entry.device_id == device_id
        ]
    )
    homeassistant.helpers = helpers
    helpers.device_registry = device_registry_module
    helpers.entity_registry = entity_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.device_registry",
        device_registry_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry_module,
    )

    hass.states = Mock()
    hass.states.get = Mock(
        side_effect=lambda entity_id: Mock(
            attributes={
                **{
                    "switch.main_valve_station_enabled": {
                        "friendly_name": "OpenSprinkler Main Valve Station Enabled",
                        "index": 0,
                        "is_master": True,
                        "name": "Main Valve",
                        "opensprinkler_type": "station",
                    },
                    "switch.irrigation_valve_1_station_enabled": {
                        "friendly_name": "OpenSprinkler Irrigation Valve 1 Station Enabled",
                        "index": 1,
                        "is_master": False,
                        "name": "Irrigation Valve 1",
                        "opensprinkler_type": "station",
                    },
                    "switch.irrigation_valve_2_station_enabled": {
                        "friendly_name": "OpenSprinkler Irrigation Valve 2 Station Enabled",
                        "index": 7,
                        "is_master": False,
                        "name": "Irrigation Valve 2",
                        "opensprinkler_type": "station",
                    },
                    "switch.irrigation_program_enabled": {
                        "friendly_name": "OpenSprinkler Irrigation Program Enabled",
                        "index": 0,
                        "name": "Irrigation Program",
                        "opensprinkler_type": "program",
                    },
                    "switch.opensprinkler_enabled": {
                        "friendly_name": "OpenSprinkler Enabled",
                        "opensprinkler_type": "controller",
                    },
                    "sensor.opensprinkler_status": {
                        "friendly_name": "OpenSprinkler Status"
                    },
                    "switch.kitchen_light": {"friendly_name": "Kitchen Light"},
                }[entity_id]
            }
        )
    )
    asyncio.run(bridge.async_initialize())

    status = asyncio.run(bridge.async_get_status())

    assert status["available_stations"] == {
        "switch.main_valve_station_enabled": (
            "OpenSprinkler Main Valve Station Enabled"
        ),
        "switch.irrigation_valve_1_station_enabled": (
            "OpenSprinkler Irrigation Valve 1 Station Enabled"
        ),
        "switch.irrigation_valve_2_station_enabled": (
            "OpenSprinkler Irrigation Valve 2 Station Enabled"
        ),
    }


def test_status_discovers_flat_sibling_opensprinkler_valves(hass, bridge, monkeypatch):
    """Test status discovers stations when every valve is a sibling."""
    opensprinkler_device = Mock(
        id="device_opensprinkler",
        name="OpenSprinkler",
        name_by_user=None,
        manufacturer="OpenSprinkler",
        model="OSPi",
        identifiers={("opensprinkler", "controller-1")},
    )
    device_registry = Mock(devices={opensprinkler_device.id: opensprinkler_device})
    entity_entries = [
        Mock(
            entity_id="switch.front_lawn_valve_station_enabled",
            device_id="device_opensprinkler",
            name=None,
            original_name="Front Lawn Valve Station Enabled",
        ),
        Mock(
            entity_id="switch.garden_beds_valve_station_enabled",
            device_id="device_opensprinkler",
            name=None,
            original_name="Garden Beds Valve Station Enabled",
        ),
        Mock(
            entity_id="switch.shrubs_valve_station_enabled",
            device_id="device_opensprinkler",
            name=None,
            original_name="Shrubs Valve Station Enabled",
        ),
    ]
    entity_registry = Mock(
        entities={entry.entity_id: entry for entry in entity_entries}
    )

    homeassistant = types.ModuleType("homeassistant")
    helpers = types.ModuleType("homeassistant.helpers")
    device_registry_module = types.ModuleType("homeassistant.helpers.device_registry")
    entity_registry_module = types.ModuleType("homeassistant.helpers.entity_registry")
    device_registry_module.async_get = Mock(return_value=device_registry)
    entity_registry_module.async_get = Mock(return_value=entity_registry)
    entity_registry_module.async_entries_for_device = Mock(return_value=entity_entries)
    homeassistant.helpers = helpers
    helpers.device_registry = device_registry_module
    helpers.entity_registry = entity_registry_module
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.device_registry",
        device_registry_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        entity_registry_module,
    )

    hass.states = Mock()
    hass.states.get = Mock(
        side_effect=lambda entity_id: Mock(
            attributes={
                "friendly_name": f"OpenSprinkler {entity_id}",
                "opensprinkler_type": "station",
            }
        )
    )
    asyncio.run(bridge.async_initialize())

    status = asyncio.run(bridge.async_get_status())

    assert status["available_stations"] == {
        "switch.front_lawn_valve_station_enabled": (
            "OpenSprinkler switch.front_lawn_valve_station_enabled"
        ),
        "switch.garden_beds_valve_station_enabled": (
            "OpenSprinkler switch.garden_beds_valve_station_enabled"
        ),
        "switch.shrubs_valve_station_enabled": (
            "OpenSprinkler switch.shrubs_valve_station_enabled"
        ),
    }


def test_run_zone_calls_opensprinkler_run_station(hass, bridge):
    """Test a mapped Smart Irrigation zone runs the OpenSprinkler station."""
    asyncio.run(bridge.async_initialize())

    result = asyncio.run(bridge.async_run_zone(1))

    hass.services.async_call.assert_awaited_once_with(
        "opensprinkler",
        "run_station",
        {
            "entity_id": "switch.front_lawn",
            "run_seconds": 600,
            "queue_option": "append",
        },
        blocking=True,
    )
    assert result["station_entity_id"] == "switch.front_lawn"
    assert result["run_seconds"] == 600
    assert result["skipped"] is False


def test_run_zone_allows_entity_and_duration_override(hass, bridge):
    """Test manual service calls can override mapping and duration."""
    asyncio.run(bridge.async_initialize())

    asyncio.run(
        bridge.async_run_zone(
            1,
            station_entity_id="switch.opensprinkler_station_override",
            run_seconds=90,
            queue_option="replace",
        )
    )

    hass.services.async_call.assert_awaited_once_with(
        "opensprinkler",
        "run_station",
        {
            "entity_id": "switch.opensprinkler_station_override",
            "run_seconds": 90,
            "queue_option": "replace",
        },
        blocking=True,
    )


def test_run_zone_skips_zero_duration(hass, bridge, store):
    """Test zero-duration zones do not call the controller."""
    store.get_zone.return_value[const.ZONE_DURATION] = 0
    asyncio.run(bridge.async_initialize())

    result = asyncio.run(bridge.async_run_zone(1))

    hass.services.async_call.assert_not_awaited()
    assert result["skipped"] is True
    assert result["reason"] == "Zone duration is 0"


def test_run_zone_requires_bridge_enabled(bridge, store):
    """Test disabled bridge refuses controller runs."""
    store.async_get_config.return_value[const.CONF_OPENSPRINKLER_INTEGRATION] = False
    asyncio.run(bridge.async_initialize())

    with pytest.raises(ValueError, match="OpenSprinkler bridge is not enabled"):
        asyncio.run(bridge.async_run_zone(1))


def test_run_zone_requires_opensprinkler_service(hass, bridge):
    """Test missing hass-opensprinkler service is reported clearly."""
    hass.services.has_service.return_value = False
    asyncio.run(bridge.async_initialize())

    with pytest.raises(ValueError, match="run_station service is not available"):
        asyncio.run(bridge.async_run_zone(1))


def test_station_map_rejects_duplicate_station_assignments():
    """One physical OpenSprinkler station can serve only one SI zone."""
    with pytest.raises(ValueError, match="already mapped"):
        OpenSprinklerBridge.validate_station_map(
            {
                "1": "switch.front_lawn_station_enabled",
                "2": "switch.front_lawn_station_enabled",
            }
        )


def test_run_zones_collects_started_skipped_and_errors(hass, bridge, store):
    """Test multi-zone runs continue when one zone is not mapped."""
    asyncio.run(bridge.async_initialize())
    store.get_zone.side_effect = [
        {
            const.ZONE_ID: 1,
            const.ZONE_NAME: "Front Lawn",
            const.ZONE_DURATION: 600,
        },
        {
            const.ZONE_ID: 2,
            const.ZONE_NAME: "Beds",
            const.ZONE_DURATION: 120,
        },
    ]

    result = asyncio.run(bridge.async_run_zones())

    assert len(result["started"]) == 1
    assert len(result["skipped"]) == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["zone_id"] == 2
    hass.bus.fire.assert_called_once()
