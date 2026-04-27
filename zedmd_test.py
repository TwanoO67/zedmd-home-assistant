#!/usr/bin/env python3
"""Standalone ZeDMD test tool — no Home Assistant required.

Usage examples:
  python zedmd_test.py --host 192.168.1.50 text "Hello World"
  python zedmd_test.py --host 192.168.1.50 text "Hello" --color "#FF8800" --no-scroll
  python zedmd_test.py --host 192.168.1.50 text "Scrolling..." --duration 10
  python zedmd_test.py --host 192.168.1.50 test-pattern --r 0 --g 255 --b 0
  python zedmd_test.py --host 192.168.1.50 clear
  python zedmd_test.py --host 192.168.1.50 brightness 50
"""

from __future__ import annotations

import argparse
import asyncio
import sys

# ── Protocol constants (mirrored from const.py) ────────────────────────────

DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 32
FRAME_SIZE = DISPLAY_WIDTH * DISPLAY_HEIGHT * 3

ZONE_WIDTH = 8
ZONE_HEIGHT = 4
ZONES_PER_ROW = 16
TOTAL_ZONES = 128
ZONE_BYTES_565 = ZONE_WIDTH * ZONE_HEIGHT * 2
DEVICE_BUFFER_SIZE = 1152

ZEDMD_FRAME_HEADER = b"FRAME"
ZEDMD_CTRL_HEADER = b"ZeDMD"

CMD_CLEAR = 0x0A
CMD_KEEP_ALIVE = 0x0B
CMD_RGB565_ZONES = 0x05
CMD_RENDER = 0x06
CMD_BRIGHTNESS = 0x16

DEFAULT_HTTP_PORT = 80
DEFAULT_STREAM_PORT = 3333

_BLACK_ZONE_565 = b"\x00" * ZONE_BYTES_565

# ── Helpers ────────────────────────────────────────────────────────────────


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _build_packet(command: int, data: bytes = b"") -> bytes:
    size = len(data)
    return (
        ZEDMD_FRAME_HEADER
        + ZEDMD_CTRL_HEADER
        + bytes([command, (size >> 8) & 0xFF, size & 0xFF, 0x00])
        + data
    )


def _build_zone_packets(rgb_data: bytes) -> list[bytes]:
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
                r, g, b = rgb_data[p], rgb_data[p + 1], rgb_data[p + 2]
                pixel = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                zone[out] = pixel & 0xFF
                zone[out + 1] = (pixel >> 8) & 0xFF
                out += 2
        entry = bytes([idx | 0x80]) if bytes(zone) == _BLACK_ZONE_565 else bytes([idx]) + bytes(zone)
        if len(buf) + len(entry) > DEVICE_BUFFER_SIZE:
            packets.append(bytes(buf))
            buf = bytearray()
        buf.extend(entry)
    if buf:
        packets.append(bytes(buf))
    return packets


def _load_font(size: int = 20):
    from PIL import ImageFont

    candidates = [
        # Linux (HA OS)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        # Windows
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/verdana.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        # macOS
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        pass
    return ImageFont.load_default()


def _render_frame(
    text: str,
    font,
    color: tuple[int, int, int],
    bg_color: tuple[int, int, int],
    x_offset: int,
) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (DISPLAY_WIDTH, DISPLAY_HEIGHT), bg_color)
    draw = ImageDraw.Draw(img)
    try:
        bbox = font.getbbox("A")
        font_height = bbox[3] - bbox[1]
    except AttributeError:
        font_height = 10
    y = max(0, (DISPLAY_HEIGHT - font_height) // 2)
    draw.text((x_offset, y), text, font=font, fill=color)
    return img.tobytes()


def _measure_text(text: str, font) -> int:
    from PIL import Image, ImageDraw

    tmp = Image.new("RGB", (4096, DISPLAY_HEIGHT))
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


# ── Client ─────────────────────────────────────────────────────────────────


class ZeDMDClient:
    def __init__(self, host: str, http_port: int, stream_port: int) -> None:
        self.host = host
        self.http_port = http_port
        self.stream_port = stream_port
        self.firmware_version = "unknown"
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def handshake(self) -> bool:
        import aiohttp

        url = f"http://{self.host}:{self.http_port}/handshake"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        print(f"[warn] HTTP handshake returned status {resp.status}", file=sys.stderr)
                        return False
                    body = await resp.text()
            if "\r\n\r\n" in body:
                body = body.split("\r\n\r\n", 1)[1]
            body = body.strip()
            fields = body.split("|")
            if len(fields) > 2:
                self.firmware_version = fields[2]
            if len(fields) > 5 and fields[5].strip().isdigit():
                self.stream_port = int(fields[5].strip())
            print(f"[ok] Handshake – fw={self.firmware_version}  stream_port={self.stream_port}")
            return True
        except Exception as ex:
            print(f"[warn] Handshake failed: {ex}", file=sys.stderr)
            return False

    async def connect(self) -> bool:
        await self.handshake()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.stream_port),
                timeout=5.0,
            )
            try:
                peek = await asyncio.wait_for(self._reader.read(1), timeout=0.3)
                if peek == b"":
                    print("[error] Connection rejected – device already has an active client.", file=sys.stderr)
                    self._writer.close()
                    self._reader = self._writer = None
                    return False
            except asyncio.TimeoutError:
                pass
            print(f"[ok] TCP connected to {self.host}:{self.stream_port}")
            return True
        except Exception as ex:
            print(f"[error] TCP connect failed: {ex}", file=sys.stderr)
            return False

    async def disconnect(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._reader = self._writer = None

    async def _send(self, command: int, data: bytes = b"") -> bool:
        packet = _build_packet(command, data)
        try:
            self._writer.write(packet)
            await self._writer.drain()
            return True
        except Exception as ex:
            print(f"[error] Send failed: {ex}", file=sys.stderr)
            return False

    async def send_frame(self, rgb_data: bytes) -> bool:
        for payload in _build_zone_packets(rgb_data):
            if not await self._send(CMD_RGB565_ZONES, payload):
                return False
        return await self._send(CMD_RENDER)

    async def clear(self) -> bool:
        ok = await self._send(CMD_CLEAR)
        if ok:
            print("[ok] Screen cleared")
        return ok

    async def set_brightness(self, percent: int) -> bool:
        level = max(0, min(15, round(percent / 100.0 * 15)))
        ok = await self._send(CMD_BRIGHTNESS, bytes([level]))
        if ok:
            print(f"[ok] Brightness set to {percent}% (level {level}/15)")
        return ok

    async def test_pattern(self, r: int, g: int, b: int) -> bool:
        frame = bytes([r, g, b]) * (DISPLAY_WIDTH * DISPLAY_HEIGHT)
        ok = await self.send_frame(frame)
        if ok:
            print(f"[ok] Test pattern RGB({r},{g},{b}) sent")
        return ok

    async def display_text(
        self,
        text: str,
        color: str = "#FFFFFF",
        bg_color: str = "#000000",
        scroll: bool = True,
        scroll_speed: int = 2,
        fps: int = 20,
        duration: float = 0.0,
    ) -> None:
        fg = _hex_to_rgb(color)
        bg = _hex_to_rgb(bg_color)
        font = _load_font(20)
        text_width = _measure_text(text, font)

        if not scroll or text_width <= DISPLAY_WIDTH - 4:
            frame = _render_frame(text, font, fg, bg, 4)
            if await self.send_frame(frame):
                print(f"[ok] Static text displayed: '{text}'")
            return

        print(
            f"[ok] Scrolling '{text}' "
            f"(width={text_width}px, speed={scroll_speed}px/frame @ {fps}fps"
            + (f", duration={duration}s" if duration > 0 else ", Ctrl-C to stop")
            + ")"
        )
        interval = 1.0 / fps
        x = DISPLAY_WIDTH
        loop = asyncio.get_event_loop()
        start = loop.time()
        try:
            while True:
                frame = _render_frame(text, font, fg, bg, x)
                if not await self.send_frame(frame):
                    break
                x -= scroll_speed
                if x < -(text_width + 10):
                    x = DISPLAY_WIDTH
                if duration > 0 and (loop.time() - start) >= duration:
                    break
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            pass


# ── CLI ────────────────────────────────────────────────────────────────────


async def _main(args: argparse.Namespace) -> int:
    client = ZeDMDClient(args.host, args.http_port, args.stream_port)

    if not await client.connect():
        return 1

    try:
        if args.command == "text":
            await client.display_text(
                text=args.message,
                color=args.color,
                bg_color=args.bg_color,
                scroll=not args.no_scroll,
                scroll_speed=args.scroll_speed,
                fps=args.fps,
                duration=args.duration,
            )
        elif args.command == "clear":
            await client.clear()
        elif args.command == "brightness":
            await client.set_brightness(args.level)
        elif args.command == "test-pattern":
            await client.test_pattern(args.r, args.g, args.b)
    except KeyboardInterrupt:
        print("\n[info] Interrupted")
    finally:
        await client.disconnect()

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ZeDMD standalone test tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--host", required=True, help="ZeDMD IP address or hostname")
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT, metavar="PORT")
    parser.add_argument("--stream-port", type=int, default=DEFAULT_STREAM_PORT, metavar="PORT")

    sub = parser.add_subparsers(dest="command", required=True)

    # text
    p_text = sub.add_parser("text", help="Display a text message")
    p_text.add_argument("message", help="Text to display")
    p_text.add_argument("--color", default="#FFFFFF", help="Foreground colour (default: #FFFFFF)")
    p_text.add_argument("--bg-color", default="#000000", help="Background colour (default: #000000)")
    p_text.add_argument("--no-scroll", action="store_true", help="Force static display")
    p_text.add_argument("--scroll-speed", type=int, default=2, metavar="PX", help="Pixels per frame (default: 2)")
    p_text.add_argument("--fps", type=int, default=20, help="Frames per second (default: 20)")
    p_text.add_argument("--duration", type=float, default=0.0, metavar="SEC",
                        help="Stop scrolling after N seconds (0 = until Ctrl-C)")

    # clear
    sub.add_parser("clear", help="Blank the display")

    # brightness
    p_bright = sub.add_parser("brightness", help="Set display brightness")
    p_bright.add_argument("level", type=int, metavar="PERCENT", help="Brightness 0–100")

    # test-pattern
    p_tp = sub.add_parser("test-pattern", help="Send a solid-colour test frame")
    p_tp.add_argument("--r", type=int, default=255, help="Red 0–255 (default: 255)")
    p_tp.add_argument("--g", type=int, default=0, help="Green 0–255 (default: 0)")
    p_tp.add_argument("--b", type=int, default=0, help="Blue 0–255 (default: 0)")

    args = parser.parse_args()
    sys.exit(asyncio.run(_main(args)))


if __name__ == "__main__":
    main()
