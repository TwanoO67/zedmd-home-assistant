"""ZeDMD media_player entity."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
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
    GIF_LIBRARY_SUBDIR,
)
from .coordinator import ZeDMDCoordinator

_LOGGER = logging.getLogger(__name__)

# Local GIF library: drop *.gif files in /config/www/zedmd_gifs/ and they
# show up automatically in the media browser.  HA serves /config/www/ at
# /local/, so the files are also accessible as thumbnails.
LIBRARY_PREFIX = "library/"

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
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

        Library (from media browser):
          • media_content_id: 'library/<filename>.gif'

        GIF (media_type=image or .gif URL):
          • media_content_type: image
          • media_content_id: https://example.com/anim.gif

        Text formats:
          • Plain text          → display_text with default colours and scrolling
          • 'text:My message'   → same, explicit prefix
          • 'text:#FF0000:#000000:My red message' → colour:bg:text
        """
        # ── Local GIF library ─────────────────────────────────────────────
        if media_id.startswith(LIBRARY_PREFIX):
            filename = media_id[len(LIBRARY_PREFIX):]
            full_path = self.hass.config.path(GIF_LIBRARY_SUBDIR, filename)
            await self._coordinator.async_play_gif_file(full_path)
            self.async_write_ha_state()
            return

        # ── GIF ───────────────────────────────────────────────────────────
        if media_type == MediaType.IMAGE or media_id.lower().endswith(".gif"):
            await self._coordinator.async_play_gif(media_id)
            self.async_write_ha_state()
            return

        # ── Text ──────────────────────────────────────────────────────────
        if media_type not in (MediaType.MUSIC, "text", "custom"):
            _LOGGER.warning("ZeDMD: unsupported media_type %r", media_type)
            return

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

    # ── Media browser (local GIF library) ─────────────────────────────────

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Expose *.gif files in /config/www/zedmd_gifs/ to the media browser."""
        gif_dir = Path(self.hass.config.path(GIF_LIBRARY_SUBDIR))

        def _scan() -> list[Path]:
            if not gif_dir.is_dir():
                return []
            return sorted(gif_dir.glob("*.gif"))

        gif_paths = await self.hass.async_add_executor_job(_scan)

        children = [
            BrowseMedia(
                title=path.stem,
                media_class=MediaClass.IMAGE,
                media_content_id=f"{LIBRARY_PREFIX}{path.name}",
                media_content_type="image/gif",
                can_play=True,
                can_expand=False,
                thumbnail=f"/local/zedmd_gifs/{path.name}",
            )
            for path in gif_paths
        ]

        return BrowseMedia(
            title="ZeDMD GIFs",
            media_class=MediaClass.DIRECTORY,
            media_content_id="",
            media_content_type="library",
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.IMAGE,
        )

    # ── Extra state attributes ────────────────────────────────────────────

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "host": self._entry.data[CONF_HOST],
            "stream_port": self._entry.data[CONF_STREAM_PORT],
            "firmware": self._coordinator.firmware_version,
            "brightness_raw": self._coordinator.brightness,
        }
