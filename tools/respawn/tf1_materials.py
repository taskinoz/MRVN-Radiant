#!/usr/bin/env python3
"""Titanfall 1 VMT/VTF materials as Titanfall 2 RPak materials (RePak assets).

Titanfall 1 materials use Respawn's texture suffixes (_col, _nml, _spc, _exp), which
map onto the Titanfall 2 world (_wld) and prop (_fix) shaders' four slots:

  0 albedo  <- $basetexture            (DXT blocks copied as BC1/BC3, sRGB)
  1 normal  <- $bumpmap / $normalmap   (copied, linear)
  2 gloss   <- $shininess texture, else the spec texture's alpha (BC1, linear)
  3 spec    <- $reflectiontint         (copied, sRGB)

Each material clones a retail template (see the port's extract_templates.py):
opaque, translucent ($translucent), alpha-tested ($alphatest) or water (the Water
shader, cloned from a scrolling-UV retail world water). Compressed VTF mips are
copied without re-encoding; mips above --max-size are dropped.

Copyright (c) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
"""
import json
import re
import shutil
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_engine import read_vtf  # noqa: E402
from build_minecraft_ports import bc1_level  # noqa: E402

BS = chr(92)
# VTF format -> (DXGI linear, DXGI sRGB, bytes per 4x4 block)
BLOCK_FORMATS = {13: (71, 72, 8), 20: (71, 72, 8), 14: (74, 75, 16), 15: (77, 78, 16)}
# Opacity of converted water (TF1 refracts the floor through it; TF2 blends it). Tuned by eye against
# R1Delta's Lagoon: the retail translucent water shader weakens the albedo alpha considerably.
WATER_ALPHA = 230
TEXTURE_KEYS = ('$basetexture', '$bumpmap', '$normalmap', '$reflectiontint', '$shininess')


def norm(s):
    return re.sub('/+', '/', s.replace(BS, '/').lower()).strip('/')


def parse_vmt(text):
    text = re.sub(r'//[^\n]*', '', text)
    m = re.match(r'\s*"?([A-Za-z0-9_]+)"?', text)
    shader = m.group(1).lower() if m else ''
    keys = {k.lower(): v.strip('"') for k, v in
            re.findall(r'"?(\$[A-Za-z0-9_]+)"?\s+("[^"]*"|[^\s{}"]+)', text)}
    inc = re.search(r'"include"\s+"([^"]+)"', text)
    return shader, keys, (norm(inc.group(1)) if inc else None)


def vtf_mips(data):
    """(format, width, height, [mip bytes, largest first]) for the first frame and face."""
    if data[:4] != b'VTF\0':
        raise ValueError('not a VTF')
    major, minor, header = struct.unpack_from('<3I', data, 4)
    width, height, flags, frames = struct.unpack_from('<HHIH', data, 16)
    fmt, mips, low_fmt, low_w, low_h = struct.unpack_from('<iBiBB', data, 52)
    if fmt not in BLOCK_FORMATS:
        raise ValueError(f'format {fmt}')
    block = BLOCK_FORMATS[fmt][2]
    faces = (6 if minor >= 5 else 7) if flags & 0x4000 else 1
    offset = None
    if minor >= 3:
        for i in range(struct.unpack_from('<I', data, 68)[0]):
            tag, _, value = struct.unpack_from('<3sBI', data, 80 + 8 * i)
            if tag == b'\x30\0\0':
                offset = value
    if offset is None:
        offset = header + (max(1, (low_w + 3) // 4) * max(1, (low_h + 3) // 4) * 8 if low_w else 0)
    levels = []
    for level in range(mips - 1, -1, -1):  # stored smallest first
        w, h = max(1, width >> level), max(1, height >> level)
        size = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block
        levels.append((w, h, data[offset:offset + size]))
        offset += size * frames * faces
    return fmt, width, height, levels[::-1]


def dds(path, width, height, dxgi, mips):
    header = struct.pack('<4sI', b'DDS ', 124)
    header += struct.pack('<6I', 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000, height, width, len(mips[0]), 0, len(mips))
    header += bytes(44)
    header += struct.pack('<2I4s5I', 32, 0x4, b'DX10', 0, 0, 0, 0, 0)
    header += struct.pack('<5I', 0x1000 | 0x400000 | 0x8, 0, 0, 0, 0)
    header += struct.pack('<5I', dxgi, 3, 0, 1, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + b''.join(mips))


def image_levels(image):
    levels, im = [], image
    while True:
        levels.append(im)
        if im.width <= 4 and im.height <= 4:
            return levels
        im = im.resize((max(4, im.width // 2), max(4, im.height // 2)), Image.Resampling.BOX)


class Converter:
    def __init__(self, assets, templates, out, prefix, max_size=1024, max_detail=512):
        self.assets, self.templates, self.out = Path(assets), Path(templates), Path(out)
        self.prefix, self.max_size, self.max_detail = prefix, max_size, max_detail
        self.files, self.textures, self.report = [], {}, {}

    # -- textures ------------------------------------------------------------
    def _add(self, path):
        self.files.append({'_type': 'txtr', '_path': path, '$disableStreaming': True})
        return path

    def vtf(self, name):
        return (self.assets / 'materials' / (norm(name) + '.vtf')).read_bytes()

    def copy(self, name, srgb, limit):
        """A VTF's blocks as a DDS texture; None if it is missing or not block-compressed."""
        # One texture per VTF: the first use decides its size and colour space.
        key = ('copy', norm(name))
        if key in self.textures:
            return self.textures[key]
        try:
            fmt, w, h, levels = vtf_mips(self.vtf(name))
            while len(levels) > 1 and max(levels[0][0], levels[0][1]) > limit:
                levels = levels[1:]
            # BC blocks: drop mips below one 4x4 block (a pak with them never finishes loading).
            levels = [lv for lv in levels if lv[0] >= 4 and lv[1] >= 4] or levels[:1]
            path = f'texture/{self.prefix}/{norm(name)}.rpak'
            dds(self.out / Path(path).with_suffix('.dds'), levels[0][0], levels[0][1],
                BLOCK_FORMATS[fmt][1 if srgb else 0], [lv[2] for lv in levels])
            self.textures[key] = (self._add(path), (levels[0][0], levels[0][1]))
        except (OSError, ValueError, struct.error):
            self.textures[key] = None
        return self.textures[key]

    def encode(self, key, image, srgb, alpha=False):
        """An image as BC1 (opaque) or RGBA8 (with alpha) with mips."""
        if key in self.textures:
            return self.textures[key]
        path = f'texture/{self.prefix}/{key}.rpak'
        levels = image_levels(image.convert('RGBA'))
        if alpha:
            dds(self.out / Path(path).with_suffix('.dds'), levels[0].width, levels[0].height, 29 if srgb else 28,
                [lv.tobytes() for lv in levels])
        else:
            dds(self.out / Path(path).with_suffix('.dds'), levels[0].width, levels[0].height, 72 if srgb else 71,
                [bc1_level(lv.width, lv.height, lv.tobytes()) for lv in levels])
        self.textures[key] = (self._add(path), image.size)
        return self.textures[key]

    def solid(self, name, rgba, srgb=True):
        alpha = rgba[3] < 255
        return self.encode('_flat/' + name, Image.new('RGBA', (16, 16), rgba), srgb, alpha)

    def gloss_from_alpha(self, name):
        key = '_gloss/' + norm(name)
        if key in self.textures:
            return self.textures[key]
        try:
            fmt = struct.unpack_from('<i', self.vtf(name), 52)[0]
            if fmt not in (14, 15):
                return None
            a = read_vtf(self.vtf(name)).getchannel('A')
        except (OSError, ValueError, struct.error):
            return None
        if max(a.size) > self.max_detail:
            s = self.max_detail / max(a.size)
            a = a.resize((max(4, int(a.width * s)), max(4, int(a.height * s))), Image.Resampling.LANCZOS)
        return self.encode(key, Image.merge('RGB', (a, a, a)), False)

    # -- materials -----------------------------------------------------------
    def vmt(self, name, depth=0):
        path = self.assets / 'materials' / (norm(name) + '.vmt')
        shader, keys, inc = parse_vmt(path.read_text(errors='replace'))
        if inc and depth < 4:
            base_shader, base_keys = self.vmt(inc.removeprefix('materials/').removesuffix('.vmt'), depth + 1)
            return base_shader, {**base_keys, **keys}
        return shader, keys

    def clone(self, key, name, suffix, textures, size, extra=None, surface=None):
        spec = json.loads((self.templates / (key + '.json')).read_text())
        spec.update(name=name, width=size[0], height=size[1], **(extra or {}))
        # rpak.py reads every retail material as 'wld'; the suffix is the real shader type.
        spec['shaderType'] = suffix.lstrip('_')
        if surface:
            spec['surfaceProp'] = surface
        spec['$textures'] = textures
        path = f'material/{name}{suffix}.rpak'
        dst = self.out / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.with_suffix('.json').write_text(json.dumps(spec, indent=2))
        shutil.copyfile(self.templates / (key + '.uber'), dst.with_suffix('.uber'))
        self.files.append({'_type': 'matl', '_path': path})
        return path

    def material(self, name, use, out=None):
        """Write TF1 material NAME as OUT (default NAME) for 'wld' (world) or 'fix' (prop) use; returns its kind."""
        name = norm(name)
        shader, keys = self.vmt(name)
        name = norm(out) if out else name
        flat_n = self.solid('normal', (128, 128, 255, 255), False)[0]
        surface = keys.get('$surfaceprop')
        if shader == 'water':
            kind = 'water'
        elif keys.get('$additive') == '1':
            kind = 'additive'
        elif keys.get('$translucent') == '1':
            kind = 'translucent'
        elif keys.get('$alphatest') == '1':
            kind = 'cutout'
        elif shader in ('unlitgeneric', 'unlittwotexture', 'basic') and use == 'fix':
            kind = 'unlit'  # sky domes, vista backdrops (Respawn's TF1 'Basic' shader is unlit)
        else:
            kind = 'opaque'
        base = keys.get('$basetexture')
        col = self.copy(base, True, self.max_size) if base and norm(base) != 'effects/white' else None
        if col is None:
            colour = [float(x) for x in re.findall(r'[-\d.]+', keys.get('$color2', keys.get('$color', '[.5 .5 .5]')))][:3] or [.5, .5, .5]
            if kind == 'water':
                # TF1 water is seen through refraction tinted $refracttint. TF2 has no refraction, so the
                # tint becomes a translucent albedo the floor shows through. ($nonrefracttint, TF1's
                # no-refraction colour, is too dark: the translucent shader then adds almost nothing.)
                tint = keys.get('$refracttint', keys.get('$fogcolor', '{25 55 60}'))
                colour = [c / 255 for c in [float(x) for x in re.findall(r'[-\d.]+', tint)][:3]]
            if kind == 'translucent':
                alpha = int(255 * float(keys.get('$alpha', '1')))
            elif kind == 'water':
                # A $bottommaterial ($abovewater 0) is drawn by TF1 only from under the surface. TF2 cannot
                # gate it, and the two-sided surface already shows from below, so it is left invisible.
                alpha = 0 if keys.get('$abovewater') == '0' else WATER_ALPHA
            else:
                alpha = 255
            rgba = tuple(int(255 * min(1.0, max(0.0, c))) for c in colour) + (alpha,)
            col = self.solid('col_%02x%02x%02x%02x' % rgba, rgba)
        bump = keys.get('$bumpmap') or keys.get('$normalmap')
        nml = (self.copy(bump, False, self.max_size) if bump else None) or (flat_n, None)
        spec_tex = keys.get('$reflectiontint')
        spc = self.copy(spec_tex, True, self.max_detail) if spec_tex and not spec_tex.startswith('[') else None
        if kind == 'water':
            spc = spc or self.solid('spc_water', (60, 60, 60, 255))
            gls = self.solid('gls_water', (230, 230, 230, 255), False)
        else:
            spc = spc or self.solid('spc_dark', (12, 12, 12, 255))
            exp = keys.get('$shininess')
            gls = (self.copy(exp, False, self.max_detail) if exp and not re.fullmatch(r'[-\d.]+', exp) else None) \
                or (self.gloss_from_alpha(spec_tex) if spc and spec_tex else None) \
                or self.solid('gls_mid', (70, 70, 70, 255), False)
        textures = {'0': col[0], '1': nml[0], '2': gls[0], '3': spc[0]}
        size = col[1]
        if kind == 'water':
            # Retail see-through pool water: translucent, scrolling, not back-face culled (so it also shows
            # from below), no colpass. It adds the lit albedo over the floor rather than hiding it, so a
            # light tint reads as water where a dark one vanishes.
            textures['18'] = nml[0]
            self.clone('water_trans_wld', name, '_wld', textures, size, {'$colpassMaterial': '0x0'}, 'water')
        elif kind == 'additive':
            # Unlit additive: light shafts, holograms. The prop shader also reads an opacity mask (slot 13).
            add = {'0': col[0]} if use == 'wld' else {'0': col[0], '13': self.solid('white', (255, 255, 255, 255))[0]}
            self.clone(f'additive_{use}', name, '_' + use, add, size, surface=surface)
        elif kind == 'unlit':
            self.clone('unlit_fix', name, '_fix', {'0': col[0]}, size, {'$colpassMaterial': '0x0'}, surface)
        elif kind == 'translucent':
            self.clone(f'translucent_{use}', name, '_' + use, textures, size, surface=surface)
        elif kind == 'cutout':
            # Own depth passes sample the albedo's alpha, or the holes cast shadows and fill the prepass.
            depth = {f'$depth{K}Material': self.clone(f'cutout_{k}_{use}', 'depth/' + name + '_' + k, '_' + use, {'0': col[0]}, size)
                     for k, K in (('shadow', 'Shadow'), ('prepass', 'Prepass'), ('vsm', 'VSM'))}
            colpass = self.clone(f'cutout_colpass_{use}', name + '_colpass', '_' + use, textures, size,
                                 {**depth, '$colpassMaterial': '0x0'}, surface)
            self.clone(f'cutout_{use}', name, '_' + use, textures, size, {**depth, '$colpassMaterial': colpass}, surface)
        else:
            colpass = self.clone(f'base_colpass_{use}', name + '_colpass', '_' + use, textures, size, {'$colpassMaterial': '0x0'}, surface)
            self.clone(f'base_{use}', name, '_' + use, textures, size, {'$colpassMaterial': colpass}, surface)
        self.report[name + '_' + use] = kind
        return kind
