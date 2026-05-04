"""Event entity for Aqara Doorbell press detection via multicast."""

from __future__ import annotations

import asyncio
import logging
import socket
import struct

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import MULTICAST_GROUP, MULTICAST_PORT
from .entity import AqaraDoorbellEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Aqara Doorbell event entity."""
    data = entry.runtime_data
    async_add_entities([
        AqaraDoorbellEvent(camera_ip=data.camera_ip, unique_id=entry.unique_id)
    ])


class MulticastDoorbellProtocol(asyncio.DatagramProtocol):
    """UDP multicast protocol that filters packets by doorbell IP."""

    def __init__(self, doorbell_ip: str, on_press) -> None:
        self._doorbell_ip = doorbell_ip
        self._on_press = on_press
        self._packet_count = 0

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        _LOGGER.debug("Multicast protocol connection established")

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._packet_count += 1
        _LOGGER.debug(
            "Multicast packet #%d from %s:%s (%d bytes), filtering for %s",
            self._packet_count, addr[0], addr[1], len(data), self._doorbell_ip,
        )
        if addr[0] == self._doorbell_ip:
            _LOGGER.info("Doorbell press detected from %s (%d bytes)", addr[0], len(data))
            self._on_press()

    def error_received(self, exc: Exception) -> None:
        _LOGGER.error("Multicast protocol error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        if exc is None:
            _LOGGER.debug("Multicast protocol closed")
        else:
            _LOGGER.warning("Multicast protocol connection lost: %s", exc)


class AqaraDoorbellEvent(AqaraDoorbellEntity, EventEntity):
    """Event entity that fires on doorbell press."""

    _attr_name = "Doorbell"
    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = ["ring"]

    def __init__(self, camera_ip: str, unique_id: str) -> None:
        super().__init__(camera_ip, unique_id)
        self._attr_unique_id = f"{unique_id}_doorbell"
        self._transport: asyncio.DatagramTransport | None = None

    async def async_added_to_hass(self) -> None:
        """Start multicast listener when added to HA."""
        _LOGGER.debug(
            "Starting doorbell multicast listener for %s on %s:%s",
            self._camera_ip, MULTICAST_GROUP, MULTICAST_PORT,
        )
        await self._start_listener()

    async def async_will_remove_from_hass(self) -> None:
        """Stop multicast listener when removed from HA."""
        if self._transport:
            self._transport.close()
            self._transport = None

    async def _start_listener(self) -> None:
        """Create the multicast UDP listener."""
        loop = self.hass.loop

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            sock.bind(("", MULTICAST_PORT))

            mreq = struct.pack(
                "4s4s", socket.inet_aton(MULTICAST_GROUP), socket.inet_aton("0.0.0.0"),
            )
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.setblocking(False)

            transport, _ = await loop.create_datagram_endpoint(
                lambda: MulticastDoorbellProtocol(self._camera_ip, self._handle_press),
                sock=sock,
            )
            self._transport = transport
            _LOGGER.info(
                "Doorbell multicast listener active on %s:%s, filtering for IP %s",
                MULTICAST_GROUP, MULTICAST_PORT, self._camera_ip,
            )
        except OSError as err:
            _LOGGER.error(
                "Failed to start doorbell multicast listener on %s:%s: %s",
                MULTICAST_GROUP, MULTICAST_PORT, err,
            )
            return

    @callback
    def _handle_press(self) -> None:
        """Handle a doorbell press event."""
        _LOGGER.debug("Firing doorbell 'ring' event for %s", self._camera_ip)
        self._trigger_event("ring")
        self.async_write_ha_state()
