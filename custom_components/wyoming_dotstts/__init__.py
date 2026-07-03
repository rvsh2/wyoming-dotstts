"""Wyoming dots.tts integration: runtime settings (seed, gain) for the TTS server.

The Wyoming protocol itself cannot carry these options from Home Assistant, so
this companion integration talks to the server's HTTP management API instead.
Settings apply server-side to every synthesis request.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import aiohttp
from aiohttp import web

from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError, Unauthorized
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_API_TOKEN,
    CONF_HOST,
    CONF_PORT,
    DOMAIN,
    PANEL_ICON,
    PANEL_STATIC_PATH,
    PANEL_TITLE,
    PANEL_URL_PATH,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]
SCAN_INTERVAL = timedelta(seconds=60)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
# Synthesis (panel voice test) can take tens of seconds on a cold GPU.
PROXY_TIMEOUT = aiohttp.ClientTimeout(total=180)


def _first_runtime(hass: HomeAssistant) -> dict:
    """First configured server — the panel manages a single server by design."""
    runtimes = hass.data.get(DOMAIN) or {}
    if not runtimes:
        raise HomeAssistantError("No dots.TTS server is configured")
    return next(iter(runtimes.values()))


class DotsTtsProxyView(HomeAssistantView):
    """Authenticated proxy to the server's management API.

    The panel calls this view with the user's HA credentials
    (hass.fetchWithAuth); the view forwards to the server adding the API
    token, so the token never reaches the browser and port 8180 only needs
    to be reachable from the HA host.
    """

    url = "/api/wyoming_dotstts/proxy/{path:.+}"
    name = "api:wyoming_dotstts:proxy"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def _proxy(self, request: web.Request, path: str) -> web.Response:
        user = request.get("hass_user")
        if user is None or not user.is_admin:
            raise Unauthorized()

        runtime = _first_runtime(self.hass)
        headers = dict(runtime["headers"])
        if request.content_type:
            # Preserve the multipart boundary for voice uploads.
            headers["Content-Type"] = request.headers.get("Content-Type", "")
        body = await request.read() if request.method in ("POST", "PUT") else None

        try:
            async with runtime["session"].request(
                request.method,
                f"{runtime['base']}/{path}",
                params=request.query,
                data=body,
                headers=headers,
                timeout=PROXY_TIMEOUT,
            ) as response:
                payload = await response.read()
                return web.Response(
                    body=payload,
                    status=response.status,
                    content_type=response.content_type,
                )
        except HomeAssistantError:
            raise
        except Exception as error:
            return web.json_response({"detail": f"dots.TTS server unreachable: {error}"}, status=502)

    async def get(self, request: web.Request, path: str) -> web.Response:
        return await self._proxy(request, path)

    async def post(self, request: web.Request, path: str) -> web.Response:
        return await self._proxy(request, path)

    async def delete(self, request: web.Request, path: str) -> web.Response:
        return await self._proxy(request, path)


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
                if response.status == 401:
                    # Wrong/rotated token: trigger HA's reauth flow instead of
                    # reporting a misleading connectivity failure.
                    raise ConfigEntryAuthFailed("Invalid API token")
                response.raise_for_status()
                data["settings"] = await response.json()
        except ConfigEntryAuthFailed:
            raise
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

    # Serve the panel module and register it as a custom sidebar panel. The
    # panel talks to the server exclusively through the authenticated proxy
    # view, so browsers never need direct access to port 8180.
    if not hass.data.get(f"{DOMAIN}_http_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    PANEL_STATIC_PATH,
                    str(Path(__file__).parent / "frontend"),
                    cache_headers=False,
                )
            ]
        )
        hass.http.register_view(DotsTtsProxyView(hass))
        hass.data[f"{DOMAIN}_http_registered"] = True

    frontend.async_register_built_in_panel(
        hass,
        "custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        frontend_url_path=PANEL_URL_PATH,
        config={
            "_panel_custom": {
                "name": "dots-tts-panel",
                "module_url": f"{PANEL_STATIC_PATH}/panel.js",
                "embed_iframe": False,
                "trust_external": False,
            }
        },
        require_admin=True,
        update=True,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            frontend.async_remove_panel(hass, PANEL_URL_PATH)
    return unload_ok
