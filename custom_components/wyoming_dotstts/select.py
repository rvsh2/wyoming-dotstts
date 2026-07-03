"""Select entities for dots.tts voice and language runtime settings."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DotsTtsEntity

# "auto" maps to null on the server: first valid profile (voice) or
# model auto-detection (language).
AUTO = "auto"

# Mirrors DEFAULT_LANGUAGES advertised by the server.
LANGUAGES = [
    AUTO, "en", "pl", "de", "fr", "es", "it", "pt", "nl", "cs", "sk",
    "uk", "ru", "zh", "ja", "ko",
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DotsTtsVoiceSelect(entry, runtime),
            DotsTtsLanguageSelect(entry, runtime),
        ]
    )


class DotsTtsVoiceSelect(DotsTtsEntity, SelectEntity):
    _attr_name = "Default voice"
    _attr_icon = "mdi:account-voice"

    def __init__(self, entry: ConfigEntry, runtime: dict) -> None:
        super().__init__(entry, runtime, "default_voice")

    @property
    def options(self) -> list[str]:
        profiles = (self._health.get("speaker_profiles") or {}).get("valid") or []
        return [AUTO] + [profile["name"] for profile in profiles]

    @property
    def current_option(self) -> str:
        # Guard against a persisted voice whose profile has since been
        # deleted/invalidated — an option outside `options` makes HA raise on
        # every coordinator refresh.
        voice = self._settings.get("default_voice") or AUTO
        return voice if voice in self.options else AUTO

    async def async_select_option(self, option: str) -> None:
        await self._post_settings({"default_voice": None if option == AUTO else option})


class DotsTtsLanguageSelect(DotsTtsEntity, SelectEntity):
    _attr_name = "Language"
    _attr_icon = "mdi:translate"
    _attr_options = LANGUAGES

    def __init__(self, entry: ConfigEntry, runtime: dict) -> None:
        super().__init__(entry, runtime, "language")

    @property
    def current_option(self) -> str:
        language = self._settings.get("language") or AUTO
        return language if language in LANGUAGES else AUTO

    async def async_select_option(self, option: str) -> None:
        await self._post_settings({"language": None if option == AUTO else option})
