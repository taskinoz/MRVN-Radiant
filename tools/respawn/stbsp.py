#!/usr/bin/env python3
"""Write and read Titanfall 2 STBSP (v8.0) material catalogues.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Layout from retail mp_coliseum.stbsp and the apex-to-titanfall-2 converter: a
392-byte header with six (offset, count) descriptors at byte 168, physical
block order 1,2,3,0,4,5, 24-byte material infos and spatial columns. Columns
cover 4x4 cells of 128 units. With resident (non-streamed) textures every
column is empty: 32 zero bytes with coverage scale FLT_MIN, as in retail.
"""
import math
import struct

MAGIC = 0xCB00CBB5
HEADER_SIZE = 392
CELL = 128.0
COLUMN_CELLS = 4
EMPTY_SCALE = struct.unpack("<f", struct.pack("<I", 0x00800000))[0]  # FLT_MIN


def write(path, materials, mins, maxs):
    """materials: [(name, guid)]; mins/maxs: world XY bounds to cover."""
    strings, infos = bytearray(), bytearray()
    for name, guid in sorted(materials):
        infos += struct.pack("<2IQ2I", len(strings), 0, guid, 0, 0)
        strings += name.encode("ascii") + b"\0"
    x0 = math.floor(mins[0] / CELL / COLUMN_CELLS) * COLUMN_CELLS
    y0 = math.floor(mins[1] / CELL / COLUMN_CELLS) * COLUMN_CELLS
    x1 = math.ceil(maxs[0] / CELL / COLUMN_CELLS) * COLUMN_CELLS
    y1 = math.ceil(maxs[1] / CELL / COLUMN_CELLS) * COLUMN_CELLS
    columns, payload = bytearray(), bytearray()
    for y in range(y0, y1, COLUMN_CELLS):
        for x in range(x0, x1, COLUMN_CELLS):
            columns += struct.pack("<QIf4h", len(payload), 32, EMPTY_SCALE, x, y, x + COLUMN_CELLS, y + COLUMN_CELLS)
            payload += bytes(32)
    blocks = [bytes(strings), bytes(infos), b"", b"", bytes(columns), bytes(payload)]
    counts = [len(strings), len(infos) // 24, 0, 0, len(columns) // 24, len(payload)]
    offsets, cursor = [0] * 6, HEADER_SIZE
    for i in (1, 2, 3, 0, 4, 5):
        offsets[i] = cursor
        cursor += len(blocks[i])
    header = bytearray(struct.pack("<I2H4iI2f", MAGIC, 8, 0, x0, y0, x1 - 1, y1 - 1, COLUMN_CELLS, CELL, CELL))
    header += bytes(168 - len(header))
    for offset, count in zip(offsets, counts):
        header += struct.pack("<2Q", offset, count)
    header += bytes(HEADER_SIZE - len(header))
    path.write_bytes(bytes(header) + b"".join(blocks[i] for i in (1, 2, 3, 0, 4, 5)))


def read(path):
    data = path.read_bytes()
    magic, major, minor = struct.unpack_from("<IHH", data)
    if magic != MAGIC or (major, minor) != (8, 0):
        raise ValueError("not a v8.0 STBSP")
    descriptors = [struct.unpack_from("<2Q", data, 168 + 16 * i) for i in range(6)]
    (string_at, string_bytes), (info_at, info_count) = descriptors[0], descriptors[1]
    if string_at + string_bytes > len(data) or info_at + info_count * 24 > len(data):
        raise ValueError("STBSP block outside the file")
    strings = data[string_at:string_at + string_bytes]
    materials = []
    for i in range(info_count):
        offset, _, guid, _, _ = struct.unpack_from("<2IQ2I", data, info_at + 24 * i)
        materials.append((strings[offset:strings.index(0, offset)].decode("ascii"), guid))
    column_at, column_count = descriptors[4]
    payload_at, payload_bytes = descriptors[5]
    columns = [struct.unpack_from("<QIf4h", data, column_at + 24 * i) for i in range(column_count)]
    for offset, length, *_ in columns:
        if offset + length > payload_bytes:
            raise ValueError("STBSP column outside its payload")
    return {"materials": materials, "columns": columns, "bounds": struct.unpack_from("<4i", data, 8)}
