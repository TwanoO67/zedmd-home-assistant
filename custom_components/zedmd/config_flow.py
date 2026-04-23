"""Config flow for ZeDMD integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HOST,
    CONF_HTTP_PORT,
    CONF_NAME,
    CONF_STREAM_PORT,
    DEFAULT_HTTP_PORT,
    DEFAULT_NAME,
    DEFAULT_STREAM_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_STREAM_PORT, default=DEFAULT_STREAM_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Optional(CONF_HTTP_PORT, default=DEFAULT_HTTP_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
    }
)


async def _test_connection(host: str, stream_port: int) -> str | None:
    """Try to open a TCP connection. Return None on success, error key on failure."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, stream_port), timeout=5.0
        )
        writer.close()
        await writer.wait_closed()
        return None
    except asyncio.TimeoutError:
        return "cannot_connect"
    except OSError:
        return "cannot_connect"


class ZeDMDConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the ZeDMD config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            stream_port = user_input[CONF_STREAM_PORT]
            http_port = user_input[CONF_HTTP_PORT]
            name = user_input[CONF_NAME].strip() or DEFAULT_NAME

            # Avoid duplicate entries for the same host:port
            await self.async_set_unique_id(f"{host}:{stream_port}")
            self._abort_if_unique_id_configured()

            error = await _test_connection(host, stream_port)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_HOST: host,
                        CONF_STREAM_PORT: stream_port,
                        CONF_HTTP_PORT: http_port,
                        CONF_NAME: name,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
