"""Config flow for Aqara Doorbell integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import (
    CONF_CAMERA_IP, CONF_RTSP_PASSWORD, CONF_RTSP_USERNAME,
    CONTROL_PORT, DOMAIN, TCP_CONNECT_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CAMERA_IP): str,
        vol.Required(CONF_RTSP_USERNAME): str,
        vol.Required(CONF_RTSP_PASSWORD): str,
    }
)


async def validate_connection(ip: str) -> bool:
    """Validate camera is reachable by TCP-connecting to the control port."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, CONTROL_PORT),
            timeout=TCP_CONNECT_TIMEOUT,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


class AqaraDoorbellConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Aqara Doorbell."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            ip = user_input[CONF_CAMERA_IP]
            await self.async_set_unique_id(ip)
            self._abort_if_unique_id_configured()

            if await validate_connection(ip):
                return self.async_create_entry(
                    title=f"Aqara Doorbell ({ip})", data=user_input,
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user", data_schema=USER_DATA_SCHEMA, errors=errors,
        )
