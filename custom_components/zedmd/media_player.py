"""ZeDMD media_player entity."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BRIGHTNESS_MAX,
    CONF_HOST,
    CONF_NAME,
    CONF_STREAM_PORT,
    DOMAIN,
)
from .coordinator import ZeDMDCoordinator

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.PLAY_MEDIA
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ZeDMD media player from a config entry."""
    coordinator: ZeDMDCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ZeDMDMediaPlayer(coordinator, entry)])


class ZeDMDMediaPlayer(MediaPlayerEntity):
    """Representation of a ZeDMD LED matrix as a media_player entity."""

    _attr_has_entity_name = True
    _attr_name = None  # use device name
    _attr_media_content_type = MediaType.MUSIC  # closest HA type; display-only device
    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(self, coordinator: ZeDMDCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry

        self._attr_unique_id = f"{entry.data[CONF_HOST]}_{entry.data[CONF_STREAM_PORT]}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=entry.data[CONF_NAME],
            manufacturer="PPUC",
            model="ZeDMD",
            sw_version=coordinator.firmware_version,
            configuration_url=(
                f"http://{entry.data[CONF_HOST]}:{entry.data.get('http_port', 80)}"
            ),
        )

    # ── HA lifecycle ──────────────────────────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Called when entity is added; nothing extra needed (coordinator already connected)."""

    # ── State ─────────────────────────────────────────────────────────────

    @property
    def state(self) -> MediaPlayerState:
        if not self._coordinator.connected:
            return MediaPlayerState.OFF
        match self._coordinator.state:
            case "playing":
                return MediaPlayerState.PLAYING
            case "paused":
                return MediaPlayerState.PAUSED
            case _:
                return MediaPlayerState.IDLE

    @property
    def available(self) -> bool:
        return self._coordinator.connected

    # ── Volume (mapped to brightness 0–15 → 0.0–1.0) ─────────────────────

    @property
    def volume_level(self) -> float:
        return self._coordinator.brightness / BRIGHTNESS_MAX

    @property
    def is_volume_muted(self) -> bool:
        return self._coordinator.brightness == 0

    async def async_set_volume_level(self, volume: float) -> None:
        """Set brightness via volume slider (0.0–1.0 → 0–100%)."""
        await self._coordinator.async_set_brightness(int(volume * 100))
        self.async_write_ha_state()

    # ── Transport controls ────────────────────────────────────────────────

    async def async_media_play(self) -> None:
        """Resume / do nothing (display is passive)."""
        await self._coordinator.async_resume()
        self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        """Freeze the current frame."""
        await self._coordinator.async_pause()
        self.async_write_ha_state()

    async def async_media_stop(self) -> None:
        """Stop playback and clear the screen."""
        await self._coordinator.async_stop()
        self.async_write_ha_state()

    # ── play_media ────────────────────────────────────────────────────────

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs
    ) -> None:
        """Play media.

        Supported media_id formats:
          • Plain text → display_text with default colours and scrolling
          • 'text:My message' → same, explicit prefix
          • 'text:#FF0000:#000000:My red message' → colour:bg:text
        """
        if media_type not in (MediaType.MUSIC, MediaType.IMAGE, "text", "custom"):
            _LOGGER.warning("ZeDMD: unsupported media_type %r", media_type)
            return

        # Parse media_id
        color = "#FFFFFF"
        bg_color = "#000000"
        text = media_id

        if media_id.startswith("text:"):
            rest = media_id[5:]
            parts = rest.split(":", 2)
            if len(parts) == 3 and parts[0].startswith("#") and parts[1].startswith("#"):
                color, bg_color, text = parts
            else:
                text = rest

        await self._coordinator.async_display_text(
            text=text, color=color, bg_color=bg_color, scroll=True
        )
        self.async_write_ha_state()

    # ── Extra state attributes ────────────────────────────────────────────

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "host": self._entry.data[CONF_HOST],
            "stream_port": self._entry.data[CONF_STREAM_PORT],
            "firmware": self._coordinator.firmware_version,
            "brightness_raw": self._coordinator.brightness,
        }
