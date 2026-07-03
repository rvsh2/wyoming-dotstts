"""Number entities controlling dots.tts runtime settings (seed, gain)."""

from __future__ import annotations

import logging

import aiohttp

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

# The seed entity uses -1 for "random seed" (the server stores null): HA
# number entities cannot express "unset" directly.
SEED_RANDOM = -1


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DotsTtsSeedNumber(entry, runtime),
            DotsTtsGainNumber(entry, runtime),
        ]
    )


class _DotsTtsSettingsNumber(CoordinatorEntity, NumberEntity):
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, runtime: dict) -> None:
        super().__init__(runtime["coordinator"])
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_{self.setting_key}"
        model = ((self.coordinator.data or {}).get("health") or {}).get("model") or "dots.tts"
        # HA renders the device card as "<model> by <manufacturer>", so strip
        # the HF org prefix from the model name to avoid "rednote-hilab/...
        # by rednote-hilab".
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Wyoming dots.tts",
            manufacturer="rednote-hilab",
            model=model.rsplit("/", 1)[-1],
        )

    @property
    def _settings(self) -> dict:
        return (self.coordinator.data or {}).get("settings") or {}

    async def _post_settings(self, payload: dict) -> None:
        try:
            async with self._runtime["session"].post(
                f"{self._runtime['base']}/settings",
                json=payload,
                headers=self._runtime["headers"],
                timeout=REQUEST_TIMEOUT,
            ) as response:
                response.raise_for_status()
        except Exception as error:
            raise HomeAssistantError(f"Failed to update dots.tts settings: {error}") from error
        await self.coordinator.async_request_refresh()


class DotsTtsSeedNumber(_DotsTtsSettingsNumber):
    setting_key = "seed"

    _attr_name = "Seed"
    _attr_icon = "mdi:dice-multiple"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = SEED_RANDOM
    _attr_native_max_value = 2**31 - 1
    _attr_native_step = 1

    @property
    def native_value(self) -> int:
        seed = self._settings.get("seed")
        return SEED_RANDOM if seed is None else int(seed)

    async def async_set_native_value(self, value: float) -> None:
        seed = None if value <= SEED_RANDOM else int(value)
        await self._post_settings({"seed": seed})


class DotsTtsGainNumber(_DotsTtsSettingsNumber):
    setting_key = "gain_db"

    _attr_name = "Gain"
    _attr_icon = "mdi:volume-plus"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = -20.0
    _attr_native_max_value = 20.0
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "dB"

    @property
    def native_value(self) -> float:
        return float(self._settings.get("gain_db") or 0.0)

    async def async_set_native_value(self, value: float) -> None:
        await self._post_settings({"gain_db": value})
