"""Wyoming dots.tts integration: runtime settings (seed, gain) for the TTS server.

The Wyoming protocol itself cannot carry these options from Home Assistant, so
this companion integration talks to the server's HTTP management API instead.
Settings apply server-side to every synthesis request.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_API_TOKEN, CONF_HOST, CONF_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.NUMBER]
SCAN_INTERVAL = timedelta(seconds=60)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)


def base_url(entry: ConfigEntry) -> str:
    return f"http://{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    base = base_url(entry)
    token = entry.data.get(CONF_API_TOKEN) or None
    headers = {"X-API-Token": token} if token else {}
    session = aiohttp_client.async_get_clientsession(hass)

    async def _async_update() -> dict:
        data: dict = {"health": None, "settings": None}
        try:
            async with session.get(f"{base}/health", timeout=REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                data["health"] = await response.json()
            async with session.get(
                f"{base}/settings", headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                data["settings"] = await response.json()
        except Exception as error:
            raise UpdateFailed(f"Cannot reach {base}: {error}") from error
        return data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=_async_update,
        update_interval=SCAN_INTERVAL,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "base": base,
        "headers": headers,
        "session": session,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
