"""Bounded reader for unpatched, decompressed Apex S3 v8 RPaks.

Original code, GPL-2.0-or-later. Layout references: r-ex/RePak rpak.h and
material.h; native installed S3 lobby. No decompression or patch application.
"""
import struct
from pathlib import Path


class ApexRPak:
    def __init__(self, path):
        self.data = b = Path(path).read_bytes()
        if len(b) < 128 or len(b) > 512 * 1024 * 1024:
            raise ValueError('RPak size outside supported range')
        if struct.unpack_from('<4sH', b) != (b'RPak', 8):
            raise ValueError('Expected Apex v8 RPak')
        if len(b) != struct.unpack_from('<Q', b, 48)[0]:
            raise ValueError('Expected decompressed RPak')
        sp, op, slabs, pages, patch, _ = struct.unpack_from('<6H', b, 72)
        if patch:
            raise ValueError('Patched RPaks are not supported')
        pointers, assets, uses, dependents = struct.unpack_from('<4I', b, 84)
        at = 128 + sp + op + slabs * 16
        sizes = [x[2] for x in struct.iter_unpack('<3I', self.span(at, pages * 12))]
        at += pages * 12 + pointers * 8
        self.assets = []
        for i in range(assets):
            row = self.span(at + i * 80, 80)
            self.assets.append(dict(guid=struct.unpack_from('<Q', row)[0],
                                    header=struct.unpack_from('<2I', row, 16),
                                    cpu=struct.unpack_from('<2I', row, 24),
                                    size=struct.unpack_from('<I', row, 68)[0],
                                    version=struct.unpack_from('<I', row, 72)[0],
                                    type=row[76:80].decode('ascii')))
        at += assets * 80 + uses * 8 + dependents * 4
        self.pages = []
        for size in sizes:
            self.span(at, size)
            self.pages.append((at, size))
            at += size
        if at != len(b):
            raise ValueError('Page data does not end at file end')

    def span(self, at, size):
        if at < 0 or size < 0 or at > len(self.data) or size > len(self.data) - at:
            raise ValueError('RPak range outside file')
        return self.data[at:at + size]

    def address(self, pointer, size=1):
        page, offset = pointer
        if page == 0xffffffff:
            return None
        if page >= len(self.pages):
            raise ValueError('Page index outside RPak')
        base, length = self.pages[page]
        if offset > length or size > length - offset:
            raise ValueError('Page pointer range outside page')
        return base + offset

    def string(self, pointer):
        if pointer == (0, 0):
            return ''
        at = self.address(pointer)
        if at is None:
            return ''
        page, offset = pointer
        end = self.data.index(0, at, self.pages[page][0] + self.pages[page][1])
        return self.data[at:end].decode('ascii').replace('\\', '/')

    def materials(self):
        for asset in self.assets:
            if asset['type'] == 'matl' and asset['version'] == 15:
                at = self.address(asset['header'], 256)
                yield asset, self.string(struct.unpack_from('<2I', self.data, at + 24))

    def material(self, asset):
        if (asset['type'], asset['version'], asset['size']) != ('matl', 15, 256):
            raise ValueError('Expected v15 material header')
        h = self.span(self.address(asset['header'], 256), 256)
        ptr = lambda off: struct.unpack_from('<2I', h, off)
        u32 = lambda off: struct.unpack_from('<I', h, off)[0]
        u64 = lambda off: struct.unpack_from('<Q', h, off)[0]
        tp, to = ptr(96)
        ep, eo = ptr(104)
        if tp != ep or eo < to or (eo - to) % 8 or eo - to > 1024:
            raise ValueError('Unsupported material texture table')
        tx = struct.unpack('<' + 'Q' * ((eo - to) // 8), self.span(self.address((tp, to), eo - to), eo - to))
        cp = self.address(asset['cpu'], 16)
        up = struct.unpack_from('<2I', self.data, cp)
        size = struct.unpack_from('<I', self.data, cp + 8)[0]
        uber = self.span(self.address(up, size), size)
        types = ('rgdu', 'rgdp', 'rgdc', 'sknu', 'sknp', 'sknc', 'wldu', 'wldc', 'ptcu', 'ptcs')
        if h[242] >= len(types):
            raise ValueError('Unsupported material shader type')
        width, height, depth = struct.unpack_from('<3H', h, 114)
        blend = struct.unpack_from('<9I2H', h, 144)
        spec = dict(name=self.string(ptr(24)), width=width, height=height, depth=depth,
                    glueFlags=hex(u32(136)), glueFlags2=hex(u32(140)),
                    blendStates=[hex(x) for x in blend[:8]], blendStateMask=hex(blend[8]),
                    depthStencilFlags=hex(blend[9]), rasterizerFlags=hex(blend[10]),
                    uberBufferFlags=h[243], features=hex(u32(128)), samplers=hex(u64(120)),
                    surfaceProp=self.string(ptr(32)), surfaceProp2=self.string(ptr(40)),
                    shaderType=types[h[242]], shaderSet=hex(u64(88)))
        spec['$textures'] = {str(i): hex(x) for i, x in enumerate(tx) if x}
        for field, off in (('depthShadowMaterial', 48), ('depthPrepassMaterial', 56),
                           ('depthVSMMaterial', 64), ('depthShadowTightMaterial', 72), ('colpassMaterial', 80)):
            spec['$' + field] = hex(u64(off))
        return spec, uber
