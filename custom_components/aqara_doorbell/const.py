"""Constants for the Aqara Doorbell integration."""

from homeassistant.const import Platform

DOMAIN = "aqara_doorbell"

# Config keys
CONF_CAMERA_IP = "camera_ip"
CONF_RTSP_USERNAME = "rtsp_username"
CONF_RTSP_PASSWORD = "rtsp_password"

# Network ports
RTSP_PORT = 8554
CONTROL_PORT = 54324
AUDIO_PORT = 54323
MULTICAST_GROUP = "230.0.0.1"
MULTICAST_PORT = 10008

# Protocol constants
MAGIC = b"\xFE\xEF"
TYPE_START_VOICE = 0
TYPE_STOP_VOICE = 1
TYPE_ACK = 2
TYPE_HEARTBEAT = 3
RTP_PAYLOAD_TYPE = 97  # Dynamic PT for AAC

# Timing
HEARTBEAT_INTERVAL = 5.0  # seconds
TCP_CONNECT_TIMEOUT = 3.0  # seconds

# Platforms
PLATFORMS: list[Platform] = [Platform.CAMERA, Platform.EVENT]
