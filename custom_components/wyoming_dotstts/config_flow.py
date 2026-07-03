"""Config flow for the Wyoming dots.tts integration."""

from __future__ import annotations

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import aiohttp_client

from .const import CONF_API_TOKEN, CONF_HOST, CONF_PORT, DEFAULT_PORT, DOMAIN

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_API_TOKEN, default=""): str,
    }
)


class WyomingDotsTtsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Ask for host/port/token and verify the management API answers."""

    VERSION = 1

    async def _token_status(self, host: str, port: int, token: str) -> int:
        """HTTP status of a token-protected endpoint (401 = bad token)."""
        session = aiohttp_client.async_get_clientsession(self.hass)
        async with session.get(
            f"http://{host}:{port}/settings",
            headers={"X-API-Token": token} if token else {},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            return response.status

    async def async_step_reauth(self, entry_data):
        """Server rejected the stored token: ask for a new one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            token = user_input.get(CONF_API_TOKEN, "").strip()
            try:
                status = await self._token_status(
                    entry.data[CONF_HOST], entry.data[CONF_PORT], token
                )
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                if status == 401:
                    errors["base"] = "invalid_auth"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data={**entry.data, CONF_API_TOKEN: token}
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): str}),
            errors=errors,
        )

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            token = user_input.get(CONF_API_TOKEN, "").strip()

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            session = aiohttp_client.async_get_clientsession(self.hass)
            try:
                async with session.get(
                    f"http://{host}:{port}/health",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    response.raise_for_status()
                    await response.json()
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                # /health is open; /settings exercises the token so a wrong
                # token fails here instead of on every later call.
                try:
                    async with session.get(
                        f"http://{host}:{port}/settings",
                        headers={"X-API-Token": token} if token else {},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as response:
                        if response.status == 401:
                            errors["base"] = "invalid_auth"
                        else:
                            response.raise_for_status()
                except Exception:
                    if "base" not in errors:
                        errors["base"] = "cannot_connect"

            if not errors:
                return self.async_create_entry(
                    title=f"dots.tts ({host})",
                    data={CONF_HOST: host, CONF_PORT: port, CONF_API_TOKEN: token},
                )

        return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA, errors=errors)
