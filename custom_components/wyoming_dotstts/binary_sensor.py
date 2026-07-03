"""Readiness binary sensor for the dots.tts server."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DotsTtsEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DotsTtsReadySensor(entry, runtime)])


class DotsTtsReadySensor(DotsTtsEntity, BinarySensorEntity):
    _attr_name = "Ready"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, entry: ConfigEntry, runtime: dict) -> None:
        super().__init__(entry, runtime, "ready")

    @property
    def is_on(self) -> bool:
        # Coordinator failures (server unreachable) make the entity
        # unavailable via CoordinatorEntity; this covers "up but still
        # loading the model".
        return bool(self._health.get("ready"))
