"""Render the app icons in web/public from the logo geometry (stdlib only; rerun after a logo change).

Full-bleed squares so they also work as maskable icons: the mark sits well inside the safe zone.
Geometry and colours match web/src/components/Logo.tsx and web/public/favicon.svg.
"""
from pathlib import Path
import struct
import zlib

START, END, WHITE = (0x2F, 0x80, 0xFF), (0x7A, 0x5C, 0xFF), (0xFF, 0xFF, 0xFF)
BARS = ((8.4, 3.0), (11.6, 8.4), (14.8, 14.0), (18.0, 8.4), (21.2, 3.0))  # (top, width) in 32-unit logo coordinates
X, HEIGHT, RADIUS = 11.0, 2.4, 1.2
SUPERSAMPLE = 4


def in_mark(x, y):
    """Inside one of the rounded bars (Logo.tsx)."""
    for top, width in BARS:
        if X <= x <= X + width and top <= y <= top + HEIGHT:
            cx = min(max(x, X + RADIUS), X + width - RADIUS)
            cy = min(max(y, top + RADIUS), top + HEIGHT - RADIUS)
            if (x - cx) ** 2 + (y - cy) ** 2 <= RADIUS ** 2:
                return True
    return False


def render(size):
    rows = []
    for py in range(size):
        row = bytearray([0])  # PNG filter type 0
        for px in range(size):
            t = (px + py) / (2 * (size - 1))  # diagonal gradient, as in the SVG
            base = [s + (e - s) * t for s, e in zip(START, END, strict=True)]
            cover = 0.0
            for i in range(SUPERSAMPLE):
                for j in range(SUPERSAMPLE):
                    x = (px + (i + .5) / SUPERSAMPLE) / size * 32
                    y = (py + (j + .5) / SUPERSAMPLE) / size * 32
                    cover += in_mark(x, y)
            a = cover / SUPERSAMPLE ** 2
            row += bytes(round(b * (1 - a) + w * a) for b, w in zip(base, WHITE, strict=True))
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
