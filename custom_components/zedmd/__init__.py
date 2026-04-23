"""ZeDMD Home Assistant integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_HOST,
    CONF_HTTP_PORT,
    CONF_STREAM_PORT,
    DEFAULT_HTTP_PORT,
    DOMAIN,
    SERVICE_CLEAR_SCREEN,
    SERVICE_DISPLAY_TEXT,
    SERVICE_SET_BRIGHTNESS,
    SERVICE_TEST_PATTERN,
)
from .coordinator import ZeDMDCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]


# ── Service schemas ───────────────────────────────────────────────────────────

SERVICE_DISPLAY_TEXT_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
        vol.Required("text"): cv.string,
        vol.Optional("color", default="#FFFFFF"): cv.string,
        vol.Optional("bg_color", default="#000000"): cv.string,
        vol.Optional("scroll", default=True): cv.boolean,
        vol.Optional("scroll_speed", default=2): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=20)
        ),
    }
)

SERVICE_BRIGHTNESS_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
        vol.Required("brightness"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
    }
)

SERVICE_CLEAR_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
    }
)


# ── Integration setup ─────────────────────────────────────────────────────────


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ZeDMD from a config entry."""
    coordinator = ZeDMDCoordinator(
        hass=hass,
        host=entry.data[CONF_HOST],
        stream_port=entry.data[CONF_STREAM_PORT],
        http_port=entry.data.get(CONF_HTTP_PORT, DEFAULT_HTTP_PORT),
    )

    connected = await coordinator.async_connect()
    if not connected:
        _LOGGER.warning(
            "ZeDMD: initial connection to %s:%s failed – "
            "the integration will retry when HA reloads.",
            entry.data[CONF_HOST],
            entry.data[CONF_STREAM_PORT],
        )
        # We still store the coordinator so the entity can surface 'unavailable'.

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ── Register domain-level services (once, idempotent) ─────────────────
    if not hass.services.has_service(DOMAIN, SERVICE_DISPLAY_TEXT):

        def _get_coordinator(call: ServiceCall) -> list[ZeDMDCoordinator]:
            """Return coordinators referenced by the service call entity_ids."""
            entity_ids = call.data.get("entity_id")
            coords: list[ZeDMDCoordinator] = []
            for eid, coord in hass.data[DOMAIN].items():
                # If entity_ids filter is absent, target all entries.
                if entity_ids is None or any(
                    eid in ei for ei in entity_ids
                ):
                    coords.append(coord)
            # Fallback: return all if filtering matched nothing
            return coords or list(hass.data[DOMAIN].values())

        async def handle_display_text(call: ServiceCall) -> None:
            for coord in _get_coordinator(call):
                await coord.async_display_text(
                    text=call.data["text"],
                    color=call.data.get("color", "#FFFFFF"),
                    bg_color=call.data.get("bg_color", "#000000"),
                    scroll=call.data.get("scroll", True),
                    scroll_speed=call.data.get("scroll_speed", 2),
                )

        async def handle_set_brightness(call: ServiceCall) -> None:
            for coord in _get_coordinator(call):
                await coord.async_set_brightness(call.data["brightness"])

        async def handle_clear_screen(call: ServiceCall) -> None:
            for coord in _get_coordinator(call):
                await coord.async_stop()

        async def handle_test_pattern(call: ServiceCall) -> None:
            color = call.data.get("color", "red")
            presets = {
                "red":   (255, 0,   0),
                "green": (0,   255, 0),
                "blue":  (0,   0,   255),
                "white": (255, 255, 255),
            }
            r, g, b = presets.get(color, (255, 0, 0))
            for coord in _get_coordinator(call):
                await coord.async_send_test_pattern(r, g, b)

        hass.services.async_register(
            DOMAIN,
            SERVICE_DISPLAY_TEXT,
            handle_display_text,
            schema=SERVICE_DISPLAY_TEXT_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_BRIGHTNESS,
            handle_set_brightness,
            schema=SERVICE_BRIGHTNESS_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_TEST_PATTERN,
            handle_test_pattern,
            schema=vol.Schema({
                vol.Optional("entity_id"): vol.Any(str, list),
                vol.Optional("color", default="red"): vol.In(["red", "green", "blue", "white"]),
            }),
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_SCREEN,
            handle_clear_screen,
            schema=SERVICE_CLEAR_SCHEMA,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a ZeDMD config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: ZeDMDCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_disconnect()

        # Remove services when last entry is removed
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_DISPLAY_TEXT)
            hass.services.async_remove(DOMAIN, SERVICE_SET_BRIGHTNESS)
            hass.services.async_remove(DOMAIN, SERVICE_CLEAR_SCREEN)
            hass.services.async_remove(DOMAIN, SERVICE_TEST_PATTERN)

    return unload_ok
