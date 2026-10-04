"""Minimal QR code encoder (byte mode, error-correction level M, versions 1-10) rendering to SVG.

Standard library only, so the QR code needs no extra dependency. Enough for a join URL (up to 213 bytes).
Follows ISO/IEC 18004; structure after Project Nayuki's reference encoder (MIT).
"""

# Error-correction level M, versions 1-10: EC codewords per block and number of blocks.
EC_PER_BLOCK = (10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
BLOCKS = (1, 1, 1, 2, 2, 4, 4, 4, 5, 5)
FORMAT_M = 0  # format-information bits for level M
MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


def _gf_mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 2)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _raw_modules(version):
    result = (16 * version + 128) * version + 64
    if version >= 2:
        n = version // 7 + 2
        result -= (25 * n - 10) * n - 55
        if version >= 7:
            result -= 36
    return result


def data_capacity(version):
    """Data codewords (bytes) available at level M."""
    return _raw_modules(version) // 8 - EC_PER_BLOCK[version - 1] * BLOCKS[version - 1]


def _alignment_positions(version, size):
    if version == 1:
        return []
    n = version // 7 + 2
    step = (version * 8 + n * 3 + 5) // (n * 4 - 4) * 2
    return [6, *sorted(size - 7 - i * step for i in range(n - 1))]


def _bit(value, i):
    return (value >> i) & 1 == 1


class _Builder:
    def __init__(self, version):
        self.version, self.size = version, version * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.function = [[False] * self.size for _ in range(self.size)]

    def set_function(self, x, y, dark):
        self.dark[y][x] = dark
        self.function[y][x] = True

    def draw_function_patterns(self):
        size = self.size
        for i in range(size):
            self.set_function(6, i, i % 2 == 0)
            self.set_function(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        self.set_function(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        positions = _alignment_positions(self.version, size)
        last = len(positions) - 1
        for i, cx in enumerate(positions):
            for j, cy in enumerate(positions):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_function(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)  # reserve the format areas; real bits are drawn after masking
        if self.version >= 7:
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.version << 12 | rem
            for i in range(18):
                a, b = size - 11 + i % 3, i // 3
                self.set_function(a, b, _bit(bits, i))
                self.set_function(b, a, _bit(bits, i))

    def draw_format(self, mask):
        data = FORMAT_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        size = self.size
        for i in range(6):
            self.set_function(8, i, _bit(bits, i))
        self.set_function(8, 7, _bit(bits, 6))
        self.set_function(8, 8, _bit(bits, 7))
        self.set_function(7, 8, _bit(bits, 8))
        for i in range(9, 15):
            self.set_function(14 - i, 8, _bit(bits, i))
        for i in range(8):
            self.set_function(size - 1 - i, 8, _bit(bits, i))
        for i in range(8, 15):
            self.set_function(8, size - 15 + i, _bit(bits, i))
        self.set_function(8, size - 8, True)  # always-dark module

    def draw_codewords(self, codewords):
        size, i = self.size, 0
        for right in range(size - 1, 0, -2):
            if right <= 6:
                right -= 1
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    y = size - 1 - vert if (right + 1) & 2 == 0 else vert
                    if not self.function[y][x] and i < len(codewords) * 8:
                        self.dark[y][x] = _bit(codewords[i >> 3], 7 - (i & 7))
                        i += 1

    def apply_mask(self, mask):
        test = MASKS[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.function[y][x] and test(x, y):
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self):
        size, dark, score = self.size, self.dark, 0
        lines = dark + [list(col) for col in zip(*dark, strict=True)]
        finder = ([True, False, True, True, True, False, True, False, False, False, False],
                  [False, False, False, False, True, False, True, True, True, False, True])
        for line in lines:
            run, prev = 0, None
            for cell in line:
                run = run + 1 if cell == prev else 1
                prev = cell
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
            padded = [False] * 4 + line + [False] * 4  # the quiet zone counts as light
            score += 40 * sum(padded[i:i + 11] in finder for i in range(len(padded) - 10))
        for y in range(size - 1):
            for x in range(size - 1):
                if dark[y][x] == dark[y][x + 1] == dark[y + 1][x] == dark[y + 1][x + 1]:
                    score += 3
        total, count = size * size, sum(map(sum, dark))
        return score + ((abs(count * 20 - total * 10) + total - 1) // total - 1) * 10


def _codewords(data, version):
    capacity = data_capacity(version)
    bits = [0, 1, 0, 0]  # byte mode
    count_bits = 8 if version < 10 else 16
    bits += [(len(data) >> i) & 1 for i in reversed(range(count_bits))]
    for b in data:
        bits += [(b >> i) & 1 for i in reversed(range(8))]
    bits += [0] * min(4, capacity * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    codewords = [int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(codewords) < capacity:
        codewords.append(pad)
        pad ^= 0xEC ^ 0x11

    blocks_n, ec_len = BLOCKS[version - 1], EC_PER_BLOCK[version - 1]
    raw = _raw_modules(version) // 8
    short_n, short_len = blocks_n - raw % blocks_n, raw // blocks_n
    divisor, blocks, k = _rs_divisor(ec_len), [], 0
    for i in range(blocks_n):
        length = short_len - ec_len + (0 if i < short_n else 1)
        dat = codewords[k:k + length]
        k += length
        block = dat + _rs_remainder(dat, divisor)
        if i < short_n:
            block.insert(short_len - ec_len, None)  # placeholder so blocks interleave evenly
        blocks.append(block)
    return [block[i] for i in range(len(blocks[0])) for block in blocks if block[i] is not None]


def encode(text):
    """Return the QR module matrix (list of rows of bools, True = dark) for text."""
    data = text.encode('utf-8')
    for version in range(1, 11):
        header_bits = 4 + (8 if version < 10 else 16)
        if header_bits + 8 * len(data) <= data_capacity(version) * 8:
            break
    else:
        raise ValueError('Text is too long for this QR encoder (max 213 bytes)')
    builder = _Builder(version)
    builder.draw_function_patterns()
    builder.draw_codewords(_codewords(data, version))
    best = None
    for mask in range(8):
        builder.apply_mask(mask)
        builder.draw_format(mask)
        score = builder.penalty()
        if best is None or score < best[0]:
            best = (score, mask)
        builder.apply_mask(mask)  # XOR again to undo
    builder.apply_mask(best[1])
    builder.draw_format(best[1])
    return builder.dark


def svg(text, border=4):
    """SVG image of the QR code for text, with the standard 4-module quiet zone."""
    matrix = encode(text)
    size = len(matrix) + 2 * border
    path = ''.join(f'M{x + border},{y + border}h1v1h-1z'
                   for y, row in enumerate(matrix) for x, dark in enumerate(row) if dark)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
            f'<rect width="{size}" height="{size}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')
