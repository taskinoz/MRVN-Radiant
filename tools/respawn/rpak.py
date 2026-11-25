#!/usr/bin/env python3
"""Read decompressed Titanfall 2 (v7) RPaks: asset table and v12 materials.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Header and material layouts follow r-ex/RSX (cpakfile.h, material.h) as
documented by the apex-to-titanfall-2 converter. Input must be a separately
decompressed copy (e.g. rpak_ddecomp output); game files are never edited.
"""
import struct

HEADER_SIZE = 88
ASSET_SIZE = 72
MATERIAL_V12_SIZE = 208


class RPak:
    def __init__(self, path):
        self.data = data = path.read_bytes()
        magic, version, flags = struct.unpack_from("<4sHH", data)
        if magic != b"RPak" or version != 7:
            raise ValueError("expected a Titanfall 2 (v7) RPak")
        # Decompressors may keep the 0x100 flag; the decompressed size is decisive.
        decompressed_size = struct.unpack_from("<Q", data, 40)[0]
        if flags & 0x100 and len(data) != decompressed_size:
            raise ValueError("RPak is still compressed; decompress a copy first")
        streaming, segments, pages, patches = struct.unpack_from("<4H", data, 56)
        if patches:
            raise ValueError("patched RPaks are not supported")
        pointers, assets, guid_refs, dependencies, externals, external_bytes = struct.unpack_from("<6I", data, 64)
        offset = HEADER_SIZE + streaming + segments * 16
        page_sizes = [size for _, _, size in struct.iter_unpack("<3I", data[offset:offset + pages * 12])]
        offset += pages * 12 + pointers * 8
        self.assets = []
        for i in range(assets):
            at = offset + i * ASSET_SIZE
            self.assets.append({
                "guid": struct.unpack_from("<Q", data, at)[0],
                "header": struct.unpack_from("<2I", data, at + 16),
                "cpu": struct.unpack_from("<2I", data, at + 24),
                "size": struct.unpack_from("<I", data, at + 60)[0],
                "version": struct.unpack_from("<I", data, at + 64)[0],
                "type": data[at + 68:at + 72].decode("ascii"),
            })
        offset += assets * ASSET_SIZE + guid_refs * 8 + dependencies * 4 + externals * 4 + external_bytes
        self.pages = []
        for size in page_sizes:
            if offset + size > len(data):
                raise ValueError("RPak page exceeds the file")
            self.pages.append((offset, size))
            offset += size
        if offset != len(data):
            raise ValueError("RPak page data does not end at the end of the file")

    def address(self, pointer):
        page, offset = pointer
        if page == 0xFFFFFFFF:
            return None
        base, size = self.pages[page]
        if offset >= size:
            raise ValueError("invalid RPak page pointer")
        return base + offset

    def string(self, pointer):
        address = self.address(pointer) if pointer != (0, 0) else None
        if address is None:
            return ""
        return self.data[address:self.data.index(0, address)].decode("ascii")

    def materials(self):
        """Yield (asset, name) for every v12 material."""
        for asset in self.assets:
            if asset["type"] == "matl" and asset["version"] == 12:
                header = self.address(asset["header"])
                yield asset, self.string(struct.unpack_from("<2I", self.data, header + 24)).replace("\\", "/")

    def material(self, asset):
        """RePak-style material description and uber buffer for a v12 material."""
        if asset["version"] != 12 or asset["size"] != MATERIAL_V12_SIZE:
            raise ValueError("expected a v12 material")
        at = self.address(asset["header"])
        header = self.data[at:at + MATERIAL_V12_SIZE]
        pointer = lambda offset: struct.unpack_from("<2I", header, offset)
        u32 = lambda offset: struct.unpack_from("<I", header, offset)[0]
        u64 = lambda offset: struct.unpack_from("<Q", header, offset)[0]
        textures_at, streaming_at = self.address(pointer(152)), self.address(pointer(160))
        if textures_at is None or streaming_at is None or not 0 <= streaming_at - textures_at <= 1024:
            raise ValueError("invalid material texture table")
        textures = struct.unpack_from(f"<{(streaming_at - textures_at) // 8}Q", self.data, textures_at)
        blend = struct.unpack_from("<5I2H", header, 80)
        cpu = self.address(asset["cpu"])
        uber_at = self.address(struct.unpack_from("<2I", self.data, cpu))
        uber_size, uber_flags = struct.unpack_from("<2I", self.data, cpu + 8)
        width, height, depth = struct.unpack_from("<3H", header, 200)
        hexed = lambda value: f"0x{value:X}"
        spec = {
            "name": self.string(pointer(24)).replace("\\", "/"),
            "width": width, "height": height, "depth": depth,
            "glueFlags": hexed(u32(192)), "glueFlags2": hexed(u32(196)),
            "blendStates": [hexed(v) for v in blend[:4]], "blendStateMask": hexed(blend[4]),
            "depthStencilFlags": hexed(blend[5]), "rasterizerFlags": hexed(blend[6]),
            "uberBufferFlags": hexed(uber_flags), "features": hexed(u32(184)),
            "samplers": hexed(u32(170)),
            "surfaceProp": self.string(pointer(32)), "surfaceProp2": self.string(pointer(40)),
            "shaderType": "wld", "shaderSet": hexed(u64(144)),
            "$textures": {str(i): hexed(v) for i, v in enumerate(textures) if v},
        }
        for field, offset in (("depthShadowMaterial", 48), ("depthPrepassMaterial", 56),
                              ("depthVSMMaterial", 64), ("colpassMaterial", 72)):
            spec["$" + field] = hexed(u64(offset))
        return spec, self.data[uber_at:uber_at + uber_size]
