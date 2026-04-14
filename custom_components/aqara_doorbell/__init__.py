"""Aqara Doorbell integration."""

from __future__ import annotations

import asyncio
import logging
import pathlib
from dataclasses import dataclass
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import CONF_CAMERA_IP, CONF_RTSP_PASSWORD, CONF_RTSP_USERNAME, DOMAIN, PLATFORMS
from . import go2rtc as go2rtc_mod
from .protocol import extract_adts_frames
from .talk import AqaraLanTalkClient

_LOGGER = logging.getLogger(__name__)

type AqaraDoorbellConfigEntry = ConfigEntry[AqaraDoorbellRuntimeData]

TALK_AUDIO_SCHEMA = vol.Schema({
    vol.Required("file_path"): str,
})


@dataclass
class AqaraDoorbellRuntimeData:
    """Runtime data for an Aqara Doorbell config entry."""

    camera_ip: str
    rtsp_username: str
    rtsp_password: str
    talk_client: AqaraLanTalkClient
    go2rtc_stream_name: str | None = None


def _get_all_runtime_data(hass: HomeAssistant) -> list[AqaraDoorbellRuntimeData]:
    """Get all active runtime data."""
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if hasattr(entry, "runtime_data")
    ]


async def async_setup_entry(
    hass: HomeAssistant, entry: AqaraDoorbellConfigEntry
) -> bool:
    """Set up Aqara Doorbell from a config entry."""
    talk_client = AqaraLanTalkClient(camera_ip=entry.data[CONF_CAMERA_IP])

    entry.runtime_data = AqaraDoorbellRuntimeData(
        camera_ip=entry.data[CONF_CAMERA_IP],
        rtsp_username=entry.data[CONF_RTSP_USERNAME],
        rtsp_password=entry.data[CONF_RTSP_PASSWORD],
        talk_client=talk_client,
    )

    # Register services once (first entry)
    if not hass.services.has_service(DOMAIN, "talk_start"):
        async def handle_talk_start(call: ServiceCall) -> None:
            for rt in _get_all_runtime_data(hass):
                if not rt.talk_client.is_connected:
                    await rt.talk_client.connect()

        async def handle_talk_stop(call: ServiceCall) -> None:
            for rt in _get_all_runtime_data(hass):
                if rt.talk_client.is_connected:
                    await rt.talk_client.disconnect()

        async def handle_talk_audio_file(call: ServiceCall) -> None:
            file_path = call.data["file_path"]
            if not hass.config.is_allowed_path(file_path):
                raise ServiceValidationError(
                    f"Path not allowed: {file_path}. Check allowlist_external_dirs."
                )
            clients = _get_all_runtime_data(hass)
            if not clients:
                raise HomeAssistantError("No Aqara Doorbell configured")
            rt = clients[0]
            if not rt.talk_client.is_connected:
                if not await rt.talk_client.connect():
                    raise HomeAssistantError(
                        "Failed to connect to doorbell — the voice channel may "
                        "already be in use by browser two-way audio or another session"
                    )
            await _send_aac_file(hass, rt.talk_client, file_path)

        hass.services.async_register(DOMAIN, "talk_start", handle_talk_start)
        hass.services.async_register(DOMAIN, "talk_stop", handle_talk_stop)
        hass.services.async_register(
            DOMAIN, "talk_audio_file", handle_talk_audio_file, schema=TALK_AUDIO_SCHEMA,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Write go2rtc stream config with backchannel (best-effort, file-based)
    await _setup_go2rtc_config(hass, entry)

    return True


async def _setup_go2rtc_config(
    hass: HomeAssistant, entry: AqaraDoorbellConfigEntry
) -> None:
    """Write a go2rtc stream to go2rtc.yaml with RTSP + exec backchannel.

    go2rtc blocks exec sources via REST API for security, so we write
    directly to the config file. Uses a dedicated stream name to avoid
    conflicting with HA's built-in go2rtc integration.
    """
    data = entry.runtime_data
    stream_name = f"aqara_doorbell_{data.camera_ip.replace('.', '_')}"

    rtsp_source = go2rtc_mod.build_rtsp_source(
        data.camera_ip, data.rtsp_username, data.rtsp_password
    )
    exec_source = go2rtc_mod.build_exec_source(hass.config.config_dir, data.camera_ip)

    entry.runtime_data.go2rtc_stream_name = stream_name

    # ffmpeg source references stream by name (reuses the RTSP connection)
    # audio=copy preserves AAC for MSE mode, audio=opus adds WebRTC compatibility
    ffmpeg_source = f"ffmpeg:{stream_name}#audio=opus#audio=copy"

    await hass.async_add_executor_job(
        go2rtc_mod.register_stream,
        hass.config.config_dir,
        stream_name,
        [rtsp_source, ffmpeg_source, exec_source],
    )


async def async_unload_entry(
    hass: HomeAssistant, entry: AqaraDoorbellConfigEntry
) -> bool:
    """Unload an Aqara Doorbell config entry."""
    await entry.runtime_data.talk_client.disconnect()

    # Remove go2rtc stream from config (best-effort)
    if entry.runtime_data.go2rtc_stream_name:
        go2rtc_mod.remove_stream(hass.config.config_dir, entry.runtime_data.go2rtc_stream_name)

    result = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Remove services when last entry is unloaded
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    if not remaining:
        hass.services.async_remove(DOMAIN, "talk_start")
        hass.services.async_remove(DOMAIN, "talk_stop")
        hass.services.async_remove(DOMAIN, "talk_audio_file")

    return result


async def _send_aac_file(
    hass: HomeAssistant, client: AqaraLanTalkClient, file_path: str
) -> None:
    """Send an AAC-ADTS file through the talk client."""
    path = pathlib.Path(file_path)
    audio_data = await hass.async_add_executor_job(path.read_bytes)

    frames = extract_adts_frames(audio_data)
    ts_samples = 0
    frame_duration_samples = 1024  # AAC frame size at 16kHz

    for frame in frames:
        if not client.is_connected:
            break
        client.send_audio_frame(frame, ts_samples)
        ts_samples += frame_duration_samples
        await asyncio.sleep(0.064)  # ~64ms pacing per frame
