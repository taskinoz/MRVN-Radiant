"""Small Java Anvil/NBT reader for local Minecraft map conversion.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Supports palette sections (1.13+) including 1.18 negative heights.
"""
import gzip
import struct
import zlib
import zipfile
from pathlib import Path


class NBT:
    def __init__(self, data):
        self.data = memoryview(data)
        self.pos = 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError('truncated NBT')
        b = self.data[self.pos:self.pos+n]
        self.pos += n
        return b

    def number(self, fmt):
        return struct.unpack('>'+fmt, self.take(struct.calcsize('>'+fmt)))[0]

    def string(self):
        return bytes(self.take(self.number('H'))).decode('utf-8', errors='replace')

    def tag(self, kind):
        if kind in range(1, 7):
            return self.number({1:'b',2:'h',3:'i',4:'q',5:'f',6:'d'}[kind])
        if kind == 7:
            return bytes(self.take(self.number('i')))
        if kind == 8:
            return self.string()
        if kind == 9:
            t, n = self.number('B'), self.number('i')
            if not 0 <= n <= 10000000: raise ValueError('invalid NBT list')
            return [self.tag(t) for _ in range(n)]
        if kind == 10:
            result = {}
            while True:
                t = self.number('B')
                if not t: return result
                name = self.string()
                result[name] = self.tag(t)
        if kind in (11, 12):
            n = self.number('i')
            if not 0 <= n <= 10000000: raise ValueError('invalid NBT array')
            return [self.number('i' if kind == 11 else 'Q') for _ in range(n)]
        raise ValueError('unknown NBT tag '+str(kind))


def read_nbt(data):
    n = NBT(data)
    kind = n.number('B')
    n.string()
    return n.tag(kind)


def chunks(archive, bounds=None):
    """Yield overworld chunks without extracting user-controlled ZIP paths."""
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if not any(n.endswith('.mca') for n in names) and any(n.endswith('.mcr') for n in names):
            raise ValueError('world saved before Minecraft 1.2 (McRegion .mcr files); '
                             'open it in Minecraft 1.2 to 1.12 first, then run tools/respawn/upgrade_minecraft_world.py')
        for name in names:
            path = Path(name)
            if path.parent.name != 'region' or path.suffix != '.mca': continue
            if any(p in ('DIM1', 'DIM-1') for p in path.parts): continue
            _, rx, rz = path.stem.split('.')
            rx, rz = int(rx), int(rz)
            if bounds and not (bounds[0]-511 <= rx*512 <= bounds[3] and
                               bounds[2]-511 <= rz*512 <= bounds[5]): continue
            data = z.read(name)
            if len(data) < 8192: raise ValueError('truncated region')
            for i in range(1024):
                cx, cz = rx*512+(i%32)*16, rz*512+(i//32)*16
                if bounds and not (bounds[0]-15 <= cx <= bounds[3] and
                                   bounds[2]-15 <= cz <= bounds[5]): continue
                offset = int.from_bytes(data[i*4:i*4+3], 'big')*4096
                if not offset: continue
                size = int.from_bytes(data[offset:offset+4], 'big')
                if size < 1 or offset+4+size > len(data): raise ValueError('invalid chunk extent')
                compression = data[offset+4]
                payload = data[offset+5:offset+4+size]
                if compression == 1: payload = gzip.decompress(payload)
                elif compression == 2: payload = zlib.decompress(payload)
                elif compression != 3: raise ValueError('unsupported chunk compression')
                root = read_nbt(payload)
                yield root.get('Level', root), root.get('DataVersion', 0)


def sections(archive, bounds=None):
    for chunk, version in chunks(archive, bounds):
        if bounds and not (bounds[0]-15 <= chunk['xPos']*16 <= bounds[3] and
                           bounds[2]-15 <= chunk['zPos']*16 <= bounds[5]): continue
        for sec in chunk.get('sections', chunk.get('Sections', [])):
            if bounds and not bounds[1]-15 <= sec['Y']*16 <= bounds[4]: continue
            bs = sec.get('block_states', {})
            palette = bs.get('palette', sec.get('Palette', []))
            if not palette and 'Blocks' in sec:
                raise ValueError('world saved before Minecraft 1.13 (numeric block IDs); '
                                 'upgrade it first with tools/respawn/upgrade_minecraft_world.py')
            if not palette: continue
            if len(palette) == 1:
                yield (chunk['xPos']*16, sec['Y']*16, chunk['zPos']*16), palette, [0]*4096
                continue
            words = bs.get('data', sec.get('BlockStates', []))
            bits = max(4, (len(palette)-1).bit_length())
            mask = (1 << bits)-1
            padded = version >= 2529
            values = []
            for i in range(4096):
                if len(palette) == 1: index = 0
                elif padded:
                    per = 64//bits
                    index = (words[i//per] >> ((i % per)*bits)) & mask
                else:
                    word, shift = divmod(i*bits, 64)
                    index = words[word] >> shift
                    if shift+bits > 64: index |= words[word+1] << (64-shift)
                    index &= mask
                if index >= len(palette): raise ValueError('invalid palette index')
                values.append(index)
            yield (chunk['xPos']*16, sec['Y']*16, chunk['zPos']*16), palette, values


def level(archive):
    with zipfile.ZipFile(archive) as z:
        name = next(n for n in z.namelist() if Path(n).name == 'level.dat')
        return read_nbt(gzip.decompress(z.read(name)))['Data']
