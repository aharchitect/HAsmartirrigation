"""Regression test for the watering_now binary sensor (#768).

The linked valve/switch is usually set after the zone entity already exists, so
binding it only once at add time meant the sensor never tracked it and stayed
"Not Running". It now rebinds on every zone config update.
"""

from types import SimpleNamespace
from unittest.mock import Mock

from custom_components.smart_irrigation import binary_sensor as bs_mod
from custom_components.smart_irrigation import const
from custom_components.smart_irrigation.binary_sensor import (
    SmartIrrigationZoneWateringNowBinarySensor,
)


def _make_hass(zone):
    hass = Mock()
    store = Mock()
    store.get_zone = Mock(return_value=zone)
    hass.data = {const.DOMAIN: {"coordinator": SimpleNamespace(store=store)}}
    hass.states = Mock()
    hass.states.get = lambda eid: None
    return hass


def test_watering_now_rebinds_when_valve_linked_later(monkeypatch):
    """A valve linked after the entity exists is tracked on the next config update."""
    tracked = {}

    def _fake_track(hass, entities, cb):
        tracked["entities"] = list(entities)
        tracked["cb"] = cb
        return Mock(name="unsub")

    monkeypatch.setattr(bs_mod, "async_track_state_change_event", _fake_track)

    # Zone starts with no linked valve.
    zone = {const.ZONE_ID: 0, const.ZONE_NAME: "Z"}
    hass = _make_hass(zone)

    sensor = SmartIrrigationZoneWateringNowBinarySensor(
        hass, "binary_sensor.z_watering_now", 0, "Z"
    )
    sensor.async_write_ha_state = lambda: None

    # Initial bind: nothing linked -> off, and no state subscription made.
    sensor._resubscribe()
    assert sensor._attr_is_on is False
    assert "entities" not in tracked

    # The user links a switch (already on) and the zone config updates.
    zone[const.ZONE_LINKED_ENTITY] = "switch.valve"
    hass.states.get = lambda eid: SimpleNamespace(state="on")
    sensor._async_config_updated(0)

    assert tracked["entities"] == ["switch.valve"]
    assert sensor._attr_is_on is True

    # Turning the switch off flips the sensor back via the tracked callback.
    hass.states.get = lambda eid: SimpleNamespace(state="off")
    tracked["cb"](Mock())
    assert sensor._attr_is_on is False
