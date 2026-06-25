"""Generate the Toybox app/tray icon as a real .ico file, pure stdlib.

Draws a cute teal mascot face (a sibling of the desktop pet) at 4x supersample,
box-downscales to 32x32 RGBA for clean edges, and encodes a 32-bpp BMP-based
.ico (universally loadable via LoadImageW). No third-party imports.
"""
import os
import struct
import tempfile
import zlib

SIZE = 32
SS = 4                # supersample factor
W = SIZE * SS         # working canvas edge (128)

# Palette (RGBA).
TEAL = (74, 196, 196, 255)       # toolbox body
TEAL_LT = (124, 218, 218, 255)   # lid highlight
TEAL_DK = (44, 150, 150, 255)
DARK = (26, 60, 60, 255)         # rim, handle, seam
ACCENT = (255, 201, 84, 255)     # latch / clasps
ACCENT_DK = (196, 146, 40, 255)
_BG = (74, 196, 196, 0)          # teal w/ 0 alpha so edges blend to teal, not black


def _blend(buf, x, y, color):
    if x < 0 or y < 0 or x >= W or y >= W:
        return
    r, g, b, a = color
    if a == 0:
        return
    i = (y * W + x) * 4
    ia = 255 - a
    buf[i] = (r * a + buf[i] * ia) // 255
    buf[i + 1] = (g * a + buf[i + 1] * ia) // 255
    buf[i + 2] = (b * a + buf[i + 2] * ia) // 255
    buf[i + 3] = min(255, a + buf[i + 3] * ia // 255)


def _disc(buf, cx, cy, r, color):
    cx *= SS
    cy *= SS
    r *= SS
    r2 = r * r
    for y in range(int(cy - r), int(cy + r) + 1):
        for x in range(int(cx - r), int(cx + r) + 1):
            dx, dy = x - cx, y - cy
            if dx * dx + dy * dy <= r2:
                _blend(buf, x, y, color)


def _rect(buf, x0, y0, x1, y1, color):
    for y in range(int(round(y0 * SS)), int(round(y1 * SS))):
        for x in range(int(round(x0 * SS)), int(round(x1 * SS))):
            _blend(buf, x, y, color)


def _rrect(buf, x0, y0, x1, y1, r, color):
    _rect(buf, x0 + r, y0, x1 - r, y1, color)
    _rect(buf, x0, y0 + r, x1, y1 - r, color)
    _disc(buf, x0 + r, y0 + r, r, color)
    _disc(buf, x1 - r, y0 + r, r, color)
    _disc(buf, x0 + r, y1 - r, r, color)
    _disc(buf, x1 - r, y1 - r, r, color)


def _render_rgba():
    """Draw the mascot at supersample, then box-downscale to SIZE x SIZE RGBA."""
    buf = bytearray()
    for _ in range(W * W):
        buf += bytes(_BG)

    # Handle: a dark "staple" arching over the top.
    _rrect(buf, 10.5, 6.0, 21.5, 8.4, 1.0, DARK)
    _rect(buf, 11.0, 7.5, 13.3, 11.6, DARK)
    _rect(buf, 18.7, 7.5, 21.0, 11.6, DARK)

    # Box: dark rim, then teal body.
    _rrect(buf, 3.5, 10.5, 28.5, 27.5, 3.5, DARK)
    _rrect(buf, 4.3, 11.3, 27.7, 26.7, 3.0, TEAL)

    # Lid highlight band + seam line (the lid opening).
    _rect(buf, 6.0, 12.2, 26.0, 15.3, TEAL_LT)
    _rect(buf, 5.0, 15.6, 27.0, 16.8, DARK)

    # Clasps on the seam.
    for cx in (9.0, 23.0):
        _disc(buf, cx, 16.2, 1.6, DARK)
        _disc(buf, cx, 16.2, 0.9, ACCENT)

    # Central latch.
    _rrect(buf, 13.5, 17.6, 18.5, 22.6, 1.0, DARK)
    _rrect(buf, 14.1, 18.2, 17.9, 22.0, 0.7, ACCENT)

    # Box-average downscale SS x SS -> SIZE x SIZE.
    out = bytearray(SIZE * SIZE * 4)
    area = SS * SS
    for oy in range(SIZE):
        for ox in range(SIZE):
            r = g = b = a = 0
            for sy in range(SS):
                base = ((oy * SS + sy) * W + ox * SS) * 4
                for sx in range(SS):
                    i = base + sx * 4
                    r += buf[i]
                    g += buf[i + 1]
                    b += buf[i + 2]
                    a += buf[i + 3]
            o = (oy * SIZE + ox) * 4
            out[o] = r // area
            out[o + 1] = g // area
            out[o + 2] = b // area
            out[o + 3] = a // area
    return out


def build_ico_bytes():
    """Return a complete 32-bpp BMP-based .ico (32x32) as bytes."""
    rgba = _render_rgba()
    w = h = SIZE
    xor = bytearray()
    for y in range(h - 1, -1, -1):          # bottom-up rows
        for x in range(w):
            i = (y * w + x) * 4
            xor += bytes((rgba[i + 2], rgba[i + 1], rgba[i], rgba[i + 3]))  # BGRA
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
        raw += rgba[y * w * 4:(y + 1) * w * 4]
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    return path
