"""Camera entity for Aqara Doorbell."""

from __future__ import annotations

import logging
from urllib.parse import quote

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import RTSP_PORT
from .entity import AqaraDoorbellEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Aqara Doorbell camera."""
    data = entry.runtime_data
    async_add_entities([
        AqaraDoorbellCamera(
            camera_ip=data.camera_ip,
            rtsp_username=data.rtsp_username,
            rtsp_password=data.rtsp_password,
            unique_id=entry.unique_id,
        )
    ])


class AqaraDoorbellCamera(AqaraDoorbellEntity, Camera):
    """Aqara Doorbell camera entity with RTSP streaming."""

    _attr_name = "Camera"
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self, camera_ip: str, rtsp_username: str, rtsp_password: str, unique_id: str,
    ) -> None:
        """Initialize the camera."""
        AqaraDoorbellEntity.__init__(self, camera_ip, unique_id)
        Camera.__init__(self)
        self._rtsp_username = rtsp_username
        self._rtsp_password = rtsp_password
        self._attr_unique_id = f"{unique_id}_camera"

    async def stream_source(self) -> str | None:
        """Return the RTSP stream URL."""
        user = quote(self._rtsp_username, safe="")
        pwd = quote(self._rtsp_password, safe="")
        return f"rtsp://{user}:{pwd}@{self._camera_ip}:{RTSP_PORT}/ch1"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return None -- no snapshot URL, stills only available during live stream."""
        return None
