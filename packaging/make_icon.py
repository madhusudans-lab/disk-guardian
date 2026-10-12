"""Draw packaging/icon.ico (a shield over a drive) with the standard library only.
Run: python packaging/make_icon.py"""
import struct
import zlib
from pathlib import Path


def shield(size):
    px = []
    c = size / 2
    for y in range(size):
        row = []
        for x in range(size):
            u, v = (x + 0.5) / size, (y + 0.5) / size
            # shield: flat top, straight sides, curved point at the bottom
            half = 0.38 if v < 0.55 else 0.38 * max(0.0, 1 - ((v - 0.55) / 0.37) ** 1.6)
            inside = 0.08 <= v <= 0.92 and abs(u - 0.5) <= half
            if not inside:
                row.append((0, 0, 0, 0))
                continue
            edge = half - abs(u - 0.5) < 0.04 or v < 0.12
            if edge:
                row.append((21, 101, 192, 255))
                continue
            # a white "drive" bar with a green light
            if 0.42 <= v <= 0.58 and abs(u - 0.5) <= 0.22:
                if (u - 0.64) ** 2 + (v - 0.5) ** 2 < 0.0012:
                    row.append((67, 200, 120, 255))
                else:
                    row.append((255, 255, 255, 255))
            else:
                row.append((30, 136, 229, 255))
        px.append(row)
    del c
    return px


def png(size):
    raw = b"".join(b"\x00" + b"".join(struct.pack("4B", *p) for p in row) for row in shield(size))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(sizes=(16, 24, 32, 48, 64, 128, 256)):
    images = [png(s) for s in sizes]
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    dirs = b""
    for s, data in zip(sizes, images):
        dirs += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return head + dirs + b"".join(images)


if __name__ == "__main__":
    out = Path(__file__).with_name("icon.ico")
    out.write_bytes(ico())
    print("wrote", out)
