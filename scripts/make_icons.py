"""Render the app icons in web/public from the logo geometry (stdlib only; rerun after a logo change).

Full-bleed squares so they also work as maskable icons: the play mark sits well inside the safe zone.
"""
from pathlib import Path
import struct
import zlib

GOLD, INK = (0xF5, 0xC4, 0x51), (0x1B, 0x14, 0x05)
TRIANGLE = ((12.5 / 32, 9.5 / 32), (12.5 / 32, 22.5 / 32), (22.5 / 32, 16 / 32))  # from Logo.tsx
SUPERSAMPLE = 4


def inside(x, y):
    (ax, ay), (bx, by), (cx, cy) = TRIANGLE
    d1 = (x - bx) * (ay - by) - (ax - bx) * (y - by)
    d2 = (x - cx) * (by - cy) - (bx - cx) * (y - cy)
    d3 = (x - ax) * (cy - ay) - (cx - ax) * (y - ay)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def render(size):
    rows = []
    for py in range(size):
        row = bytearray([0])  # PNG filter type 0
        for px in range(size):
            hits = sum(inside((px + (i + .5) / SUPERSAMPLE) / size, (py + (j + .5) / SUPERSAMPLE) / size)
                       for i in range(SUPERSAMPLE) for j in range(SUPERSAMPLE))
            t = hits / SUPERSAMPLE ** 2
            row += bytes(round(g * (1 - t) + k * t) for g, k in zip(GOLD, INK, strict=True))
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
