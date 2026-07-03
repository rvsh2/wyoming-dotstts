"""Number entities controlling dots.tts runtime settings (seed, gain)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DotsTtsEntity

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
            DotsTtsNumStepsNumber(entry, runtime),
        ]
    )


class _DotsTtsSettingsNumber(DotsTtsEntity, NumberEntity):
    def __init__(self, entry: ConfigEntry, runtime: dict) -> None:
        super().__init__(entry, runtime, self.setting_key)


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


class DotsTtsNumStepsNumber(_DotsTtsSettingsNumber):
    setting_key = "num_steps"

    _attr_name = "Diffusion steps"
    _attr_icon = "mdi:stairs"
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 1
    _attr_native_max_value = 16
    _attr_native_step = 1

    @property
    def native_value(self) -> int:
        return int(self._settings.get("num_steps") or 4)

    async def async_set_native_value(self, value: float) -> None:
        await self._post_settings({"num_steps": int(value)})
