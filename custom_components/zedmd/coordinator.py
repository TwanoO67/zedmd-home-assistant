"""ZeDMD coordinator: TCP connection + protocol + text rendering."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp
from homeassistant.core import HomeAssistant

from .const import (
    BRIGHTNESS_DEFAULT,
    BRIGHTNESS_MAX,
    CMD_BRIGHTNESS,
    CMD_CLEAR,
    CMD_KEEP_ALIVE,
    CMD_RENDER,
    CMD_RGB565_ZONES,
    DEFAULT_HTTP_PORT,
    DEVICE_BUFFER_SIZE,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FRAME_SIZE,
    KEEP_ALIVE_INTERVAL,
    TOTAL_ZONES,
    ZEDMD_CTRL_HEADER,
    ZEDMD_FRAME_HEADER,
    ZONE_BYTES_565,
    ZONE_HEIGHT,
    ZONE_WIDTH,
    ZONES_PER_ROW,
)

_BLACK_ZONE_565 = b"\x00" * ZONE_BYTES_565

_LOGGER = logging.getLogger(__name__)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Convert '#RRGGBB' or 'RRGGBB' to (R, G, B)."""
    value = value.strip().lstrip("#")
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return r, g, b


class ZeDMDCoordinator:
    """Manages the ZeDMD TCP connection, protocol framing, and text rendering.

    Protocol notes (firmware main.cpp HandleData / libzedmd ZeDMDComm.cpp):
      • Logical packet  = FRAME_HEADER(5) + CTRL_HEADER(5) + cmd(1)
                          + size_hi(1) + size_lo(1) + comp_flag(1) + payload
      • Frame display = N×CMD_RGB888_ZONES (0x04) packets carrying zone entries,
        then a single CMD_RENDER (0x06) packet to flip the buffer.
      • Each payload must fit in the firmware's BUFFER_SIZE (1152 B on ESP32).
      • Over WiFi/TCP the firmware sends no ACK; reliability is handled by TCP.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        stream_port: int,
        http_port: int = DEFAULT_HTTP_PORT,
    ) -> None:
        self.hass = hass
        self.host = host
        self.stream_port = stream_port  # may be updated by HTTP handshake
        self.http_port = http_port

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()
        self._keep_alive_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._current_task: Optional[asyncio.Task] = None

        self.brightness: int = BRIGHTNESS_DEFAULT  # device range 0–15
        self.firmware_version: str = "unknown"
        self.transport: str = "TCP"
        self._state: str = "idle"  # idle | playing | paused

    # ── Public properties ─────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    @property
    def state(self) -> str:
        return self._state

    # ── Packet construction ───────────────────────────────────────────────

    @staticmethod
    def _build_packet(command: int, data: bytes = b"") -> bytes:
        """Assemble a logical ZeDMD packet (not yet chunked)."""
        size = len(data)
        return (
            ZEDMD_FRAME_HEADER
            + ZEDMD_CTRL_HEADER
            + bytes([command, (size >> 8) & 0xFF, size & 0xFF, 0x00])
            + data
        )

    # ── Low-level I/O ─────────────────────────────────────────────────────

    async def _send_command(self, command: int, data: bytes = b"") -> bool:
        """Send a logical packet over TCP (no ACK – WiFi/TCP firmware is fire-and-forget).

        The libzedmd ACK mechanism only exists on the serial transport.
        Over TCP, reliability is guaranteed by the transport layer itself.
        """
        if not self.connected:
            _LOGGER.error("ZeDMD: not connected – cannot send command 0x%02X", command)
            return False

        packet = self._build_packet(command, data)
        _LOGGER.debug(
            "ZeDMD: sending cmd=0x%02X payload=%d bytes  header=%s",
            command, len(data), packet[:14].hex(),
        )

        try:
            self._writer.write(packet)
            await self._writer.drain()
            return True

        except (ConnectionResetError, BrokenPipeError, OSError) as ex:
            _LOGGER.error("ZeDMD: connection lost during send: %s", ex)
            await self._do_disconnect()
            return False

    async def async_send_test_pattern(self, r: int = 255, g: int = 0, b: int = 0) -> bool:
        """Send a solid-colour test frame (no PIL). Use for protocol debugging.

        Default: all-red.  Call with r=0,g=255,b=0 for green, etc.
        """
        frame = bytes([r, g, b]) * (DISPLAY_WIDTH * DISPLAY_HEIGHT)
        _LOGGER.info(
            "ZeDMD: sending test pattern RGB(%d,%d,%d) – %d bytes",
            r, g, b, len(frame),
        )
        return await self.async_send_frame(frame)

    # ── HTTP handshake ────────────────────────────────────────────────────

    async def _http_handshake(self) -> bool:
        """GET http://<host>:<http_port>/handshake and parse pipe-delimited response.

        Response format (21 pipe-separated fields, ZeDMDWiFi.cpp):
          0:width | 1:height | 2:fw_version | 3:s3 | 4:protocol(TCP/UDP)
          5:stream_port | 6:udp_delay | 7:write_at_once | 8:brightness
          9:rgb_mode | 10:clkphase | 11:driver | 12:i2s_speed
          13:latch_blanking | 14:min_refresh | 15:y_offset | 16:ssid
          17:half | 18:device_id | 19:power | 20:device_type
        """
        url = f"http://{self.host}:{self.http_port}/handshake"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning(
                            "ZeDMD: HTTP handshake returned status %d", resp.status
                        )
                        return False
                    body = await resp.text()

            # Strip HTTP headers if raw response (some firmware variants)
            if "\r\n\r\n" in body:
                body = body.split("\r\n\r\n", 1)[1]
            body = body.strip()

            fields = body.split("|")
            _LOGGER.debug("ZeDMD: handshake fields %s", fields)

            if len(fields) > 2:
                self.firmware_version = fields[2] if len(fields) > 2 else "unknown"
            if len(fields) > 4:
                self.transport = fields[4].strip().upper()  # "TCP" or "UDP"
            if len(fields) > 5 and fields[5].strip().isdigit():
                self.stream_port = int(fields[5].strip())
            if len(fields) > 8 and fields[8].strip().isdigit():
                self.brightness = int(fields[8].strip())

            _LOGGER.info(
                "ZeDMD: handshake OK – fw=%s transport=%s stream_port=%d",
                self.firmware_version, self.transport, self.stream_port,
            )
            return True

        except aiohttp.ClientError as ex:
            _LOGGER.warning("ZeDMD: HTTP handshake failed: %s", ex)
            return False
        except Exception as ex:
            _LOGGER.warning("ZeDMD: HTTP handshake unexpected error: %s", ex)
            return False

    # ── Connection lifecycle ──────────────────────────────────────────────

    async def async_connect(self) -> bool:
        """HTTP handshake then open the TCP streaming connection."""
        # Step 1 – HTTP handshake (updates stream_port, firmware version, etc.)
        await self._http_handshake()  # non-fatal if it fails

        if self.transport == "UDP":
            _LOGGER.error(
                "ZeDMD: device is in UDP mode – this integration requires TCP. "
                "Change the transport in the ZeDMD firmware settings."
            )
            return False

        # Step 2 – TCP streaming socket
        # The ZeDMD firmware only allows ONE concurrent TCP client.
        # If transportActive is still True (e.g. after HA restart without
        # power-cycling the device), the firmware closes the connection
        # immediately after the TCP handshake.  We detect this by trying
        # a small read with a short timeout right after connect.
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.stream_port),
                timeout=5.0,
            )

            # Quick rejection probe: if the firmware closes the socket
            # (transportActive already True), we get EOF within ~200 ms.
            try:
                peek = await asyncio.wait_for(
                    self._reader.read(1), timeout=0.3
                )
                if peek == b"":
                    # EOF → firmware rejected us (already has a client)
                    _LOGGER.error(
                        "ZeDMD: connection rejected by firmware "
                        "(device already has an active client). "
                        "Power-cycle the ZeDMD and try again."
                    )
                    self._writer.close()
                    self._reader = None
                    self._writer = None
                    return False
                # Some unexpected data arrived; log and continue.
                _LOGGER.debug("ZeDMD: unexpected byte on connect probe: %r", peek)
            except asyncio.TimeoutError:
                # No data and no EOF → firmware accepted us (normal path)
                pass

            _LOGGER.info(
                "ZeDMD: TCP connected to %s:%d", self.host, self.stream_port
            )
            self._keep_alive_task = asyncio.create_task(self._keep_alive_loop())
            self._monitor_task = asyncio.create_task(self._connection_monitor())
            self._state = "idle"
            return True

        except (OSError, asyncio.TimeoutError) as ex:
            _LOGGER.error(
                "ZeDMD: TCP connect to %s:%d failed: %s",
                self.host, self.stream_port, ex,
            )
            self._reader = None
            self._writer = None
            return False

    async def _connection_monitor(self) -> None:
        """Wait for EOF from the firmware (indicates remote disconnect)."""
        try:
            await self._reader.read(1)
            # Any data or EOF here means something unexpected happened
            _LOGGER.warning("ZeDMD: connection closed by device")
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            _LOGGER.warning("ZeDMD: connection reset by device")
        except asyncio.CancelledError:
            return
        finally:
            # Mark as disconnected so the entity shows 'unavailable'
            self._writer = None
            self._reader = None
            self._state = "idle"

    async def _do_disconnect(self) -> None:
        """Internal disconnect (cancels tasks, closes socket)."""
        self._state = "idle"

        if self._keep_alive_task:
            self._keep_alive_task.cancel()
            self._keep_alive_task = None

        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None

        if self._current_task:
            self._current_task.cancel()
            self._current_task = None

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def async_disconnect(self) -> None:
        """Public disconnect called by HA on unload."""
        await self._do_disconnect()

    # ── Keep-alive ────────────────────────────────────────────────────────

    async def _keep_alive_loop(self) -> None:
        """Send CMD_KEEP_ALIVE every KEEP_ALIVE_INTERVAL seconds."""
        while True:
            await asyncio.sleep(KEEP_ALIVE_INTERVAL)
            if not self.connected:
                break
            async with self._lock:
                try:
                    packet = self._build_packet(CMD_KEEP_ALIVE)
                    self._writer.write(packet)
                    await self._writer.drain()
                    # Keep-alive expects no ACK from the device.
                except Exception as ex:
                    _LOGGER.debug("ZeDMD: keep-alive write error: %s", ex)

    # ── Display commands ──────────────────────────────────────────────────

    async def async_clear_screen(self) -> bool:
        """Blank the display."""
        async with self._lock:
            return await self._send_command(CMD_CLEAR)

    async def async_set_brightness(self, percent: int) -> bool:
        """Set brightness.  percent: 0–100 → device range 0–15."""
        level = round(percent / 100.0 * BRIGHTNESS_MAX)
        level = max(0, min(BRIGHTNESS_MAX, level))
        self.brightness = level
        async with self._lock:
            return await self._send_command(CMD_BRIGHTNESS, bytes([level]))

    @staticmethod
    def _build_zone_packets(rgb_data: bytes) -> list[bytes]:
        """Convert RGB888 frame to RGB565 zones, packed for the firmware.

        Firmware case 5 (RGB565 Zones Stream) expects payload =
        concatenation of zone entries, each:
          - non-black zone: 1 byte zone_idx (0..127) + ZONE_BYTES_565 pixel data
          - all-black zone: 1 byte (zone_idx | 0x80)   ← optimisation

        RGB565 layout per pixel: 2 bytes little-endian, where
            pixel = (R5 << 11) | (G6 << 5) | B5
            byte0 = pixel & 0xFF, byte1 = (pixel >> 8) & 0xFF

        Each payload must fit in DEVICE_BUFFER_SIZE (1152 B on stock ESP32).
        """
        packets: list[bytes] = []
        buf = bytearray()
        for idx in range(TOTAL_ZONES):
            zx = idx % ZONES_PER_ROW
            zy = idx // ZONES_PER_ROW
            zone = bytearray(ZONE_BYTES_565)
            out = 0
            for dy in range(ZONE_HEIGHT):
                row_start = ((zy * ZONE_HEIGHT + dy) * DISPLAY_WIDTH + zx * ZONE_WIDTH) * 3
                for dx in range(ZONE_WIDTH):
                    p = row_start + dx * 3
                    r = rgb_data[p]
                    g = rgb_data[p + 1]
                    b = rgb_data[p + 2]
                    pixel = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                    zone[out]     = pixel & 0xFF
                    zone[out + 1] = (pixel >> 8) & 0xFF
                    out += 2
            if zone == _BLACK_ZONE_565:
                entry = bytes([idx | 0x80])
            else:
                entry = bytes([idx]) + bytes(zone)
            if len(buf) + len(entry) > DEVICE_BUFFER_SIZE:
                packets.append(bytes(buf))
                buf = bytearray()
            buf.extend(entry)
        if buf:
            packets.append(bytes(buf))
        return packets

    async def async_send_frame(self, rgb_data: bytes) -> bool:
        """Send a raw RGB888 frame (DISPLAY_WIDTH × DISPLAY_HEIGHT × 3 bytes).

        Wire protocol: one or more CMD_RGB565_ZONES packets, then CMD_RENDER.
        Frame is converted to RGB565 to be compatible with firmware ≤ 5.x
        (RGB888 zone stream was only added in firmware 6.0.0).
        """
        if len(rgb_data) != FRAME_SIZE:
            _LOGGER.error(
                "ZeDMD: wrong frame size %d (expected %d)", len(rgb_data), FRAME_SIZE
            )
            return False
        packets = await self.hass.async_add_executor_job(
            self._build_zone_packets, rgb_data
        )
        async with self._lock:
            for payload in packets:
                if not await self._send_command(CMD_RGB565_ZONES, payload):
                    return False
            return await self._send_command(CMD_RENDER)

    # ── Text rendering ────────────────────────────────────────────────────

    @staticmethod
    def _render_frame(
        text: str,
        font,
        color: tuple[int, int, int],
        bg_color: tuple[int, int, int],
        x_offset: int,
    ) -> bytes:
        """Draw *text* at (x_offset, centred_y) into a 128×32 RGB image."""
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (DISPLAY_WIDTH, DISPLAY_HEIGHT), bg_color)
        draw = ImageDraw.Draw(img)

        # Vertical centre using font metrics
        try:
            bbox = font.getbbox("A")
            font_height = bbox[3] - bbox[1]
        except AttributeError:
            font_height = 10  # fallback for old Pillow

        y = max(0, (DISPLAY_HEIGHT - font_height) // 2)
        draw.text((x_offset, y), text, font=font, fill=color)
        return img.tobytes()  # RGB888

    @staticmethod
    def _load_font(size: int = 20):
        """Load the best available PIL font at *size* pixels."""
        from PIL import ImageFont

        # 1) Try system TrueType fonts common on Linux (HA OS)
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except (IOError, OSError):
                pass

        # 2) PIL built-in scalable default (Pillow ≥ 9.2.0)
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            pass

        # 3) Oldest fallback – tiny bitmap font
        return ImageFont.load_default()

    async def async_display_text(
        self,
        text: str,
        color: str | tuple = "#FFFFFF",
        bg_color: str | tuple = "#000000",
        scroll: bool = True,
        scroll_speed: int = 2,
        fps: int = 20,
    ) -> None:
        """Render *text* on the display.

        If *scroll* is True and the text is wider than the panel the text will
        continuously scroll right-to-left until stopped.
        """
        # Normalise colour arguments
        if isinstance(color, str):
            color = _hex_to_rgb(color)
        if isinstance(bg_color, str):
            bg_color = _hex_to_rgb(bg_color)

        font = await self.hass.async_add_executor_job(self._load_font, 20)

        # Measure text width in a throw-away image
        from PIL import Image, ImageDraw

        def _measure(txt: str) -> int:
            tmp = Image.new("RGB", (4096, DISPLAY_HEIGHT))
            d = ImageDraw.Draw(tmp)
            bbox = d.textbbox((0, 0), txt, font=font)
            return bbox[2] - bbox[0]

        text_width = await self.hass.async_add_executor_job(_measure, text)

        if not scroll or text_width <= DISPLAY_WIDTH - 4:
            # ── Static display ─────────────────────────────────────────────
            frame = await self.hass.async_add_executor_job(
                self._render_frame, text, font, color, bg_color, 4
            )
            self._state = "playing"
            await self.async_send_frame(frame)
            return

        # ── Scrolling loop (background task) ──────────────────────────────
        async def _scroll_loop() -> None:
            self._state = "playing"
            x = DISPLAY_WIDTH
            interval = 1.0 / fps

            try:
                while self._state == "playing":
                    frame = await self.hass.async_add_executor_job(
                        self._render_frame, text, font, color, bg_color, x
                    )
                    if not await self.async_send_frame(frame):
                        break

                    x -= scroll_speed
                    if x < -(text_width + 10):
                        x = DISPLAY_WIDTH  # restart from right

                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                pass
            finally:
                if self._state == "playing":
                    self._state = "idle"

        # Cancel any previous task first (lock not held here on purpose)
        if self._current_task:
            self._current_task.cancel()
        self._current_task = asyncio.create_task(_scroll_loop())

    async def async_stop(self) -> None:
        """Stop current playback and clear the screen."""
        self._state = "idle"
        if self._current_task:
            self._current_task.cancel()
            self._current_task = None
        await self.async_clear_screen()

    async def async_pause(self) -> None:
        """Pause scrolling (freeze current frame)."""
        if self._state == "playing":
            self._state = "paused"
            if self._current_task:
                self._current_task.cancel()
                self._current_task = None

    async def async_resume(self) -> None:
        """Resume – not implemented for text; re-display last content."""
        self._state = "idle"
