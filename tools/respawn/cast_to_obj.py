#!/usr/bin/env python3
"""Convert Cast model files (as exported by RSX) to OBJ editor copies.

Original implementation, GPL-2.0-or-later. Python 3.10+, standard library only.
Format reference: the public Cast specification, dtzxporter/cast
(https://github.com/dtzxporter/cast, MIT); no code copied.

Only mesh positions, first UV layer and faces are converted. Each Cast mesh
becomes an OBJ group named after its material (or mesh index). The OBJ keeps
the Cast coordinate system, which for Respawn exports is the game's own, so
the compiler can use it directly to bound a static prop.

    python cast_to_obj.py IN.cast OUT.obj
    python cast_to_obj.py --tree EXPORT_DIR OUT_DIR   # every *_LOD0.cast

``--tree`` writes OUT_DIR/models/<relative path without _LOD0>.obj. With
OUT_DIR as the compiler's assets folder, a ``prop_static`` whose model is
``mdl/x/y.rmdl`` finds ``models/mdl/x/y.obj`` as its editor copy; the game
lump keeps the ``.rmdl`` name.

Vertices are written Y-up (x, z, -y) because the compiler's model importer
rotates OBJ input from Y-up to Z-up.
"""
import argparse
import struct
from pathlib import Path

CAST_MAGIC = 0x74736163
PROPERTY_FORMATS = {
    0x62: ("B", 1), 0x68: ("H", 1), 0x69: ("I", 1), 0x6C: ("Q", 1),
    0x66: ("f", 1), 0x64: ("d", 1),
    0x7632: ("f", 2), 0x7633: ("f", 3), 0x7634: ("f", 4),
}
NODE_MESH = 0x6873656D
NODE_MATERIAL = 0x6C74616D


class Node:
    __slots__ = ("kind", "hash", "properties", "children")

    def __init__(self, kind, hash_):
        self.kind, self.hash, self.properties, self.children = kind, hash_, {}, []


def read_node(data, at):
    kind, size, hash_, property_count, child_count = struct.unpack_from("<IIQII", data, at)
    end = at + size
    node = Node(kind, hash_)
    at += 24
    for _ in range(property_count):
        ptype, name_size, count = struct.unpack_from("<HHI", data, at)
        at += 8
        name = data[at:at + name_size].decode("utf-8", "replace")
        at += name_size
        if ptype == 0x73:  # string: NUL-terminated
            stop = data.index(b"\0", at)
            node.properties[name] = data[at:stop].decode("utf-8", "replace")
            at = stop + 1
            continue
        if ptype not in PROPERTY_FORMATS:
            raise ValueError(f"unsupported Cast property type 0x{ptype:x} ({name})")
        code, width = PROPERTY_FORMATS[ptype]
        values = struct.unpack_from(f"<{count * width}{code}", data, at)
        at += struct.calcsize(f"<{count * width}{code}")
        node.properties[name] = [values[i:i + width] for i in range(0, len(values), width)] if width > 1 else list(values)
    for _ in range(child_count):
        child, at = read_node(data, at)
        node.children.append(child)
    if at != end:
        raise ValueError("Cast node size disagrees with its contents")
    return node, end


def read_cast(path):
    data = Path(path).read_bytes()
    magic, version, root_count, _flags = struct.unpack_from("<IIII", data, 0)
    if magic != CAST_MAGIC:
        raise ValueError(f"{path} is not a Cast file")
    roots, at = [], 16
    for _ in range(root_count):
        node, at = read_node(data, at)
        roots.append(node)
    return roots


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.children)


def cast_to_obj(source, target):
    nodes = list(walk(read_cast(source)))
    materials = {n.hash: n.properties.get("n", f"material_{n.hash:x}") for n in nodes if n.kind == NODE_MATERIAL}
    meshes = [n for n in nodes if n.kind == NODE_MESH]
    if not meshes:
        raise ValueError(f"{source} has no meshes")
    lines, base, triangles = [f"# converted from {Path(source).name} by cast_to_obj.py"], 1, 0
    for index, mesh in enumerate(meshes):
        positions = mesh.properties.get("vp", [])
        uvs = mesh.properties.get("u0", [])
        faces = mesh.properties.get("f", [])
        material = mesh.properties.get("m")
        name = materials.get(material[0] if isinstance(material, list) else material, f"mesh_{index}")
        lines.append(f"g {name}")
        lines.extend(f"v {x:.6f} {z:.6f} {-y:.6f}" for x, y, z in positions)
        has_uv = len(uvs) == len(positions)
        if has_uv:
            lines.extend(f"vt {u:.6f} {1.0 - v:.6f}" for u, v in uvs)
        for i in range(0, len(faces) - 2, 3):
            a, b, c = (base + faces[i + k] for k in range(3))
            # Cast faces are clockwise; OBJ expects counter-clockwise.
            lines.append(f"f {a}/{a} {c}/{c} {b}/{b}" if has_uv else f"f {a} {c} {b}")
            triangles += 1
        base += len(positions)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(target).write_text("\n".join(lines) + "\n")
    return dict(meshes=len(meshes), vertices=base - 1, triangles=triangles)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--tree", action="store_true", help="convert every *_LOD0.cast under SOURCE")
    args = parser.parse_args()
    if not args.tree:
        print(cast_to_obj(args.source, args.target))
        return
    converted = 0
    for cast in sorted(args.source.rglob("*_LOD0.cast")):
        relative = cast.relative_to(args.source)
        target = args.target / "models" / relative.parent / (relative.name[:-len("_LOD0.cast")] + ".obj")
        try:
            cast_to_obj(cast, target)
            converted += 1
        except (ValueError, struct.error) as error:
            print(f"skipped {relative}: {error}")
    print(f"converted {converted} models")


if __name__ == "__main__":
    main()
