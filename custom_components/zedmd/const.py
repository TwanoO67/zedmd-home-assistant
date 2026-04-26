"""Constants for the ZeDMD integration."""

DOMAIN = "zedmd"
PLATFORMS = ["media_player"]

# Config entry keys
CONF_HOST = "host"
CONF_HTTP_PORT = "http_port"
CONF_STREAM_PORT = "stream_port"
CONF_NAME = "name"

# Defaults
DEFAULT_HTTP_PORT = 80
DEFAULT_STREAM_PORT = 3333
DEFAULT_NAME = "ZeDMD"

# Display geometry
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 32
FRAME_SIZE = DISPLAY_WIDTH * DISPLAY_HEIGHT * 3  # 12 288 bytes RGB888

# Zone geometry (firmware: TOTAL_WIDTH/16 by TOTAL_HEIGHT/8)
ZONE_WIDTH    = DISPLAY_WIDTH // 16    # 8 px
ZONE_HEIGHT   = DISPLAY_HEIGHT // 8    # 4 px
ZONES_PER_ROW = DISPLAY_WIDTH // ZONE_WIDTH    # 16
ZONES_PER_COL = DISPLAY_HEIGHT // ZONE_HEIGHT  # 8
TOTAL_ZONES   = ZONES_PER_ROW * ZONES_PER_COL  # 128
ZONE_BYTES_565 = ZONE_WIDTH * ZONE_HEIGHT * 2  # 64 bytes RGB565 (little-endian) per zone

# Firmware payload buffer size (main.h: BUFFER_SIZE = 1152 on standard ESP32).
# Each non-black zone entry costs 1 (idx) + ZONE_BYTES_565; black zones cost 1.
DEVICE_BUFFER_SIZE = 1152

# ── ZeDMD wire protocol (libzedmd v5.x) ───────────────────────────────────
# Every logical packet:
#   b"FRAME" (5) + b"ZeDMD" (5) + cmd(1) + size_hi(1) + size_lo(1) + 0x00(1) + payload
# The firmware parser (main.cpp HandleData) only matches "ZeDMD" (N_CTRL_CHARS=5)
# then reads cmd/size_hi/size_lo/comp_flag and finally the payload.

ZEDMD_FRAME_HEADER = b"FRAME"   # 5 bytes – packet sync marker
ZEDMD_CTRL_HEADER  = b"ZeDMD"  # 5 bytes – control/ID marker
ZEDMD_ACK          = b"ZeDMDA" # expected 6-byte ACK  ("ZeDMD" + "A")

# Keep-alive cadence (seconds)
KEEP_ALIVE_INTERVAL = 3.0

# Commands  (ZEDMD_COMM_COMMAND enum from ZeDMDComm.h, matching firmware switch)
# Firmware ≤5.x only implements case 5 (RGB565). RGB888 (case 4) was added in 6.0.0.
CMD_HANDSHAKE       = 0x0C
CMD_CLEAR           = 0x0A
CMD_KEEP_ALIVE      = 0x0B
CMD_RGB565_ZONES    = 0x05   # firmware case 5: RGB565 zone stream (universal)
CMD_RENDER          = 0x06   # firmware case 6: render queued zones (NOP without PSRAM)
CMD_BRIGHTNESS      = 0x16

# Brightness device range
BRIGHTNESS_MIN     = 0
BRIGHTNESS_MAX     = 15
BRIGHTNESS_DEFAULT = 2

# Service names
SERVICE_DISPLAY_TEXT   = "display_text"
SERVICE_SET_BRIGHTNESS = "set_brightness"
SERVICE_CLEAR_SCREEN   = "clear_screen"
SERVICE_TEST_PATTERN   = "test_pattern"
