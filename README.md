# Aqara Doorbell - Home Assistant Integration

**This is **NOT** a complete working production ready integration for the Aqara G400 Doorbell, it is **only** a **proof of concept** designed to test if fully local **two-way audio** independent of any hub/app/cloud connection is possible with the device. You will **not** get a fully functional stable doorbell with this integration. Please do not use this integration expecting a properly functioning G400 doorbell, it is recommended to use the doorbell in Home Assistant via the official HomeKit integration.**

Proof of concept for local-only two-way audio for the **Aqara G400 Video Doorbell** (`lumi.camera.agl013`). No cloud, no hub, no proprietary SDK required.

Written for and tested on the G400 Doorbell, but user feedback states it works with other Aqara doorbell models such as the G410.

Protocol reverse-engineered from the Aqara Android app.

Use [Aqara Camera 2-Way Audio integration](https://github.com/absent42/Aqara-Camera-2-Way-Audio) for better support of any Aqara camera's video/audio features. 

## Features

- **Video streaming** via RTSP (H.264)
- **Two-way audio** via go2rtc backchannel — speak through the doorbell from the HA dashboard
- **Audio file playback** — play pre-recorded messages through the doorbell speaker
- **Fully local** — all communication stays on your LAN

## Requirements

- Aqara Video Doorbell on the same LAN as Home Assistant
- RTSP credentials configured in the Aqara Home app (Device > More Settings > RTSP LAN Preview)
- [AlexxIT's WebRTC](https://github.com/AlexxIT/WebRTC) custom component (for two-way audio dashboard card)
- Home Assistant 2026.2+ with go2rtc

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| Camera | `camera` | RTSP video stream from the doorbell |

## Two-Way Audio

### How it works

The Aqara G400 uses a proprietary LAN protocol for two-way audio, separate from its RTSP video stream:

```
Browser microphone
  --> WebRTC (Opus/48kHz)
  --> go2rtc (transcodes to G.711 A-law / 8kHz)
  --> bridge.py (transcodes to AAC-LC / 16kHz via ffmpeg)
  --> RTP/UDP port 54323 --> doorbell speaker

Doorbell microphone
  --> RTSP (AAC / 16kHz) port 8554
  --> go2rtc (transcodes to Opus/48kHz via ffmpeg)
  --> WebRTC --> browser speaker
```

The integration automatically configures go2rtc with a stream containing three sources:

1. **RTSP** — video + audio from the camera
2. **ffmpeg** — transcodes camera AAC audio to Opus for WebRTC
3. **exec bridge** — routes browser microphone audio to the doorbell speaker

### Dashboard card

Add a [WebRTC Camera](https://github.com/AlexxIT/WebRTC) card to your dashboard:

```yaml
type: custom:webrtc-camera
streams:
  - url: aqara_doorbell_DOORBELL_IP
    mode: webrtc
    media: video,audio,microphone
style: >
  video {aspect-ratio: 3/4; object-fit: fill;}    
```

Replace `DOORBELL_IP` with your doorbell's IP address (dots replaced with underscores, e.g. `aqara_doorbell_192_168_1_100`).

**Multi-stream card** example with a toggle between listening and speaking:

```yaml
type: custom:webrtc-camera
ui: true
streams:
  - url: aqara_doorbell_DOORBELL_IP
    mode: webrtc
    media: video,audio
    name: Listening
  - url: aqara_doorbell_DOORBELL_IP
    mode: webrtc
    media: video,audio,microphone
    name: Speaking
style: >
  video {aspect-ratio: 3/4; object-fit: fill;} .volume { padding: 4px 6px;
  display: flex } .stream { padding: 4px 8px; flex: 1 0 0; } .space, .header,
  .fullscreen, .screenshot, .pictureinpicture { display: none }
```

> **Note:** The card must use `url:` (go2rtc stream name), not `entity:` (HA entity ID). The go2rtc stream name is `aqara_doorbell_{ip_with_underscores}`.

> **Note:** The browser must be served over HTTPS for microphone access to work. The first connection will prompt for microphone permission.

### Audio file playback

Play pre-recorded audio files through the doorbell speaker using the `talk_audio_file` service:

```yaml
# Example automation: play a greeting through the doorbell speaker.
# This integration does not provide a ring event — use any trigger you like.
# For a local doorbell-press trigger, pair the doorbell with Home Assistant's
# official HomeKit integration and use its doorbell event entity (recommended).
automation:
  trigger:
    platform: state
    entity_id: event.your_homekit_doorbell  # from the HomeKit integration
  action:
    service: aqara_doorbell.talk_audio_file
    data:
      file_path: /media/doorbell_greeting.aac
```

Audio files must be in **AAC-ADTS format** (16kHz mono). Convert with ffmpeg:

```bash
ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a aac -b:a 32k -f adts output.aac
```

The file path must be in HA's `allowlist_external_dirs` configuration.

> **Note:** Talk services and browser two-way audio are mutually exclusive. The doorbell supports one voice session at a time.


## Services

| Service | Description |
|---------|-------------|
| `aqara_doorbell.talk_start` | Open a voice session with the doorbell |
| `aqara_doorbell.talk_stop` | Close the active voice session |
| `aqara_doorbell.talk_audio_file` | Play an AAC audio file through the doorbell speaker |

## Protocol Details

The Aqara G400 LAN talk protocol was reverse-engineered from the Aqara Android app (`com.lumi.module.rtsp`). It uses three independent network channels:

| Channel | Protocol | Port | Purpose |
|---------|----------|------|---------|
| Video/Audio stream | RTSP over TCP | 8554 | H.264 video + AAC audio from camera |
| Voice control | TCP | 54324 | Session management (start/stop/heartbeat) |
| Voice audio | UDP (RTP) | 54323 | AAC-LC ADTS frames to doorbell speaker |

### Control channel (TCP 54324)

Uses a custom `LmLocalPacket` binary format:

```
Magic (0xFEEF) | Type (1B) | Payload Length (2B) | Payload (N) | CRC-16 (2B)
```

- **START_VOICE** (type 0): Opens session, payload is epoch milliseconds
- **STOP_VOICE** (type 1): Closes session
- **ACK** (type 2): Response from camera (0 = success)
- **HEARTBEAT** (type 3): Sent every 5 seconds to keep session alive

CRC is CRC-16/KERMIT (polynomial 0x8408, init 0xFFFF, final XOR 0xFFFF).

### Audio channel (UDP 54323)

Standard RTP (RFC 3550) with payload type 97 (dynamic AAC):

- **Codec:** AAC-LC ADTS, 16kHz, mono, 32kbps
- **Frame size:** 1024 samples (64ms per frame)
- **RTP timestamp clock:** 16kHz

## Tested Hardware

- **Aqara G400 Video Doorbell** (model `lumi.camera.agl013` / ZNKSML11LM / AC035)
- Firmware: 4.5.20_0022/4.5.20_0026
- go2rtc: v1.9.14 (HA bundled, backchannel uses PCMA/8kHz)

## Known Limitations

- Two-way audio requires [AlexxIT's WebRTC](https://github.com/AlexxIT/WebRTC) custom component
- The dashboard card must use `url:` (go2rtc stream name), not `entity:` (HA entity ID)
- go2rtc restart required after initial installation (stream config is written to `go2rtc.yaml`)
- Backchannel audio quality is limited to G.711 A-law at 8kHz (go2rtc limitation)
- Doorbell press (ring) detection is not provided by this integration; pair the doorbell with Home Assistant's official HomeKit integration for local ring events
- The doorbell supports one voice session at a time
- Only tested with the Aqara G400 model
