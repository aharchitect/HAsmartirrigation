"""The Info "next irrigation" start time honours the active trigger (#763).

Covers _trigger_start_base_and_offset, which mirrors the sunrise/sunset offset
logic of TriggersMixin so the displayed start matches when irrigation actually
begins, rather than always assuming "finish at sunrise".
"""

from custom_components.smart_irrigation import const
from custom_components.smart_irrigation.websockets import (
    _trigger_start_base_and_offset,
)

_TD = 600  # total_duration seconds


def _trig(ttype, offset=0, account=True):
    return {
        const.TRIGGER_CONF_TYPE: ttype,
        const.TRIGGER_CONF_OFFSET_MINUTES: offset,
        const.TRIGGER_CONF_ACCOUNT_FOR_DURATION: account,
    }


def test_default_trigger_finishes_at_sunrise():
    assert _trigger_start_base_and_offset(None, _TD) == ("sunrise", -_TD)


def test_sunrise_offset_accounting_for_duration():
    # The reporter's "before sunrise -2h" trigger, accounting for duration.
    trig = _trig(const.TRIGGER_TYPE_SUNRISE, offset=-120, account=True)
    assert _trigger_start_base_and_offset(trig, _TD) == ("sunrise", -120 * 60 - _TD)


def test_sunrise_zero_offset_finishes_at_sunrise():
    trig = _trig(const.TRIGGER_TYPE_SUNRISE, offset=0, account=True)
    assert _trigger_start_base_and_offset(trig, _TD) == ("sunrise", -_TD)


def test_sunrise_starts_exactly_at_offset_without_duration():
    trig = _trig(const.TRIGGER_TYPE_SUNRISE, offset=30, account=False)
    assert _trigger_start_base_and_offset(trig, _TD) == ("sunrise", 30 * 60)


def test_sunset_accounting_for_duration():
    trig = _trig(const.TRIGGER_TYPE_SUNSET, offset=0, account=True)
    assert _trigger_start_base_and_offset(trig, _TD) == ("sunset", -_TD)


def test_sunset_starts_exactly_at_offset_without_duration():
    trig = _trig(const.TRIGGER_TYPE_SUNSET, offset=15, account=False)
    assert _trigger_start_base_and_offset(trig, _TD) == ("sunset", 15 * 60)


def test_solar_azimuth_falls_back_to_sunrise_minus_duration():
    trig = _trig(const.TRIGGER_TYPE_SOLAR_AZIMUTH, offset=45, account=True)
    assert _trigger_start_base_and_offset(trig, _TD) == ("sunrise", -_TD)
