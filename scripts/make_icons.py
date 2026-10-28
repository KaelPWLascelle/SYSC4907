"""Render the app icons in web/public from the mark's geometry (stdlib only; rerun after a mark change).

The mark is the i of "flicks" (web/src/components/Logo.tsx): a white stem and its dot drawn as a warm bulb
with a soft glow, on black. Full-bleed squares so they also work as maskable icons: the mark sits well
inside the safe zone. Geometry and colours match web/public/favicon.svg.
"""
import math
from pathlib import Path
import struct
import zlib

BLACK, WHITE, BULB = (0, 0, 0), (0xFF, 0xFF, 0xFF), (0xFF, 0xE2, 0xA8)
STEM = (14.0, 13.5, 4.0, 11.5, 2.0)  # x, y, width, height, corner radius in 32-unit coordinates
DOT, DOT_R, GLOW_R = (16.0, 9.0), 2.6, 7.0
SUPERSAMPLE = 4


def in_stem(x, y):
    sx, sy, w, h, r = STEM
    if not (sx <= x <= sx + w and sy <= y <= sy + h):
        return False
    cx = min(max(x, sx + r), sx + w - r)
    cy = min(max(y, sy + r), sy + h - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2


def render(size):
    rows = []
    for py in range(size):
        row = bytearray([0])  # PNG filter type 0
        for px in range(size):
            stem = dot = 0.0
            for i in range(SUPERSAMPLE):
                for j in range(SUPERSAMPLE):
                    x = (px + (i + .5) / SUPERSAMPLE) / size * 32
                    y = (py + (j + .5) / SUPERSAMPLE) / size * 32
                    stem += in_stem(x, y)
                    dot += math.dist((x, y), DOT) <= DOT_R
            stem /= SUPERSAMPLE ** 2
            dot /= SUPERSAMPLE ** 2
            # The glow fades from the bulb outward, as in the SVG's radial gradient.
            d = math.dist(((px + .5) / size * 32, (py + .5) / size * 32), DOT)
            glow = max(0.0, 1 - d / GLOW_R) * 0.55
            base = [b + (u - b) * glow for b, u in zip(BLACK, BULB, strict=True)]
            base = [b + (u - b) * dot for b, u in zip(base, BULB, strict=True)]
            row += bytes(round(b + (w - b) * stem) for b, w in zip(base, WHITE, strict=True))
        rows.append(bytes(row))
    return png(size, b''.join(rows))


def png(size, raw):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF)
    header = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')


if __name__ == '__main__':
    out = Path(__file__).resolve().parents[1]/'web'/'public'
    for name, size in (('icon-192.png', 192), ('icon-512.png', 512), ('apple-touch-icon.png', 180)):
        (out/name).write_bytes(render(size))
        print(f'wrote {name}')
