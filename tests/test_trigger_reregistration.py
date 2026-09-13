"""Editing the start trigger takes effect without a restart (#800).

The panel saves the trigger through ``coordinator.async_update_config``, which
wrote it to the store and stopped there. The already registered sunrise/sunset
tracker kept the old schedule, so the Info tab showed the new start time while
irrigation still began at the old one until Home Assistant was restarted.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.smart_irrigation import SmartIrrigationCoordinator, const


def _coordinator():
    """Build a coordinator without running its (very wide) __init__."""
    coordinator = SmartIrrigationCoordinator.__new__(SmartIrrigationCoordinator)
    coordinator.hass = MagicMock()
    coordinator.store = MagicMock()
    coordinator.store.async_update_config = AsyncMock()
    coordinator.store.async_get_config = AsyncMock(return_value={})
    coordinator.set_up_auto_calc_time = AsyncMock()
    coordinator.set_up_auto_update_time = AsyncMock()
    coordinator.set_up_auto_clear_time = AsyncMock()
    coordinator.async_setup_observed_watering = AsyncMock()
    coordinator.register_start_event = AsyncMock()
    coordinator.opensprinkler_bridge = MagicMock()
    coordinator.opensprinkler_bridge.async_update_configuration = AsyncMock()
    return coordinator


async def _update(coordinator, data):
    with patch("custom_components.smart_irrigation.async_dispatcher_send"):
        await coordinator.async_update_config(data)


async def test_editing_a_trigger_reregisters_it():
    coordinator = _coordinator()

    await _update(
        coordinator,
        {
            const.CONF_IRRIGATION_START_TRIGGERS: [
                {
                    const.TRIGGER_CONF_NAME: "before sunrise",
                    const.TRIGGER_CONF_TYPE: const.TRIGGER_TYPE_SUNRISE,
                    const.TRIGGER_CONF_OFFSET_MINUTES: -120,
                }
            ]
        },
    )

    assert coordinator.register_start_event.await_count == 1


async def test_selecting_another_trigger_reregisters_it():
    coordinator = _coordinator()

    await _update(coordinator, {const.CONF_ACTIVE_START_TRIGGER: "after sunset"})

    assert coordinator.register_start_event.await_count == 1


async def test_the_trigger_is_written_before_it_is_reregistered():
    """register_start_event reads the store, so the order matters."""
    coordinator = _coordinator()
    calls = []
    coordinator.store.async_update_config = AsyncMock(
        side_effect=lambda *a, **kw: calls.append("store")
    )
    coordinator.register_start_event = AsyncMock(
        side_effect=lambda *a, **kw: calls.append("register")
    )

    await _update(coordinator, {const.CONF_ACTIVE_START_TRIGGER: "after sunset"})

    assert calls == ["store", "register"]


async def test_unrelated_settings_do_not_reregister():
    """Saving the rest of the general settings must stay a cheap store write."""
    coordinator = _coordinator()

    await _update(coordinator, {const.CONF_DAYS_BETWEEN_IRRIGATION: 3})

    assert coordinator.register_start_event.await_count == 0


async def test_partial_config_updates_reconfigure_timers_with_full_config():
    coordinator = _coordinator()
    current_config = {
        const.CONF_AUTO_CALC_ENABLED: False,
        const.CONF_AUTO_UPDATE_ENABLED: False,
        const.CONF_AUTO_CLEAR_ENABLED: False,
    }
    coordinator.store.async_get_config = AsyncMock(return_value=current_config)

    await _update(
        coordinator,
        {const.CONF_OPENSPRINKLER_STATION_MAP: {"0": "switch.opensprinkler_0"}},
    )

    for setup_timer in (
        coordinator.set_up_auto_calc_time,
        coordinator.set_up_auto_update_time,
        coordinator.set_up_auto_clear_time,
    ):
        setup_timer.assert_awaited_once()
        assert setup_timer.await_args.args[0][const.CONF_AUTO_CALC_ENABLED] is False
        assert setup_timer.await_args.args[0][const.CONF_OPENSPRINKLER_STATION_MAP] == {
            "0": "switch.opensprinkler_0"
        }
