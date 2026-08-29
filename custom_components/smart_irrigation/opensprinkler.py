"""Optional OpenSprinkler bridge for Smart Irrigation.

This module intentionally talks to the Home Assistant OpenSprinkler integration
through HA services instead of calling the controller HTTP API directly. That
keeps controller discovery, authentication, and API compatibility owned by the
OpenSprinkler integration and lets Smart Irrigation stay controller-agnostic
unless the bridge is explicitly enabled.
"""

import datetime
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from . import const

_LOGGER = logging.getLogger(__name__)


class OpenSprinklerBridge:
    """Bridge Smart Irrigation zones to the OpenSprinkler HA integration."""

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        """Initialize the OpenSprinkler bridge."""
        self.hass = hass
        self.coordinator = coordinator
        self._enabled = False
        self._station_map: dict[str, str] = {}
        self._queue_option = const.CONF_DEFAULT_OPENSPRINKLER_QUEUE_OPTION

    async def async_initialize(self) -> None:
        """Load bridge configuration and enable it for a configured controller."""
        config = await self.coordinator.store.async_get_config()
        if (
            not config.get(
                const.CONF_OPENSPRINKLER_INTEGRATION,
                const.CONF_DEFAULT_OPENSPRINKLER_INTEGRATION,
            )
            and self._has_opensprinkler_config_entry()
        ):
            await self.coordinator.store.async_update_config(
                {const.CONF_OPENSPRINKLER_INTEGRATION: True}
            )
            config = {
                **config,
                const.CONF_OPENSPRINKLER_INTEGRATION: True,
            }
            _LOGGER.info(
                "Enabled the OpenSprinkler bridge because an OpenSprinkler "
                "config entry is configured"
            )
        await self.async_update_configuration(config)

    async def async_update_configuration(self, config: dict[str, Any]) -> None:
        """Update bridge configuration from Smart Irrigation config."""
        self._enabled = config.get(
            const.CONF_OPENSPRINKLER_INTEGRATION,
            const.CONF_DEFAULT_OPENSPRINKLER_INTEGRATION,
        )
        # The map is stored as Smart Irrigation zone ID -> station switch
        # entity ID. Entity IDs can be user-renamed, so discovery uses the
        # OpenSprinkler device registry entry rather than an entity name prefix.
        self._station_map = {
            str(zone_id): entity_id
            for zone_id, entity_id in config.get(
                const.CONF_OPENSPRINKLER_STATION_MAP,
                const.CONF_DEFAULT_OPENSPRINKLER_STATION_MAP,
            ).items()
            if entity_id
        }
        self._queue_option = config.get(
            const.CONF_OPENSPRINKLER_QUEUE_OPTION,
            const.CONF_DEFAULT_OPENSPRINKLER_QUEUE_OPTION,
        )

        if self._enabled:
            _LOGGER.info(
                "OpenSprinkler bridge enabled with %d mapped station(s)",
                len(self._station_map),
            )

    def is_enabled(self) -> bool:
        """Return whether the bridge is enabled."""
        return self._enabled

    def _has_opensprinkler_config_entry(self) -> bool:
        """Return whether Home Assistant has a configured OpenSprinkler entry."""
        config_entries = getattr(self.hass, "config_entries", None)
        async_entries = getattr(config_entries, "async_entries", None)
        if not callable(async_entries):
            return False

        entries = async_entries(const.OPENSPRINKLER_DOMAIN)
        # Home Assistant returns a list. Restrict the accepted types so unit
        # test mocks or a malformed integration object cannot enable the bridge.
        return isinstance(entries, (list, tuple, set)) and bool(entries)

    def _has_run_station_service(self) -> bool:
        """Return whether the OpenSprinkler run_station service is available."""
        # No manifest dependency is declared, so service availability is the
        # runtime contract that tells us whether hass-opensprinkler is installed.
        return self.hass.services.has_service(
            const.OPENSPRINKLER_DOMAIN, const.OPENSPRINKLER_SERVICE_RUN_STATION
        )

    def _station_for_zone(self, zone_id: int | str) -> str | None:
        """Return mapped OpenSprinkler station entity for a Smart Irrigation zone."""
        return self._station_map.get(str(zone_id))

    @staticmethod
    def validate_station_map(station_map: dict[str, str]) -> None:
        """Ensure a station is mapped to no more than one SI zone."""
        stations: dict[str, str] = {}
        for zone_id, entity_id in station_map.items():
            if not entity_id:
                continue

            previous_zone_id = stations.get(entity_id)
            if previous_zone_id is not None:
                raise ValueError(
                    "OpenSprinkler station "
                    f"{entity_id} is already mapped to Smart Irrigation zone "
                    f"{previous_zone_id}"
                )
            stations[entity_id] = str(zone_id)

    def _is_opensprinkler_device(self, device: Any) -> bool:
        """Return whether a device registry entry is the OpenSprinkler device."""
        device_text = " ".join(
            str(value).lower()
            for value in (
                getattr(device, "name_by_user", None),
                getattr(device, "name", None),
                getattr(device, "manufacturer", None),
                getattr(device, "model", None),
            )
            if value
        )
        if "opensprinkler" in device_text:
            return True

        identifiers = getattr(device, "identifiers", set()) or set()
        for identifier in identifiers:
            if any("opensprinkler" in str(part).lower() for part in identifier):
                return True
        return False

    def _entries_for_device(self, entity_registry: Any, device_id: str) -> list[Any]:
        """Return entity registry entries tied to a device."""
        try:
            from homeassistant.helpers import entity_registry as er
        except ImportError:
            er = None

        if er is not None and hasattr(er, "async_entries_for_device"):
            return list(er.async_entries_for_device(entity_registry, device_id))

        entities = getattr(entity_registry, "entities", {}) or {}
        return [
            entry
            for entry in entities.values()
            if getattr(entry, "device_id", None) == device_id
        ]

    def _friendly_name_for_station(self, entry: Any) -> str:
        """Return the display name for an OpenSprinkler station entity."""
        entity_id = getattr(entry, "entity_id", "")
        state = (
            self.hass.states.get(entity_id)
            if hasattr(self.hass, "states") and entity_id
            else None
        )
        if state is not None:
            friendly_name = state.attributes.get("friendly_name")
            if friendly_name:
                return friendly_name

        return (
            getattr(entry, "name", None)
            or getattr(entry, "original_name", None)
            or entity_id
        )

    def _is_station_switch(self, entry: Any) -> bool:
        """Return whether an entity registry entry is an OpenSprinkler station switch."""
        entity_id = getattr(entry, "entity_id", "")
        if not entity_id.startswith("switch."):
            return False

        state = (
            self.hass.states.get(entity_id)
            if hasattr(self.hass, "states") and entity_id
            else None
        )
        if state is not None:
            opensprinkler_type = state.attributes.get("opensprinkler_type")
            if opensprinkler_type is not None:
                return opensprinkler_type == "station"

        return "_station_" in entity_id

    def _available_stations(self) -> dict[str, str]:
        """Return OpenSprinkler station switch entities available in Home Assistant."""
        try:
            from homeassistant.helpers import device_registry as dr
            from homeassistant.helpers import entity_registry as er
        except ImportError:
            return {}

        try:
            device_registry = dr.async_get(self.hass)
            entity_registry = er.async_get(self.hass)
        except (AttributeError, KeyError, TypeError):
            return {}

        devices = getattr(device_registry, "devices", {}) or {}
        if not devices:
            return {}

        stations: dict[str, str] = {}
        for device in devices.values():
            if not self._is_opensprinkler_device(device):
                continue

            device_id = getattr(device, "id", None)
            if not device_id:
                continue

            for entry in self._entries_for_device(entity_registry, device_id):
                if not self._is_station_switch(entry):
                    continue
                entity_id = getattr(entry, "entity_id", "")
                stations[entity_id] = self._friendly_name_for_station(entry)
        return stations

    async def async_run_zone(
        self,
        zone_id: int | str,
        *,
        station_entity_id: str | None = None,
        run_seconds: int | float | None = None,
        queue_option: str | None = None,
    ) -> dict[str, Any]:
        """Run one OpenSprinkler station for a Smart Irrigation zone."""
        if not self._enabled:
            raise ValueError("OpenSprinkler bridge is not enabled")

        if not self._has_run_station_service():
            raise ValueError("OpenSprinkler run_station service is not available")

        zone = self.coordinator.store.get_zone(zone_id)
        if zone is None:
            raise ValueError(f"Smart Irrigation zone {zone_id} not found")

        # By default, use the duration calculated by Smart Irrigation. The
        # service can override it for manual tests or one-off runs.
        duration = int(
            run_seconds if run_seconds is not None else zone.get(const.ZONE_DURATION, 0)
        )
        if duration <= 0:
            # A zero duration means Smart Irrigation decided this zone does not
            # need watering right now, so do not call the controller.
            return {
                "zone_id": zone_id,
                "zone_name": zone.get(const.ZONE_NAME),
                "skipped": True,
                "reason": "Zone duration is 0",
            }

        entity_id = station_entity_id or self._station_for_zone(zone_id)
        if not entity_id:
            raise ValueError(f"No OpenSprinkler station mapped for zone {zone_id}")

        service_data = {
            "entity_id": entity_id,
            "run_seconds": duration,
            "queue_option": queue_option or self._queue_option,
        }
        await self.hass.services.async_call(
            const.OPENSPRINKLER_DOMAIN,
            const.OPENSPRINKLER_SERVICE_RUN_STATION,
            service_data,
            blocking=True,
        )

        result = {
            "zone_id": zone_id,
            "zone_name": zone.get(const.ZONE_NAME),
            "station_entity_id": entity_id,
            "run_seconds": duration,
            "queue_option": service_data["queue_option"],
            "skipped": False,
        }
        _LOGGER.info(
            "Started OpenSprinkler station %s for Smart Irrigation zone %s (%d seconds)",
            entity_id,
            zone_id,
            duration,
        )
        return result

    async def async_run_zones(
        self, zone_ids: list[int | str] | None = None
    ) -> dict[str, Any]:
        """Run mapped OpenSprinkler stations for Smart Irrigation zones."""
        if not self._enabled:
            raise ValueError("OpenSprinkler bridge is not enabled")

        zones = await self.coordinator.store.async_get_zones()
        if zone_ids:
            wanted_zone_ids = {str(zone_id) for zone_id in zone_ids}
            zones = [
                zone
                for zone in zones
                if str(zone.get(const.ZONE_ID)) in wanted_zone_ids
            ]

        results = {"started": [], "skipped": [], "errors": []}
        for zone in zones:
            zone_id = zone.get(const.ZONE_ID)
            try:
                # Keep going per-zone: one missing mapping or controller error
                # should not prevent other valid stations from starting.
                result = await self.async_run_zone(zone_id)
            except Exception as err:  # noqa: BLE001 - collect per-zone bridge failures
                _LOGGER.error("Failed to run OpenSprinkler zone %s: %s", zone_id, err)
                results["errors"].append(
                    {
                        "zone_id": zone_id,
                        "zone_name": zone.get(const.ZONE_NAME),
                        "error": str(err),
                    }
                )
                continue

            if result.get("skipped"):
                results["skipped"].append(result)
            else:
                results["started"].append(result)

        self.hass.bus.fire(
            f"{const.DOMAIN}_{const.EVENT_OPENSPRINKLER_RUN_COMPLETED}",
            {
                "results": results,
                "timestamp": datetime.datetime.now().isoformat(),
            },
        )
        return results

    async def async_get_status(self) -> dict[str, Any]:
        """Return OpenSprinkler bridge status."""
        return {
            "enabled": self._enabled,
            "run_station_service_available": self._has_run_station_service(),
            "queue_option": self._queue_option,
            "mapped_zones": self._station_map.copy(),
            "available_stations": self._available_stations(),
        }
