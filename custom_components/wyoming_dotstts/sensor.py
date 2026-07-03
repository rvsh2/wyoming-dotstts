"""Voice profile sensor for the dots.tts server."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DotsTtsEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DotsTtsVoicesSensor(entry, runtime)])


class DotsTtsVoicesSensor(DotsTtsEntity, SensorEntity):
    _attr_name = "Voices"
    _attr_icon = "mdi:account-voice"
    _attr_native_unit_of_measurement = "voices"

    def __init__(self, entry: ConfigEntry, runtime: dict) -> None:
        super().__init__(entry, runtime, "voices")

    @property
    def _profiles(self) -> dict:
        return self._health.get("speaker_profiles") or {}

    @property
    def native_value(self) -> int:
        return len(self._profiles.get("valid") or [])

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "voices": [profile["name"] for profile in self._profiles.get("valid") or []],
            "invalid": {
                profile["name"]: profile["reason"]
                for profile in self._profiles.get("invalid") or []
            },
        }
