"""Base entity for Aqara Doorbell integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN


class AqaraDoorbellEntity(Entity):
    """Base class for Aqara Doorbell entities."""

    _attr_has_entity_name = True

    def __init__(self, camera_ip: str, unique_id: str) -> None:
        """Initialize with shared device info."""
        self._camera_ip = camera_ip
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            manufacturer="Aqara",
            model="G400 Doorbell",
            name=f"Aqara Doorbell ({camera_ip})",
        )
