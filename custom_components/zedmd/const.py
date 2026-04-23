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

# ── ZeDMD wire protocol (libzedmd v5.x) ───────────────────────────────────
# Every logical packet:
#   b"FRAME" (5) + b"ZeDMD" (5) + cmd(1) + size_hi(1) + size_lo(1) + 0x00(1) + payload
# The packet is then sliced into physical chunks of at most MAX_CHUNK_SIZE
# bytes; the device responds with a 6-byte ACK (b"ZeDMD" + b"A") after each
# physical chunk before the host may send the next one.

ZEDMD_FRAME_HEADER = b"FRAME"   # 5 bytes – packet sync marker
ZEDMD_CTRL_HEADER  = b"ZeDMD"  # 5 bytes – control/ID marker
ZEDMD_ACK          = b"ZeDMDA" # expected 6-byte ACK  ("ZeDMD" + "A")

MAX_CHUNK_SIZE = 1920            # maximum physical write (ZEDMD_COMM_MAX_SERIAL_WRITE_AT_ONCE)

# Keep-alive cadence (seconds)
KEEP_ALIVE_INTERVAL = 3.0

# Commands  (ZEDMD_COMM_COMMAND enum from ZeDMDComm.h)
CMD_HANDSHAKE   = 0x0C
CMD_CLEAR       = 0x0A
CMD_KEEP_ALIVE  = 0x0B
CMD_RGB888      = 0x07
CMD_BRIGHTNESS  = 0x16

# Brightness device range
BRIGHTNESS_MIN     = 0
BRIGHTNESS_MAX     = 15
BRIGHTNESS_DEFAULT = 2

# Service names
SERVICE_DISPLAY_TEXT   = "display_text"
SERVICE_SET_BRIGHTNESS = "set_brightness"
SERVICE_CLEAR_SCREEN   = "clear_screen"
SERVICE_TEST_PATTERN   = "test_pattern"
