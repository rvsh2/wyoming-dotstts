"""Switch entities for dots.tts boolean runtime settings."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DotsTtsEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DotsTtsSettingSwitch(entry, runtime, "trim_silence", "Trim silence", "mdi:content-cut"),
            DotsTtsSettingSwitch(entry, runtime, "normalize_text", "Normalize text", "mdi:format-letter-case"),
        ]
    )


class DotsTtsSettingSwitch(DotsTtsEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, runtime: dict, key: str, name: str, icon: str) -> None:
        super().__init__(entry, runtime, key)
        self._key = key
        self._attr_name = name
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        return bool(self._settings.get(self._key))

    async def async_turn_on(self, **kwargs) -> None:
        await self._post_settings({self._key: True})

    async def async_turn_off(self, **kwargs) -> None:
        await self._post_settings({self._key: False})
