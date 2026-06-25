# tools/calibrate_eyes.py
"""Print the EYES["idle"] anchor table by finding the two dark eye clusters in
each Idle.png frame. Run once; paste the output into petkit/eyes.py.
    python tools/calibrate_eyes.py
"""
import os
import struct
import zlib

SHEET = os.path.join(os.path.dirname(__file__), "..", "assets", "cat", "Idle.png")
FW = FH = 32
EYE_BAND = range(11, 16)  # rows the eye almonds occupy (excludes the brow ridge)
DARK = 95                 # luminance below this counts as "eye/outline ink"


def centroid(pts, fallback):
    if not pts:
        return fallback
    return (round(sum(p[0] for p in pts) / len(pts)),
            round(sum(p[1] for p in pts) / len(pts)))


def _decode_rgba(path):
    d = open(path, "rb").read(); i = 8; idat = b""; W = H = ct = 0
    while i < len(d):
        ln = struct.unpack(">I", d[i:i + 4])[0]; typ = d[i + 4:i + 8]
        data = d[i + 8:i + 8 + ln]; i += 12 + ln
        if typ == b"IHDR": W, H, _, ct = struct.unpack(">IIBB", data[:10])
        elif typ == b"IDAT": idat += data
        elif typ == b"IEND": break
    raw = zlib.decompress(idat); ch = 4 if ct == 6 else 3; stride = W * ch
    out = bytearray(); prev = bytearray(stride); p = 0
    for _y in range(H):
        f = raw[p]; p += 1; line = bytearray(raw[p:p + stride]); p += stride
        for x in range(stride):
            a = line[x - ch] if x >= ch else 0; b = prev[x]; c = prev[x - ch] if x >= ch else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif f == 4:
                pp = a + b - c; pa = abs(pp - a); pb = abs(pp - b); pc = abs(pp - c)
                line[x] = (line[x] + (a if (pa <= pb and pa <= pc) else (b if pb <= pc else c))) & 255
        out += line; prev = line
    return W, H, ch, bytes(out)


def main():
    W, H, ch, px = _decode_rgba(SHEET)
    frames = W // FW
    table = []
    for fi in range(frames):
        groups = {"l": [], "r": []}
        for y in EYE_BAND:
            dark = []
            for x in range(FW):
                o = (y * W + fi * FW + x) * ch
                r, g, b = px[o], px[o + 1], px[o + 2]
                a = px[o + 3] if ch == 4 else 255
                if a > 0 and (0.299 * r + 0.587 * g + 0.114 * b) < DARK:
                    dark.append((x, y))
            # The leftmost/rightmost dark pixels are the head outline, not the
            # eye -- drop them so they can't drag the centroid onto the border.
            interior = dark[1:-1]
            if not interior:
                continue
            # Split the remaining interior ink into the two eyes about its midpoint.
            mid = (interior[0][0] + interior[-1][0]) / 2.0
            for x, y in interior:
                groups["l" if x <= mid else "r"].append((x, y))
        left = centroid(groups["l"], (8, 13))
        right = centroid(groups["r"], (13, 13))
        table.append((left, right))
    print('    "idle": [')
    for left, right in table:
        print(f"        ({left}, {right}),")
    print("    ],")


if __name__ == "__main__":
    main()
