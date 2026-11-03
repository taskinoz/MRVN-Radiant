"""Readers for Source 2 (Counter-Strike 2) map content exported by Source2Viewer-CLI.

Binary resources are not parsed here: Source2Viewer's `-b BLOCK` dumps a block as
KeyValues3 text and its `-d --gltf_export_format gltf` exports render meshes and
textures. This module reads those dumps and exports.
"""
import base64
import json
from pathlib import Path
import re
import struct

import numpy as np

TOKEN = re.compile(r'''\s*(?:
    (?P<comment>//[^\n]*|/\*.*?\*/|<!--.*?-->)
  | (?P<blob>\#\[(?P<hex>[0-9A-Fa-f\s]*)\])
  | (?P<multi>""".*?""")
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<punct>[{}\[\]=,])
  | (?P<atom>[^\s{}\[\]=,"]+(?:"(?:[^"\\]|\\.)*")?)
)''', re.S | re.X)


def parse_kv3(text):
    """KeyValues3 text: objects become dicts, arrays lists, #[..] blobs bytes."""
    tokens = []
    for m in TOKEN.finditer(text):
        kind = m.lastgroup
        if kind == 'comment': continue
        if kind == 'blob': tokens.append(('blob', bytes.fromhex(''.join(m.group('hex').split()))))
        elif kind == 'multi': tokens.append(('value', m.group('multi')[3:-3]))
        elif kind == 'string': tokens.append(('value', re.sub(r'\\(.)', r'\1', m.group('string')[1:-1], flags=re.S)))
        elif kind == 'punct': tokens.append((m.group('punct'), None))
        else: tokens.append(('atom', m.group('atom')))
    pos = 0

    def atom(a):
        if a in ('true', 'false'): return a == 'true'
        if a == 'null': return None
        try: return int(a)
        except ValueError: pass
        try: return float(a)
        except ValueError: pass
        # resource:"path", soundevent:"name" and other flagged strings keep their payload.
        m = re.match(r'\w+:"(.*)"$', a)
        return m.group(1) if m else a

    def value():
        nonlocal pos
        kind, v = tokens[pos]; pos += 1
        if kind == '{':
            out = {}
            while tokens[pos][0] != '}':
                key = tokens[pos][1]; pos += 1
                assert tokens[pos][0] == '=', tokens[pos]; pos += 1
                out[key] = value()
            pos += 1; return out
        if kind == '[':
            out = []
            while tokens[pos][0] != ']':
                out.append(value())
                if tokens[pos][0] == ',': pos += 1
            pos += 1; return out
        if kind == 'blob': return v
        if kind == 'atom': return atom(v)
        return v
    return value()


def block_text(dump):
    """The KV3 body of a Source2Viewer `-b` dump, from its encoding header on."""
    start = dump.index('<!-- kv3')
    return dump[start:]


def entities(dump):
    """Entity keyvalues from a `-b DATA` dump of an entity lump (.vents_c)."""
    lump = parse_kv3(block_text(dump))
    return [e['keyValues3Data']['values'] for e in lump['m_entityKeyValues'] if e.get('keyValues3Data')]


class Physics:
    """World collision from a `-b PHYS` dump of world_physics.vmdl_c: convex hulls and triangle meshes."""

    def __init__(self, dump):
        phys = parse_kv3(block_text(dump))
        self.attributes = phys.get('m_collisionAttributes', [])
        self.hulls = []; self.meshes = []
        for part in phys['m_parts']:
            shape = part['m_rnShape']
            for hull in shape['m_hulls']:
                # Face planes as (normal, offset) with normal . p = offset; m_pRegionSVM holds unrelated split planes.
                planes = np.frombuffer(hull['m_Hull']['m_Planes'], '<f4').reshape(-1, 4)
                self.hulls.append((hull['m_nCollisionAttributeIndex'], planes))
            for mesh in shape['m_meshes']:
                m = mesh['m_Mesh']
                vertices = np.frombuffer(m['m_Vertices'], '<f4').reshape(-1, 3)
                triangles = np.frombuffer(m['m_Triangles'], '<i4').reshape(-1, 3)
                self.meshes.append((mesh['m_nCollisionAttributeIndex'], vertices, triangles))

    def solid_for_players(self, index):
        """Whether a collision attribute stops players (default world, player clip), not just bullets or grenades."""
        attribute = self.attributes[index] if index < len(self.attributes) else {}
        group = str(attribute.get('m_CollisionGroupString', 'default')).lower()
        interacts = {str(s).lower() for s in attribute.get('m_InteractAsStrings', [])}
        if group in ('trigger', 'debris', 'interactive', 'weapon'): return False
        return not interacts or bool(interacts & {'default', 'solid', 'playerclip', 'player_clip', 'world', 'worldgeometry'})


ACCESSOR = {5120: 'i1', 5121: 'u1', 5122: 'i2', 5123: 'u2', 5125: 'u4', 5126: 'f4'}
WIDTH = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


class GLTF:
    """A glTF 2.0 export: flattened node transforms, mesh primitives and material base colour images."""

    def __init__(self, path):
        self.path = Path(path); self.root = self.path.parent
        self.data = json.loads(self.path.read_text(encoding='utf-8'))
        self.buffers = []
        for b in self.data.get('buffers', []):
            uri = b['uri']
            self.buffers.append(base64.b64decode(uri.split(',', 1)[1]) if uri.startswith('data:') else (self.root/uri).read_bytes())

    def accessor(self, index):
        a = self.data['accessors'][index]; view = self.data['bufferViews'][a['bufferView']]
        buffer = self.buffers[view['buffer']]; width = WIDTH[a['type']]; dtype = np.dtype('<'+ACCESSOR[a['componentType']])
        start = view.get('byteOffset', 0)+a.get('byteOffset', 0); stride = view.get('byteStride') or dtype.itemsize*width
        raw = np.ndarray((a['count'], width), dtype, buffer, start, (stride, dtype.itemsize))
        return raw.astype(np.float64 if dtype.kind == 'f' else np.int64)

    def instances(self):
        """(mesh index, 4x4 world matrix) for every node with a mesh."""
        nodes = self.data['nodes']; out = []
        def walk(i, parent):
            n = nodes[i]
            if 'matrix' in n: local = np.array(n['matrix'], float).reshape(4, 4).T
            else:
                t = n.get('translation', [0, 0, 0]); r = n.get('rotation', [0, 0, 0, 1]); s = n.get('scale', [1, 1, 1])
                x, y, z, w = r
                rot = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                                [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                                [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
                local = np.eye(4); local[:3, :3] = rot*np.array(s); local[:3, 3] = t
            world = parent@local
            if 'mesh' in n: out.append((n['mesh'], world))
            for c in n.get('children', []): walk(c, world)
        scene = self.data['scenes'][self.data.get('scene', 0)]
        for i in scene['nodes']: walk(i, np.eye(4))
        return out

    def primitives(self, mesh):
        """(material index, positions, normals, uvs, triangles) per primitive of a mesh."""
        out = []; cache = {}
        def accessor(index):
            if index not in cache: cache[index] = self.accessor(index)
            return cache[index]
        for p in self.data['meshes'][mesh]['primitives']:
            if p.get('mode', 4) != 4: continue
            attrs = p['attributes']; positions = accessor(attrs['POSITION'])
            normals = accessor(attrs['NORMAL']) if 'NORMAL' in attrs else np.zeros_like(positions)
            uvs = accessor(attrs['TEXCOORD_0']) if 'TEXCOORD_0' in attrs else np.zeros((len(positions), 2))
            triangles = self.accessor(p['indices']).reshape(-1, 3) if 'indices' in p else np.arange(len(positions)).reshape(-1, 3)
            # Primitives of one mesh share its whole vertex buffer; keep only the vertices this one uses.
            used, triangles = np.unique(triangles, return_inverse=True); triangles = triangles.reshape(-1, 3)
            positions, normals, uvs = positions[used], normals[used], uvs[used]
            out.append((p.get('material'), positions, normals, uvs, triangles))
        return out

    def material(self, index):
        """(name, base colour image path or None, alpha mode, base colour factor) of a material."""
        m = self.data['materials'][index]; pbr = m.get('pbrMetallicRoughness', {})
        image = None
        if 'baseColorTexture' in pbr:
            source = self.data['textures'][pbr['baseColorTexture']['index']].get('source')
            if source is not None and 'uri' in self.data['images'][source]:
                image = self.root/self.data['images'][source]['uri'].replace('%20', ' ')
        return m.get('name', f'material_{index}'), image, m.get('alphaMode', 'OPAQUE'), pbr.get('baseColorFactor', [1, 1, 1, 1])


# glTF is Y up in metres; Source2Viewer exports Source units scaled by this.
GLTF_TO_SOURCE = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], float)
