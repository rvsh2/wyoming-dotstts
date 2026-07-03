"""Shared entity base for the Wyoming dots.tts integration."""

from __future__ import annotations

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)


class DotsTtsEntity(CoordinatorEntity):
    """Coordinator entity bound to the server device."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, runtime: dict, key: str) -> None:
        super().__init__(runtime["coordinator"])
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        # The device is the wyoming-dotstts server, not the model vendor —
        # rednote-hilab only made the checkpoint, which is what "model" shows
        # (HA renders the card as "<model> by <manufacturer>").
        model = (self._health.get("model") or "dots.tts").rsplit("/", 1)[-1]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="dotsTTS",
            manufacturer="wyoming-dotstts",
            model=model,
        )

    @property
    def _health(self) -> dict:
        return (self.coordinator.data or {}).get("health") or {}

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
