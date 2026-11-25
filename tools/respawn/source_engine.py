"""Readers for Source engine content: VPK archives, BSP v19-v21, VMT and VTF.

Only what a map port needs: the brush list, displacements, entities, textures
and the map's embedded pakfile.
"""
from collections import namedtuple
import io
import lzma
import math
from pathlib import Path
import re
import struct
import zipfile

import numpy as np
from PIL import Image


class VPK:
    """A `*_dir.vpk` and its numbered archives, indexed by lower-case path."""

    def __init__(self, path):
        self.path = Path(path); self.entries = {}
        data = self.path.read_bytes()
        signature, version, tree = struct.unpack_from('<3I', data)
        if signature != 0x55AA1234: raise ValueError(f'{path} is not a VPK')
        header = 12 if version == 1 else 28
        self.data_start = header + tree; self.dir_data = data
        p = header
        def string():
            nonlocal p
            end = data.index(b'\0', p); s = data[p:end].decode('latin-1'); p = end+1; return s
        while (ext := string()):
            while (folder := string()):
                while (name := string()):
                    crc, preload, archive, offset, length, terminator = struct.unpack_from('<IHHIIH', data, p); p += 18
                    full = (f'{folder}/' if folder != ' ' else '')+name+'.'+ext
                    self.entries[full.lower()] = (archive, offset, length, data[p:p+preload]); p += preload

    def read(self, name):
        archive, offset, length, preload = self.entries[name.lower()]
        if not length: return preload
        if archive == 0x7FFF: return preload+self.dir_data[self.data_start+offset:self.data_start+offset+length]
        part = self.path.with_name(self.path.name.replace('_dir.vpk', f'_{archive:03d}.vpk'))
        with part.open('rb') as f:
            f.seek(offset); return preload+f.read(length)


class Content:
    """Search path for game files: the map's pakfile first, then loose files, then VPKs."""

    def __init__(self, roots, pakfile=None):
        self.pakfile = pakfile; self.roots = [Path(r) for r in roots]; self.vpks = []
        for root in self.roots:
            for vpk in sorted(root.glob('*_dir.vpk')):
                if 'sound' not in vpk.name: self.vpks.append(VPK(vpk))

    def read(self, name):
        name = name.replace('\\', '/').lower()
        if self.pakfile:
            for info in self.pakfile.infolist():
                if info.filename.lower() == name: return self.pakfile.read(info)
        for root in self.roots:
            if (root/name).is_file(): return (root/name).read_bytes()
        for vpk in self.vpks:
            if name in vpk.entries: return vpk.read(name)
        raise KeyError(name)


Brush = namedtuple('Brush', 'contents sides')
Side = namedtuple('Side', 'normal dist texinfo dispinfo bevel')
TexInfo = namedtuple('TexInfo', 's t flags material')
Displacement = namedtuple('Displacement', 'power corners start rows texinfo normal')

# Lump numbers.
ENTITIES, PLANES, TEXDATA, VERTEXES, NODES, TEXINFO, FACES, LEAFS = 0, 1, 2, 3, 5, 6, 7, 10
EDGES, SURFEDGES, MODELS, LEAFBRUSHES, BRUSHES, BRUSHSIDES = 12, 13, 14, 17, 18, 19
DISPINFO, DISP_VERTS, GAME_LUMP, PAKFILE, TEXDATA_STRINGS, TEXDATA_TABLE = 26, 33, 35, 40, 43, 44

CONTENTS_SOLID, CONTENTS_WINDOW, CONTENTS_GRATE, CONTENTS_WATER = 0x1, 0x2, 0x8, 0x20
CONTENTS_PLAYERCLIP, CONTENTS_LADDER = 0x10000, 0x20000000
SURF_SKY2D, SURF_SKY, SURF_NODRAW, SURF_HINT, SURF_SKIP = 0x2, 0x4, 0x80, 0x100, 0x200


def decompress(data):
    """Valve's LZMA lump wrapper: 'LZMA', size, compressed size, 5 property bytes."""
    if data[:4] != b'LZMA': return data
    size, packed = struct.unpack_from('<II', data, 4)
    props = data[12]; dictionary = struct.unpack_from('<I', data, 13)[0]
    lc, lp, pb = props % 9, props//9 % 5, props//45
    filters = [{'id': lzma.FILTER_LZMA1, 'lc': lc, 'lp': lp, 'pb': pb, 'dict_size': dictionary}]
    return lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=filters).decompress(data[17:17+packed])[:size]


def parse_entities(text):
    entities = []
    for block in re.findall(r'\{(.*?)\}', text, re.S):
        e = {}
        for k, v in re.findall(r'"([^"]*)"\s+"([^"]*)"', block):
            e.setdefault(k, v)
        entities.append(e)
    return entities


class BSP:
    def __init__(self, path):
        self.path = Path(path); data = self.path.read_bytes()
        magic, self.version = struct.unpack_from('<4si', data)
        if magic != b'VBSP' or not 19 <= self.version <= 21: raise ValueError(f'{path}: not a Source BSP v19-21')
        self.lumps = {}; self.lump_versions = {}
        for i in range(64):
            offset, length, version, _ = struct.unpack_from('<4i', data, 8+16*i)
            if i == GAME_LUMP or i == PAKFILE: self.lumps[i] = data[offset:offset+length]
            else: self.lumps[i] = decompress(data[offset:offset+length])
            self.lump_versions[i] = version
        self.entities = parse_entities(self.lumps[ENTITIES].decode('latin-1'))
        self.planes = [(p[:3], p[3]) for p in struct.iter_unpack('<4fi', self.lumps[PLANES])]
        table = [t[0] for t in struct.iter_unpack('<i', self.lumps[TEXDATA_TABLE])]
        strings = self.lumps[TEXDATA_STRINGS]
        names = [strings[o:strings.index(b'\0', o)].decode('latin-1') for o in table]
        self.texdata = [(names[t[3]], t[4], t[5]) for t in struct.iter_unpack('<3f5i', self.lumps[TEXDATA])]
        self.texinfo = []
        for t in struct.iter_unpack('<16f2i', self.lumps[TEXINFO]):
            self.texinfo.append(TexInfo(t[0:4], t[4:8], t[16], self.texdata[t[17]][0] if t[17] >= 0 else None))
        self.brushes = []
        sides = list(struct.iter_unpack('<HhhH' if self.version < 21 else '<Hhhbb', self.lumps[BRUSHSIDES]))
        for first, count, contents in struct.iter_unpack('<3i', self.lumps[BRUSHES]):
            out = []
            for s in sides[first:first+count]:
                normal, dist = self.planes[s[0]]
                out.append(Side(normal, dist, s[1], s[2], bool(s[3])))
            self.brushes.append(Brush(contents, out))
        self.models = [m for m in struct.iter_unpack('<9f3i', self.lumps[MODELS])]
        self.nodes = list(struct.iter_unpack('<3i6h2H2h', self.lumps[NODES]))
        leaf_size = 56 if self.lump_versions[LEAFS] == 0 else 32
        self.leafs = []
        for i in range(0, len(self.lumps[LEAFS]), leaf_size):
            contents, cluster, area_flags = struct.unpack_from('<ihh', self.lumps[LEAFS], i)
            bounds = struct.unpack_from('<6h', self.lumps[LEAFS], i+8)
            first, count = struct.unpack_from('<2H', self.lumps[LEAFS], i+24)
            self.leafs.append((contents, area_flags & 0x1FF, first, count, cluster, bounds))
        self.leafbrushes = [b[0] for b in struct.iter_unpack('<H', self.lumps[LEAFBRUSHES])]
        self.pakfile = zipfile.ZipFile(io.BytesIO(self.lumps[PAKFILE])) if self.lumps[PAKFILE] else None

    def model_leafs(self, model):
        stack = [self.models[model][9]]; leafs = []
        while stack:
            node = stack.pop()
            if node < 0: leafs.append(-1-node); continue
            stack += self.nodes[node][1:3]
        return leafs

    def model_brushes(self, model):
        keep = set()
        for leaf in self.model_leafs(model):
            contents, area, first, count = self.leafs[leaf][:4]
            keep.update(self.leafbrushes[first:first+count])
        return sorted(keep)

    @staticmethod
    def brush_bounds(brush):
        """Bounds from the axial sides every compiled brush carries."""
        lo, hi = [None]*3, [None]*3
        for side in brush.sides:
            for axis in range(3):
                if side.normal[axis] == 1: hi[axis] = side.dist
                elif side.normal[axis] == -1: lo[axis] = -side.dist
        return lo, hi

    def skybox_brushes(self, brushes):
        """The 3D skybox room: the smallest group of touching brushes whose bounds hold the sky_camera."""
        camera = next((e for e in self.entities if e.get('classname') == 'sky_camera'), None)
        if not camera: return set()
        point = np.array(tuple(map(float, camera['origin'].split())))
        boxes = np.array([sum(self.brush_bounds(self.brushes[i]), []) for i in brushes], dtype=float)
        lo, hi = boxes[:, :3], boxes[:, 3:]
        touching = np.all((lo[:, None] <= hi[None]+1) & (lo[None] <= hi[:, None]+1), axis=2)
        group = np.full(len(brushes), -1)
        for start in range(len(brushes)):
            if group[start] >= 0: continue
            group[start] = start; pending = [start]
            while pending:
                near = np.nonzero(touching[pending.pop()] & (group < 0))[0]
                group[near] = start; pending += near.tolist()
        best = None
        for g in set(group.tolist()):
            members = group == g
            glo, ghi = lo[members].min(0), hi[members].max(0)
            if np.all(glo <= point) and np.all(point <= ghi) and (best is None or np.prod(ghi-glo) < best[0]):
                best = (np.prod(ghi-glo), members)
        if best is None or best[1].sum() > len(brushes)/2: return set()
        return {b for b, m in zip(brushes, best[1]) if m}

    def visible_clusters(self, point):
        """Clusters in the PVS of the leaf holding a point."""
        cluster = self.leafs[self.leaf_at(point)][4]
        vis = self.lumps[4]
        if cluster < 0 or not vis: return set()
        count = struct.unpack_from('<i', vis)[0]
        p = struct.unpack_from('<i', vis, 4+8*cluster)[0]; out = set(); c = 0
        while c < count:
            byte = vis[p]; p += 1
            if byte == 0:
                c += 8*vis[p]; p += 1; continue
            for bit in range(8):
                if byte & (1 << bit) and c+bit < count: out.add(c+bit)
            c += 8
        return out

    def leaf_at(self, point):
        node = self.models[0][9]
        while node >= 0:
            planenum, front, back = self.nodes[node][:3]
            normal, dist = self.planes[planenum]
            node = front if sum(a*b for a, b in zip(normal, point))-dist >= 0 else back
        return -1-node

    def displacements(self):
        verts = list(struct.iter_unpack('<5f', self.lumps[DISP_VERTS]))
        points = [struct.unpack_from('<3f', self.lumps[VERTEXES], i) for i in range(0, len(self.lumps[VERTEXES]), 12)]
        edges = list(struct.iter_unpack('<2H', self.lumps[EDGES]))
        surfedges = [s[0] for s in struct.iter_unpack('<i', self.lumps[SURFEDGES])]
        faces = list(struct.iter_unpack('<HBBihhhh4BiF2i2iiHHI'.replace('F', 'f'), self.lumps[FACES]))
        out = []
        for i in range(0, len(self.lumps[DISPINFO]), 176):
            start = struct.unpack_from('<3f', self.lumps[DISPINFO], i)
            vert_start, _, power = struct.unpack_from('<3i', self.lumps[DISPINFO], i+12)
            face = faces[struct.unpack_from('<H', self.lumps[DISPINFO], i+36)[0]]
            corners = []
            for e in surfedges[face[3]:face[3]+face[4]]:
                corners.append(points[edges[e][0]] if e >= 0 else points[edges[-e][1]])
            # Corners start at the one nearest the displacement's start position.
            first = min(range(4), key=lambda k: sum((a-b)**2 for a, b in zip(corners[k], start)))
            corners = corners[first:]+corners[:first]
            n = (1 << power)+1; rows = []
            for y in range(n):
                row = []
                for x in range(n):
                    vx, vy, vz, dist, alpha = verts[vert_start+y*n+x]
                    a = [c0+(c3-c0)*y/(n-1) for c0, c3 in zip(corners[0], corners[1])]
                    b = [c1+(c2-c1)*y/(n-1) for c1, c2 in zip(corners[3], corners[2])]
                    base = [p+(q-p)*x/(n-1) for p, q in zip(a, b)]
                    row.append(tuple(p+v*dist for p, v in zip(base, (vx, vy, vz))))
                rows.append(row)
            normal = self.planes[face[0]][0]
            if face[1]: normal = tuple(-v for v in normal)
            out.append(Displacement(power, corners, start, rows, face[5], normal))
        return out

    def static_props(self):
        """(model path, origin, angles, solid, skin) for each static prop."""
        data = self.lumps[GAME_LUMP]
        if not data: return []
        for i in range(struct.unpack_from('<i', data)[0]):
            ident, flags, version, offset, length = struct.unpack_from('<4sHHii', data, 4+16*i)
            if ident != b'prps': continue
            with self.path.open('rb') as f:
                f.seek(offset); lump = f.read(length)
            if flags & 1: lump = decompress(lump)
            count = struct.unpack_from('<i', lump)[0]
            names = [lump[4+128*k:4+128*k+128].split(b'\0')[0].decode('latin-1') for k in range(count)]
            p = 4+128*count; p += 4+2*struct.unpack_from('<i', lump, p)[0]
            count = struct.unpack_from('<i', lump, p)[0]; p += 4
            if not count: return []
            # Entry size varies by version; the shared prefix is all a port needs.
            size = (len(lump)-p)//count; out = []
            for k in range(count):
                o = p+size*k
                origin = struct.unpack_from('<3f', lump, o); angles = struct.unpack_from('<3f', lump, o+12)
                model, = struct.unpack_from('<H', lump, o+24); solid, = struct.unpack_from('<B', lump, o+30)
                skin, = struct.unpack_from('<i', lump, o+32)
                out.append((names[model], origin, angles, solid, skin))
            return out
        return []


def parse_vmt(text):
    """Flat lower-case key/value view of a VMT; nested blocks merge into it."""
    text = re.sub(r'//[^\n]*', '', text)
    tokens = re.findall(r'"([^"]*)"|([^\s{}"]+)|([{}])', text)
    shader = None; values = {}; key = None
    for quoted, bare, brace in tokens:
        token = quoted if quoted or (not bare and not brace) else bare
        if brace:
            key = None; continue
        if shader is None: shader = token.lower(); continue
        if key is None: key = token.lower()
        else: values.setdefault(key, token); key = None
    return shader, values


def material_info(content, name, depth=0):
    """Shader and keys of a material, following patch materials to their base."""
    shader, values = parse_vmt(content.read('materials/'+name.lower()+'.vmt').decode('latin-1'))
    if shader == 'patch' and 'include' in values and depth < 4:
        base = values['include'].replace('\\', '/').lower().removeprefix('materials/').removesuffix('.vmt')
        base_shader, base_values = material_info(content, base, depth+1)
        return base_shader, {**base_values, **{k: v for k, v in values.items() if k != 'include'}}
    return shader, values


# VTF image formats this reader decodes: Pillow raw mode or BCn variant.
VTF_FORMATS = {0: ('raw', 'RGBA', 4), 1: ('raw', 'ABGR', 4), 2: ('raw', 'RGB', 3), 3: ('raw', 'BGR', 3),
               5: ('raw', 'L', 1), 6: ('raw', 'LA', 2), 12: ('raw', 'BGRA', 4), 16: ('raw', 'BGRX', 4),
               13: ('bcn', 1, 8), 20: ('bcn', 1, 8), 14: ('bcn', 2, 16), 15: ('bcn', 3, 16)}


def vtf_level_size(fmt, width, height):
    kind, _, size = VTF_FORMATS[fmt]
    if kind == 'bcn': return max(1, (width+3)//4)*max(1, (height+3)//4)*size
    return width*height*size


def read_vtf(data):
    """Largest mip of the first frame and face, as RGBA."""
    if data[:4] != b'VTF\0': raise ValueError('not a VTF')
    major, minor, header = struct.unpack_from('<3I', data, 4)
    width, height, flags, frames = struct.unpack_from('<HHIH', data, 16)
    fmt, mips, low_fmt, low_w, low_h = struct.unpack_from('<iBiBB', data, 52)
    if fmt not in VTF_FORMATS: raise ValueError(f'unsupported VTF format {fmt}')
    # Envmaps before 7.5 carry a seventh spheremap face.
    faces = (6 if minor >= 5 else 7) if flags & 0x4000 else 1
    if minor >= 3:
        count = struct.unpack_from('<I', data, 68)[0]
        offset = None
        for i in range(count):
            tag, _, value = struct.unpack_from('<3sBI', data, 80+8*i)
            if tag == b'\x30\0\0': offset = value
        if offset is None: raise ValueError('VTF without image data')
    else:
        offset = header+(vtf_level_size(low_fmt, low_w, low_h) if low_fmt in VTF_FORMATS and low_w else 0)
    for level in range(mips-1, 0, -1):
        offset += frames*faces*vtf_level_size(fmt, max(1, width >> level), max(1, height >> level))
    raw = data[offset:offset+vtf_level_size(fmt, width, height)]
    kind, mode, _ = VTF_FORMATS[fmt]
    if kind == 'bcn': return Image.frombytes('RGBA', (width, height), raw, 'bcn', mode)
    return Image.frombytes('RGBA' if mode in ('RGBA', 'ABGR', 'BGRA', 'BGRX') else 'RGB' if mode in ('RGB', 'BGR') else mode,
                           (width, height), raw, 'raw', mode).convert('RGBA')


def vtf_size(data):
    return struct.unpack_from('<HH', data, 16)


def angle_matrix(pitch, yaw, roll):
    """Source AngleMatrix: columns are forward, left, up."""
    p, y, r = (math.radians(a) for a in (pitch, yaw, roll))
    sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(r), math.cos(r)
    return np.array(((cp*cy, sr*sp*cy-cr*sy, cr*sp*cy+sr*sy),
                     (cp*sy, sr*sp*sy+cr*cy, cr*sp*sy-sr*cy),
                     (-sp, sr*cp, cr*cp)))


def c_string(data, offset):
    return data[offset:data.index(b'\0', offset)].decode('latin-1')


class Model:
    """A static prop: LOD 0 triangles per material from MDL/VVD/VTX, and PHY convex pieces."""

    def __init__(self, content, path):
        base = path.lower().replace('\\', '/').removesuffix('.mdl')
        mdl = content.read(base+'.mdl')
        if mdl[:4] != b'IDST': raise ValueError(f'{path}: not an MDL')
        version, = struct.unpack_from('<i', mdl, 4)
        texture_count, texture_index, cd_count, cd_index = struct.unpack_from('<4i', mdl, 204)
        skin_refs, skin_families, skin_index, part_count, part_index = struct.unpack_from('<5i', mdl, 220)
        self.textures = [c_string(mdl, texture_index+64*k+struct.unpack_from('<i', mdl, texture_index+64*k)[0]) for k in range(texture_count)]
        self.cd = [c_string(mdl, struct.unpack_from('<i', mdl, cd_index+4*k)[0]) for k in range(cd_count)]
        self.skins = [struct.unpack_from(f'<{skin_refs}h', mdl, skin_index+2*skin_refs*f) for f in range(skin_families)]
        self.vertices = self.vvd(content.read(base+'.vvd'))
        vtx = content.read(base+'.dx90.vtx')
        vtx_parts, vtx_part_index = struct.unpack_from('<2i', vtx, 28)
        self.meshes = []  # (material index, triangles as vertex indices)
        for b in range(min(part_count, vtx_parts)):
            part = part_index+16*b
            models, model_index = struct.unpack_from('<i4xi', mdl, part+4)
            if not models: continue
            model = part+model_index  # first model of each body part
            mesh_count, mesh_index, _, vertex_index = struct.unpack_from('<4i', mdl, model+72)
            first_vertex = vertex_index//48
            vpart = vtx_part_index+8*b
            vmodel = vpart+struct.unpack_from('<i', vtx, vpart+4)[0]
            vlod = vmodel+struct.unpack_from('<i', vtx, vmodel+4)[0]
            vmesh_count, vmesh_offset = struct.unpack_from('<2i', vtx, vlod)
            for m in range(min(mesh_count, vmesh_count)):
                mesh = model+mesh_index+116*m
                material, _, _, vertex_offset = struct.unpack_from('<4i', mdl, mesh)
                vmesh = vlod+vmesh_offset+9*m
                groups, group_offset = struct.unpack_from('<2i', vtx, vmesh)
                triangles = []
                for g in range(groups):
                    triangles += [first_vertex+vertex_offset+i for i in self.strip_group(vtx, vmesh+group_offset, g)]
                if triangles:
                    self.meshes.append((material, np.array(triangles).reshape(-1, 3)))
        try: self.hulls = self.phy(content.read(base+'.phy'))
        except KeyError: self.hulls = []

    @staticmethod
    def vvd(data):
        """LOD 0 vertices as rows of position, normal and UV."""
        if data[:4] != b'IDSV': raise ValueError('not a VVD')
        lod0, = struct.unpack_from('<i', data, 16)
        fixups, fixup_start, vertex_start = struct.unpack_from('<3i', data, 48)
        def rows(first, count):
            block = data[vertex_start+48*first:vertex_start+48*(first+count)]
            return np.frombuffer(block, np.float32).reshape(-1, 12)[:, 4:12]
        if not fixups: return rows(0, lod0)
        return np.concatenate([rows(source, count) for lod, source, count in
                               (struct.unpack_from('<3i', data, fixup_start+12*k) for k in range(fixups)) if lod >= 0])

    @staticmethod
    def strip_group(vtx, start, index):
        # Strip groups grew topology fields in later tools; take the size whose indices fit.
        for size in (25, 33):
            group = start+size*index
            verts, vert_offset, indices, index_offset = struct.unpack_from('<4i', vtx, group)
            if not (0 < verts < 65536 and 0 <= indices < 1 << 20 and group+index_offset+2*indices <= len(vtx)
                    and group+vert_offset+9*verts <= len(vtx)): continue
            ids = [struct.unpack_from('<H', vtx, group+vert_offset+9*k+4)[0] for k in range(verts)]
            order = struct.unpack_from(f'<{indices}H', vtx, group+index_offset)
            if all(i < verts for i in order): return [ids[i] for i in order]
        raise ValueError('unreadable VTX strip group')

    @staticmethod
    def phy(data):
        """Convex pieces, each a list of planes (normal, dist) in model space."""
        header, _, solids, _ = struct.unpack_from('<4i', data)
        p = header; hulls = []
        for _ in range(solids):
            size, = struct.unpack_from('<i', data, p); start = p+4; p = start+size
            surface = start+28 if data[start:start+4] == b'VPHY' else start
            root, = struct.unpack_from('<i', data, surface+32)
            # Ledge tree nodes are 28 bytes from the root to the end of the solid. Internal nodes also
            # point at ledges, the convex hull of their whole subtree; only leaves are collision pieces.
            leaves = []; end = surface+(struct.unpack_from('<I', data, surface+28)[0] >> 8)
            for node in range(surface+root, min(end, p)-27, 28):
                right, ledge_offset = struct.unpack_from('<ii', data, node)
                if right == 0: leaves.append(node+ledge_offset)
            for ledge in leaves:
                points_offset, _, _, tri_count = struct.unpack_from('<iiih', data, ledge)
                tris = [[e & 0xFFFF for e in struct.unpack_from('<3I', data, ledge+20+16*t)] for t in range(tri_count)]
                if tri_count:
                    coords = {}
                    for i in {i for tri in tris for i in tri}:
                        x, y, z = struct.unpack_from('<3f', data, ledge+points_offset+16*i)
                        coords[i] = np.array((x, z, -y))*39.3701  # IVP metres, Y down
                    centre = np.mean(list(coords.values()), 0); planes = []
                    for a, b, c in tris:
                        n = np.cross(coords[b]-coords[a], coords[c]-coords[a])
                        if np.linalg.norm(n) < 1e-6: continue
                        n /= np.linalg.norm(n); d = n@coords[a]
                        if n@centre > d: n, d = -n, -d
                        if not any(np.allclose(n, q, atol=1e-3) and abs(d-e) < .1 for q, e in planes): planes.append((n, d))
                    if len(planes) >= 4: hulls.append(planes)
        return hulls

    def material(self, mesh_material, skin):
        """Candidate material paths for a mesh, one per model search directory."""
        family = self.skins[skin] if skin < len(self.skins) else self.skins[0]
        name = self.textures[family[mesh_material] if mesh_material < len(family) else mesh_material]
        return [re.sub('/+', '/', (cd+'/'+name).replace('\\', '/').lower()).strip('/') for cd in self.cd]
