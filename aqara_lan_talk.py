"""
Aqara Camera LAN Talk - Proof of Concept

2-way audio and doorbell event detection for Aqara cameras over LAN.
No cloud, no hub, no proprietary SDK required.

Protocol reverse-engineered from the Aqara Android app.

Proven working with Aqara G400 Doorbell (lumi.camera.agl013).

Architecture:
  Video (in):  RTSP   rtsp://user:pass@cameraip:8554/ch1
  Audio (out): TCP 54324 (control) + UDP 54323 (AAC-LC RTP)
  Doorbell:    Multicast 230.0.0.1:10008

Audio format: AAC-LC ADTS, 16kHz mono, 32kbps
  Convert with: ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a aac -b:a 32k -f adts output.aac

Usage:
  python aqara_lan_talk.py <camera_ip> --test-connect
  python aqara_lan_talk.py <camera_ip> --audio-file output.aac
  python aqara_lan_talk.py <camera_ip> --doorbell-listen
"""

import socket
import struct
import time
import threading
import random
import argparse
import sys
import os


# =============================================================================
# CRC-16/KERMIT
# =============================================================================

CRC16_TABLE = [
    0x0000, 0x1189, 0x2312, 0x329B, 0x4624, 0x57AD, 0x6536, 0x74BF,
    0x8C48, 0x9DC1, 0xAF5A, 0xBED3, 0xCA6C, 0xDBE5, 0xE97E, 0xF8F7,
    0x1081, 0x0108, 0x3393, 0x221A, 0x56A5, 0x472C, 0x75B7, 0x643E,
    0x9CC9, 0x8D40, 0xBFDB, 0xAE52, 0xDAED, 0xCB64, 0xF9FF, 0xE876,
    0x2102, 0x308B, 0x0210, 0x1399, 0x6726, 0x76AF, 0x4434, 0x55BD,
    0xAD4A, 0xBCC3, 0x8E58, 0x9FD1, 0xEB6E, 0xFAE7, 0xC87C, 0xD9F5,
    0x3183, 0x200A, 0x1291, 0x0318, 0x77A7, 0x662E, 0x54B5, 0x453C,
    0xBDCB, 0xAC42, 0x9ED9, 0x8F50, 0xFBEF, 0xEA66, 0xD8FD, 0xC974,
    0x4204, 0x538D, 0x6116, 0x709F, 0x0420, 0x15A9, 0x2732, 0x36BB,
    0xCE4C, 0xDFC5, 0xED5E, 0xFCD7, 0x8868, 0x99E1, 0xAB7A, 0xBAF3,
    0x5285, 0x430C, 0x7197, 0x601E, 0x14A1, 0x0528, 0x37B3, 0x263A,
    0xDECD, 0xCF44, 0xFDDF, 0xEC56, 0x98E9, 0x8960, 0xBBFB, 0xAA72,
    0x6306, 0x728F, 0x4014, 0x519D, 0x2522, 0x34AB, 0x0630, 0x17B9,
    0xEF4E, 0xFEC7, 0xCC5C, 0xDDD5, 0xA96A, 0xB8E3, 0x8A78, 0x9BF1,
    0x7387, 0x620E, 0x5095, 0x411C, 0x35A3, 0x242A, 0x16B1, 0x0738,
    0xFFCF, 0xEE46, 0xDCDD, 0xCD54, 0xB9EB, 0xA862, 0x9AF9, 0x8B70,
    0x8408, 0x9581, 0xA71A, 0xB693, 0xC22C, 0xD3A5, 0xE13E, 0xF0B7,
    0x0840, 0x19C9, 0x2B52, 0x3ADB, 0x4E64, 0x5FED, 0x6D76, 0x7CFF,
    0x9489, 0x8500, 0xB79B, 0xA612, 0xD2AD, 0xC324, 0xF1BF, 0xE036,
    0x18C1, 0x0948, 0x3BD3, 0x2A5A, 0x5EE5, 0x4F6C, 0x7DF7, 0x6C7E,
    0xA50A, 0xB483, 0x8618, 0x9791, 0xE32E, 0xF2A7, 0xC03C, 0xD1B5,
    0x2942, 0x38CB, 0x0A50, 0x1BD9, 0x6F66, 0x7EEF, 0x4C74, 0x5DFD,
    0xB58B, 0xA402, 0x9699, 0x8710, 0xF3AF, 0xE226, 0xD0BD, 0xC134,
    0x39C3, 0x284A, 0x1AD1, 0x0B58, 0x7FE7, 0x6E6E, 0x5CF5, 0x4D7C,
    0xC60C, 0xD785, 0xE51E, 0xF497, 0x8028, 0x91A1, 0xA33A, 0xB2B3,
    0x4A44, 0x5BCD, 0x6956, 0x78DF, 0x0C60, 0x1DE9, 0x2F72, 0x3EFB,
    0xD68D, 0xC704, 0xF59F, 0xE416, 0x90A9, 0x8120, 0xB3BB, 0xA232,
    0x5AC5, 0x4B4C, 0x79D7, 0x685E, 0x1CE1, 0x0D68, 0x3FF3, 0x2E7A,
    0xE70E, 0xF687, 0xC41C, 0xD595, 0xA12A, 0xB0A3, 0x8238, 0x93B1,
    0x6B46, 0x7ACF, 0x4854, 0x59DD, 0x2D62, 0x3CEB, 0x0E70, 0x1FF9,
    0xF78F, 0xE606, 0xD49D, 0xC514, 0xB1AB, 0xA022, 0x92B9, 0x8330,
    0x7BC7, 0x6A4E, 0x58D5, 0x495C, 0x3DE3, 0x2C6A, 0x1EF1, 0x0F78,
]


def crc16_kermit(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc = CRC16_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return (~crc) & 0xFFFF


# =============================================================================
# LmLocalPacket — TCP control channel (port 54324)
# =============================================================================

TYPE_START_VOICE = 0
TYPE_STOP_VOICE = 1
TYPE_ACK = 2
TYPE_HEARTBEAT = 3
MAGIC = b'\xFE\xEF'
TYPE_NAMES = {0: "START_VOICE", 1: "STOP_VOICE", 2: "ACK", 3: "HEARTBEAT"}


def build_packet(pkt_type: int, payload_value: int) -> bytes:
    if pkt_type == TYPE_ACK:
        payload_bytes = struct.pack('>B', payload_value & 0xFF)
    else:
        payload_bytes = struct.pack('>Q', payload_value)

    header = MAGIC + struct.pack('>B', pkt_type) + struct.pack('>H', len(payload_bytes))
    crc_data = header[2:] + payload_bytes
    crc = crc16_kermit(crc_data)
    return header + payload_bytes + struct.pack('>H', crc)


def parse_packet(data: bytes) -> dict | None:
    if len(data) < 8 or data[0:2] != MAGIC:
        return None
    pkt_type = data[2]
    if pkt_type > 3:
        return None
    payload_len = struct.unpack('>H', data[3:5])[0]
    if len(data) < 5 + payload_len + 2:
        return None

    crc_data = data[2:5 + payload_len]
    expected_crc = struct.unpack('>H', data[5 + payload_len:7 + payload_len])[0]
    if crc16_kermit(crc_data) != expected_crc:
        return None

    payload_bytes = data[5:5 + payload_len]
    value = payload_bytes[0] if pkt_type == TYPE_ACK else int.from_bytes(payload_bytes, 'big')
    return {"type": pkt_type, "type_name": TYPE_NAMES.get(pkt_type, "?"), "value": value}


# =============================================================================
# RTP header — UDP audio channel (port 54323)
# =============================================================================

def build_rtp_header(payload_type: int, timestamp: int, ssrc: int, seq_num: int) -> bytes:
    return struct.pack('>BBHII', 0x80, payload_type, seq_num & 0xFFFF,
                       timestamp & 0xFFFFFFFF, ssrc & 0xFFFFFFFF)


# =============================================================================
# AqaraLanTalk — 2-way audio client
# =============================================================================

class AqaraLanTalk:
    CONTROL_PORT = 54324
    AUDIO_PORT = 54323
    RTP_PT = 97  # AAC dynamic payload type
    HEARTBEAT_INTERVAL = 5.0

    def __init__(self, camera_ip: str):
        self.camera_ip = camera_ip
        self.session_ts = int(time.time() * 1000)
        self.tcp_sock: socket.socket | None = None
        self.udp_sock: socket.socket | None = None
        self.ssrc = random.randint(1, 2147483647)
        self.seq_num = 0
        self._heartbeat_thread: threading.Thread | None = None
        self._running = False

    def connect(self) -> bool:
        try:
            self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.tcp_sock.settimeout(3.0)
            print(f"Connecting to {self.camera_ip}:{self.CONTROL_PORT}...")
            self.tcp_sock.connect((self.camera_ip, self.CONTROL_PORT))

            self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            pkt = build_packet(TYPE_START_VOICE, self.session_ts)
            print(f"  START_VOICE (session={self.session_ts})")
            self.tcp_sock.sendall(pkt)

            resp = self.tcp_sock.recv(1024)
            if not resp:
                print("  No response")
                return False

            parsed = parse_packet(resp)
            if not parsed or parsed["type"] != TYPE_ACK or parsed["value"] != 0:
                print(f"  Rejected: {parsed}")
                return False

            print("  Voice session active")
            self._running = True
            self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self._heartbeat_thread.start()
            return True

        except Exception as e:
            print(f"  Failed: {e}")
            self.disconnect()
            return False

    def send_audio(self, aac_frame: bytes, timestamp_ms: int = 0):
        if not self.udp_sock:
            return
        rtp_ts = timestamp_ms * 16  # 16kHz clock
        header = build_rtp_header(self.RTP_PT, rtp_ts, self.ssrc, self.seq_num)
        self.seq_num += 1
        self.udp_sock.sendto(header + aac_frame, (self.camera_ip, self.AUDIO_PORT))

    def stop(self):
        self._running = False
        if self.tcp_sock:
            try:
                self.tcp_sock.sendall(build_packet(TYPE_STOP_VOICE, self.session_ts))
                resp = self.tcp_sock.recv(1024)
                if resp:
                    parsed = parse_packet(resp)
                    print(f"  STOP_VOICE: {parsed}")
            except Exception:
                pass
        self.disconnect()

    def disconnect(self):
        self._running = False
        for sock in [self.tcp_sock, self.udp_sock]:
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
        self.tcp_sock = None
        self.udp_sock = None

    def _heartbeat_loop(self):
        failures = 0
        while self._running:
            time.sleep(self.HEARTBEAT_INTERVAL)
            if not self._running:
                break
            try:
                self.tcp_sock.sendall(build_packet(TYPE_HEARTBEAT, self.session_ts))
                resp = self.tcp_sock.recv(1024)
                parsed = parse_packet(resp) if resp else None
                if parsed and parsed["type"] == TYPE_ACK and parsed["value"] == 0:
                    failures = 0
                    continue
                failures += 1
            except Exception:
                failures += 1
            if failures > 5:
                print("  Voice channel dead")
                self._running = False


# =============================================================================
# DoorbellListener — multicast event detection
# =============================================================================

class DoorbellListener:
    MULTICAST_GROUP = "230.0.0.1"
    MULTICAST_PORT = 10008

    def __init__(self, doorbell_ip: str, callback=None):
        self.doorbell_ip = doorbell_ip
        self.callback = callback or (lambda ip, data: print(f"[DOORBELL] {ip} ({len(data)} bytes)"))

    def listen(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', self.MULTICAST_PORT))
        mreq = struct.pack("4s4s", socket.inet_aton(self.MULTICAST_GROUP), socket.inet_aton("0.0.0.0"))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        print(f"Listening for doorbell events from {self.doorbell_ip}...")
        while True:
            data, addr = sock.recvfrom(4096)
            if addr[0] == self.doorbell_ip:
                self.callback(addr[0], data)


# =============================================================================
# AAC-ADTS streaming
# =============================================================================

def send_aac_file(client: AqaraLanTalk, filepath: str):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    with open(filepath, 'rb') as f:
        audio_data = f.read()

    print(f"Sending {len(audio_data)} bytes of AAC...")
    offset = 0
    ts_ms = 0
    frame_count = 0
    frame_duration_ms = 64  # 1024 samples / 16kHz ≈ 64ms per AAC frame

    while offset < len(audio_data) - 7 and client._running:
        # ADTS sync word 0xFFF
        if audio_data[offset] != 0xFF or (audio_data[offset + 1] & 0xF0) != 0xF0:
            offset += 1
            continue

        frame_len = ((audio_data[offset + 3] & 0x03) << 11 |
                     audio_data[offset + 4] << 3 |
                     (audio_data[offset + 5] >> 5))

        if frame_len < 7 or offset + frame_len > len(audio_data):
            break

        client.send_audio(audio_data[offset:offset + frame_len], ts_ms)
        frame_count += 1
        offset += frame_len
        ts_ms += frame_duration_ms
        time.sleep(frame_duration_ms / 1000.0)

    print(f"Sent {frame_count} frames ({ts_ms / 1000.0:.1f}s)")


# =============================================================================
# Live microphone streaming (PCM capture → AAC encode → RTP send)
# =============================================================================

def _get_aac_encoder():
    """Return an AAC encoder function using PyAV or ffmpeg subprocess.

    Returns (init_fn, encode_fn, close_fn) or None if neither is available.
    PyAV is preferred (lower latency). ffmpeg subprocess is the fallback.
    """
    # Try PyAV first
    try:
        import importlib.util
        if importlib.util.find_spec("av"):
            return _pyav_encoder()
    except Exception:
        pass

    # Try ffmpeg subprocess
    import subprocess
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return _ffmpeg_encoder()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def _pyav_encoder():
    """AAC encoder using PyAV (pip install av)."""
    import av
    import io

    state = {}

    def init():
        output = av.open(io.BytesIO(), mode='w', format='adts')
        stream = output.add_stream('aac', rate=16000, layout='mono')
        stream.bit_rate = 32000
        state['output'] = output
        state['stream'] = stream
        state['frame_pts'] = 0

    def encode(pcm_bytes: bytes) -> list[bytes]:
        """Encode 16-bit PCM to AAC-ADTS frames. Returns list of ADTS frame bytes."""
        import numpy as np
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format='s16', layout='mono')
        frame.sample_rate = 16000
        frame.pts = state['frame_pts']
        state['frame_pts'] += len(samples)

        adts_frames = []
        for packet in state['stream'].encode(frame):
            adts_frames.append(bytes(packet))
        return adts_frames

    def close():
        # Flush encoder
        try:
            for _ in state['stream'].encode(None):
                pass
            state['output'].close()
        except Exception:
            pass

    return init, encode, close


def _ffmpeg_encoder():
    """AAC encoder using ffmpeg subprocess pipe."""
    import subprocess

    state = {}

    def init():
        proc = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "pipe:0",
             "-c:a", "aac", "-b:a", "32k", "-f", "adts", "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        state['proc'] = proc

    def encode(pcm_bytes: bytes) -> list[bytes]:
        """Write PCM to ffmpeg stdin, read AAC-ADTS from stdout."""
        proc = state['proc']
        try:
            proc.stdin.write(pcm_bytes)
            proc.stdin.flush()
        except BrokenPipeError:
            return []

        # Non-blocking read of available output
        import select
        adts_frames = []
        while select.select([proc.stdout], [], [], 0.001)[0]:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            adts_frames.extend(_extract_adts_frames(chunk))
        return adts_frames

    def close():
        proc = state.get('proc')
        if proc:
            try:
                proc.stdin.close()
                proc.wait(timeout=2)
            except Exception:
                proc.kill()

    return init, encode, close


def _extract_adts_frames(data: bytes) -> list[bytes]:
    """Extract individual ADTS frames from a byte buffer."""
    frames = []
    offset = 0
    while offset < len(data) - 7:
        if data[offset] != 0xFF or (data[offset + 1] & 0xF0) != 0xF0:
            offset += 1
            continue
        frame_len = ((data[offset + 3] & 0x03) << 11 |
                     data[offset + 4] << 3 |
                     (data[offset + 5] >> 5))
        if frame_len < 7 or offset + frame_len > len(data):
            break
        frames.append(data[offset:offset + frame_len])
        offset += frame_len
    return frames


def stream_microphone(client: AqaraLanTalk):
    """Stream live microphone audio to the camera.

    Captures PCM from microphone, encodes to AAC-LC in real time,
    and sends to camera via UDP RTP.

    Requires: pyaudio (pip install pyaudio)
    Plus one of: av (pip install av) OR ffmpeg in PATH
    """
    try:
        import pyaudio
    except ImportError:
        print("pyaudio required: pip install pyaudio")
        return

    encoder = _get_aac_encoder()
    if encoder is None:
        print("AAC encoder required. Install one of:")
        print("  pip install av          (PyAV — preferred, lower latency)")
        print("  or add ffmpeg to PATH   (ffmpeg subprocess — fallback)")
        return

    init_enc, encode_fn, close_enc = encoder

    RATE = 16000
    CHANNELS = 1
    CHUNK_SAMPLES = 1024  # Match AAC frame size (1024 samples)
    CHUNK_DURATION_MS = int(CHUNK_SAMPLES / RATE * 1000)  # 64ms

    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=CHANNELS, rate=RATE,
                     input=True, frames_per_buffer=CHUNK_SAMPLES)

    init_enc()
    print(f"Streaming microphone (16kHz mono → AAC → camera). Ctrl+C to stop.")
    ts_ms = 0

    try:
        while client._running:
            pcm_data = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
            aac_frames = encode_fn(pcm_data)
            for frame in aac_frames:
                client.send_audio(frame, ts_ms)
                ts_ms += CHUNK_DURATION_MS
    except KeyboardInterrupt:
        pass
    finally:
        close_enc()
        stream.stop_stream()
        stream.close()
        pa.terminate()
        print(f"\nMicrophone stopped ({ts_ms / 1000.0:.1f}s)")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Aqara Camera LAN Talk",
        epilog="Audio: ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a aac -b:a 32k -f adts output.aac")
    parser.add_argument("camera_ip", help="Camera LAN IP address")
    parser.add_argument("--test-connect", action="store_true", help="Test voice session (no audio)")
    parser.add_argument("--audio-file", type=str, help="Send AAC-ADTS file to camera speaker")
    parser.add_argument("--mic", action="store_true", help="Stream microphone to camera (needs pyaudio + av or ffmpeg)")
    parser.add_argument("--doorbell-listen", action="store_true", help="Listen for doorbell press events")
    args = parser.parse_args()

    if args.doorbell_listen:
        try:
            DoorbellListener(args.camera_ip).listen()
        except KeyboardInterrupt:
            print("\nStopped")
        return

    if args.test_connect:
        client = AqaraLanTalk(args.camera_ip)
        if client.connect():
            print("Press Ctrl+C to stop.")
            try:
                while client._running:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
            client.stop()
        return

    if args.audio_file:
        client = AqaraLanTalk(args.camera_ip)
        if not client.connect():
            sys.exit(1)
        try:
            send_aac_file(client, args.audio_file)
        except KeyboardInterrupt:
            pass
        client.stop()
        return

    if args.mic:
        client = AqaraLanTalk(args.camera_ip)
        if not client.connect():
            sys.exit(1)
        try:
            stream_microphone(client)
        except KeyboardInterrupt:
            pass
        client.stop()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
