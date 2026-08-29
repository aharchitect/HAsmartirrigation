"""Frontend contract tests for OpenSprinkler zone mapping UI."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
ZONES_VIEW = (
    REPO_ROOT
    / "custom_components"
    / "smart_irrigation"
    / "frontend"
    / "src"
    / "views"
    / "zones"
    / "view-zones.ts"
)


@pytest.fixture
def enable_custom_integrations():
    """Keep this static frontend test independent from HA plugin fixtures."""
    yield


def test_zones_view_exposes_opensprinkler_station_mapping_control():
    """Zone cards should let users map a Smart Irrigation zone to a station."""
    source = ZONES_VIEW.read_text(encoding="utf-8")

    assert "CONF_OPENSPRINKLER_INTEGRATION" in source
    assert "CONF_OPENSPRINKLER_STATION_MAP" in source
    assert "OpenSprinkler station" in source
    assert "opensprinkler_station_map" in source
    assert "config/device_registry/list" in source
    assert "config/entity_registry/list" in source
    assert "opensprinkler_type" in source
    assert '"station"' in source
    assert "mappedToAnotherZone" in source
    assert "?disabled=${mappedToAnotherZone}" in source
    assert "switch.opensprinkler" not in source
