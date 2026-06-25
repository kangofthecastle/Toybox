"""Generate the Toybox app/tray icon as a real .ico file, pure stdlib.

Draws a WHITE, outline-style game controller (matching the monochrome line-art
of the Windows notification-area icons): a hollow gamepad body with two grips, a
d-pad and two face buttons. White strokes, transparent fill. Rendered at 4x
supersample for clean edges, box-downscaled to 32x32 RGBA (pure white with a
coverage alpha), then encoded as a 32-bpp BMP-based .ico. No third-party imports.
"""
import math
import os
import struct
import tempfile
import zlib

SIZE = 32
SS = 4                 # supersample factor
W = SIZE * SS          # working canvas edge (128)
STROKE = 2.0           # stroke width in 32-space px


def _stamp(ink, cx, cy, r, val=255):
    """Paint a filled disc of `val` into the single-channel ink buffer.

    val=255 lays down ink (white); val=0 erases it (used to knock the hollow
    interior and the d-pad/button cuts out of a filled silhouette)."""
    r2 = r * r
    x0 = max(0, int(cx - r))
    x1 = min(W - 1, int(cx + r) + 1)
    y0 = max(0, int(cy - r))
    y1 = min(W - 1, int(cy + r) + 1)
    for y in range(y0, y1 + 1):
        dy = y - cy
        for x in range(x0, x1 + 1):
            dx = x - cx
            if dx * dx + dy * dy <= r2:
                ink[y * W + x] = val


def _disc(ink, cx, cy, r, val=255):
    """Filled disc in 32-space coordinates."""
    _stamp(ink, cx * SS, cy * SS, r * SS, val)


def _line(ink, x0, y0, x1, y1, t=STROKE):
    x0 *= SS; y0 *= SS; x1 *= SS; y1 *= SS
    r = t * SS / 2.0
    n = max(1, int(math.hypot(x1 - x0, y1 - y0)))
    for k in range(n + 1):
        _stamp(ink, x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, r)


def _arc(ink, cx, cy, rad, a0, a1, t=STROKE):
    cx *= SS; cy *= SS; rad *= SS
    r = t * SS / 2.0
    n = max(2, int(abs(a1 - a0) * 2))
    for k in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * k / n)
        _stamp(ink, cx + rad * math.cos(a), cy - rad * math.sin(a), r)


def _fill_rrect(ink, x0, y0, x1, y1, r, val=255):
    """Filled rounded rectangle in 32-space coordinates."""
    X0 = x0 * SS; Y0 = y0 * SS; X1 = x1 * SS; Y1 = y1 * SS; R = r * SS
    for y in range(max(0, int(Y0)), min(W, int(Y1) + 1)):
        for x in range(max(0, int(X0)), min(W, int(X1) + 1)):
            dx = dy = 0.0
            if x < X0 + R: dx = X0 + R - x
            elif x > X1 - R: dx = x - (X1 - R)
            if y < Y0 + R: dy = Y0 + R - y
            elif y > Y1 - R: dy = y - (Y1 - R)
            if dx * dx + dy * dy <= R * R:
                ink[y * W + x] = val


def _dpad(ink, cx, cy, val, arm=2.3, half=0.8):
    """A plus/cross (the directional pad), drawn or erased per `val`."""
    _fill_rrect(ink, cx - half, cy - arm, cx + half, cy + arm, 0.2, val)
    _fill_rrect(ink, cx - arm, cy - half, cx + arm, cy + half, 0.2, val)


def _render_rgba():
    """Draw the white outline game controller, downscale coverage -> alpha."""
    ink = bytearray(W * W)

    # Solid gamepad silhouette: rounded body + two grips bulging down.
    _fill_rrect(ink, 4.0, 10.0, 28.0, 20.5, 4.2)
    _disc(ink, 8.6, 19.6, 4.8)
    _disc(ink, 23.4, 19.6, 4.8)
    # Hollow it out, leaving a ~2px outline ring (matches the line-art tray icons).
    _fill_rrect(ink, 6.3, 12.2, 25.7, 18.0, 2.8, val=0)
    _disc(ink, 8.6, 18.8, 2.7, val=0)
    _disc(ink, 23.4, 18.8, 2.7, val=0)
    # Controls inside the hollow: d-pad (left) + two face buttons (right).
    _dpad(ink, 10.0, 14.8, val=255)
    _disc(ink, 21.0, 13.8, 1.4)
    _disc(ink, 23.8, 16.4, 1.4)

    out = bytearray(SIZE * SIZE * 4)
    area = SS * SS
    for oy in range(SIZE):
        for ox in range(SIZE):
            s = 0
            for sy in range(SS):
                base = (oy * SS + sy) * W + ox * SS
                for sx in range(SS):
                    s += ink[base + sx]
            o = (oy * SIZE + ox) * 4
            out[o] = 255          # B
            out[o + 1] = 255      # G
            out[o + 2] = 255      # R (white)
            out[o + 3] = s // area
    return out


def build_ico_bytes():
    """Return a complete 32-bpp BMP-based .ico (32x32) as bytes."""
    rgba = _render_rgba()
    w = h = SIZE
    xor = bytearray()
    for y in range(h - 1, -1, -1):          # bottom-up rows
        for x in range(w):
            i = (y * w + x) * 4
            xor += bytes((rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]))  # already BGRA (white)
    and_stride = ((w + 31) // 32) * 4
    and_mask = b"\x00" * (and_stride * h)   # alpha channel handles transparency
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    image = header + bytes(xor) + and_mask
    icondir = struct.pack("<HHH", 0, 1, 1)  # reserved, type=icon, count=1
    entry = struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(image), 6 + 16)
    return icondir + entry + image


def ensure_ico(path):
    """Write the .ico to path atomically (always refreshed to match the design)."""
    data = build_ico_bytes()
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return path


def save_png_preview(path):
    """Write the 32x32 RGBA as a PNG (for visual inspection only)."""
    rgba = _render_rgba()
    w = h = SIZE

    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))

    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            i = (y * w + x) * 4
            raw += bytes((rgba[i + 2], rgba[i + 1], rgba[i], rgba[i + 3]))  # RGBA for PNG
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return path
