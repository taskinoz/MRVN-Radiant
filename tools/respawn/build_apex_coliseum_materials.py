"""Build local S3 materials from extracted TF2 textures and native Apex templates.

Original code, GPL-2.0-or-later. Requires user-owned game assets. This translates
material inputs; it does not claim identical shaders across the two engines.
"""
import argparse
import copy
import csv
import hashlib
import io
import itertools
import json
from pathlib import Path
import struct
import subprocess

from PIL import Image
import numpy as np
from build_quake_materials import write_dds
from rpak import RPak
from rpak_apex import ApexRPak

PAK_NAME = 'mrvn_coliseum_materials'
BASE = 'world/dev/dev_gray_512'
BLEND = 'world/mud/canyonlands_mud_01_ws_to_canyonlands_crater_mud_01_bm'


def orient_cube_faces(cube):
    """Recover VTF face rotations/reflections by matching adjoining edges."""
    variants=[]
    for im in cube:
        a=np.asarray(im.resize((128,128)),dtype=np.float32)[:,:,:3]/255
        variants.append([np.fliplr(np.rot90(a,k)) if flip else np.rot90(a,k)
                         for flip in (False,True) for k in range(4)])
    costs=[];seen=set();t=np.linspace(-.98,.98,100)
    for face in range(6):
        axis=face//2;negative=face%2
        for edge in range(4):
            u=np.full_like(t,-1 if edge==0 else 1) if edge<2 else t
            v=t if edge<2 else np.full_like(t,-1 if edge==2 else 1)
            if axis==0:d=np.stack((np.full_like(t,-1 if negative else 1),u if negative else -u,-v))
            elif axis==1:d=np.stack((-u if negative else u,np.full_like(t,-1 if negative else 1),-v))
            else:d=np.stack((u,-v if negative else v,np.full_like(t,-1 if negative else 1)))
            other_axis=max((a for a in range(3) if a!=axis),key=lambda a:abs(d[a,0]))
            other=other_axis*2+int(d[other_axis,0]<0)
            pair=tuple(sorted((face,other)))
            if pair in seen:continue
            seen.add(pair);neg=other%2;den=np.abs(d[other_axis])
            if other_axis==0:ou=(d[1] if neg else -d[1])/den;ov=-d[2]/den
            elif other_axis==1:ou=(-d[0] if neg else d[0])/den;ov=-d[2]/den
            else:ou=d[0]/den;ov=(-d[1] if neg else d[1])/den
            def samples(images,x,y):
                ix=np.clip(((x+1)*64).astype(int),0,127);iy=np.clip(((y+1)*64).astype(int),0,127)
                return np.stack([im[iy,ix] for im in images])
            a=samples(variants[face],u,v);b=samples(variants[other],ou,ov)
            costs.append((face,other,np.mean((a[:,None]-b[None,:])**2,axis=(2,3))))
    combinations=np.array(list(itertools.product(range(8),repeat=6)),dtype=np.int8)
    score=np.zeros(len(combinations))
    for a,b,cost in costs:score+=cost[combinations[:,a],combinations[:,b]]
    best=combinations[np.argmin(score)]
    result=[]
    for im,k in zip(cube,best):
        im=im.rotate(int(k%4)*90)
        if k>=4:im=im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        result.append(im)
    return result


def vtf_images(path):
    """Decode bounded v7.5 BC1 VTF top mips, including cubemap faces."""
    b = Path(path).read_bytes()
    if b[:4] != b'VTF\0' or struct.unpack_from('<2I', b, 4) != (7, 5):
        raise ValueError('Expected VTF 7.5')
    w, h = struct.unpack_from('<2H', b, 16)
    flags = struct.unpack_from('<I', b, 20)[0]
    frames = struct.unpack_from('<H', b, 24)[0]
    fmt = struct.unpack_from('<I', b, 52)[0]
    if not 0 < w <= 8192 or not 0 < h <= 8192 or frames != 1 or fmt != 13:
        raise ValueError('Expected bounded single-frame BC1 VTF')
    faces = 6 if flags & 0x4000 else 1
    resources = struct.unpack_from('<I', b, 68)[0]
    high = None
    for i in range(resources):
        tag, at = struct.unpack_from('<II', b, 80 + i * 8)
        if tag == 0x30:
            high = at
    if high is None:
        raise ValueError('VTF has no high-resolution resource')
    size = lambda x, y: max(1, (x + 3) // 4) * max(1, (y + 3) // 4) * 8
    at = high + sum(size(max(1, w >> m), max(1, h >> m)) * faces for m in range(1, b[56]))
    n = size(w, h)
    if at + n * faces > len(b):
        raise ValueError('VTF image outside file')
    header = bytearray(128)
    struct.pack_into('<4s7I', header, 0, b'DDS ', 124, 0x81007, h, w, n, 0, 1)
    struct.pack_into('<II4s', header, 76, 32, 4, b'DXT1')
    struct.pack_into('<I', header, 108, 0x1000)
    return [Image.open(io.BytesIO(header + b[at + f*n:at + (f+1)*n])).convert('RGBA') for f in range(faces)]


def build(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    project = output / 'project'
    assets = project / 'assets'
    assets.mkdir(parents=True)
    source = RPak(args.tf2_rpak)
    target = ApexRPak(args.apex_rpak)
    sm = {n.lower(): a for a, n in source.materials()}
    # Native packs contain world and rigid-model variants with identical names.
    # BSP world geometry requires the world shader variant.
    tm = {n.lower(): a for a, n in target.materials() if target.material(a)[0]['shaderType']=='wldc'}
    names = json.loads(args.materials.read_text())
    lookup = {int(x['guid'], 16): x['asset_name'] for x in csv.DictReader(args.asset_list.open())}
    pngs = {}
    for p in args.textures.rglob('*.png'):
        pngs.setdefault(p.name.lower(), []).append(p)
    files, textures, manifest = [], {}, {}
    target_defaults = target.material(tm[BASE])[0]['$textures']

    def texture(path, srgb):
        key = (str(path.resolve()), srgb)
        if key in textures:
            return textures[key]
        tag = hashlib.sha256((str(path.resolve()) + str(srgb)).encode()).hexdigest()[:20]
        name = 'texture/mrvn_coliseum/' + tag + '.rpak'
        im = Image.open(path).convert('RGBA')
        levels = []
        while True:
            levels.append((im.width, im.height, im.tobytes()))
            if im.size == (1, 1):
                break
            im = im.resize((max(1, im.width // 2), max(1, im.height // 2)), Image.Resampling.BOX)
        write_dds(assets / Path(name).with_suffix('.dds'), levels, srgb)
        files.append({'_type': 'txtr', '_path': name, '$disableStreaming': True})
        textures[key] = name
        return name

    def resolve(guid, slot, family):
        raw = lookup.get(int(guid, 16))
        basename = Path(raw.replace('\\', '/')).stem.lower() + '.png' if raw else None
        candidates = pngs.get(basename, [])
        if candidates:
            # Identical exports occur in primary and colpass folders.
            hashes = {hashlib.sha256(p.read_bytes()).digest() for p in candidates}
            if len(hashes) > 1:
                preferred = [p for p in candidates if p.parent.name.lower() == family]
                if len(preferred) != 1:
                    raise ValueError(f'Ambiguous texture: {basename}')
                candidates = preferred
            return texture(candidates[0], slot in (0, 3, 23, 26))
        if slot == 0 and family != 'dev_gray_512_wld':
            raise ValueError(f'Missing source albedo: {raw or guid}')
        return target_defaults.get(str(slot), target_defaults['1'] if slot in (15,24) else '0x0')

    dome_image = vtf_images(args.vtf_root / 'materials/effects/dev_scanline_small_mip.vtf')[0]
    dome_image.save(output / 'dome-scanline.png')
    cube=orient_cube_faces(vtf_images(args.vtf_root / 'materials/skies/skycube.vtf'))
    for i, face in enumerate(cube):
        face.save(output / f'dome-cube-{i}.png')
    # Static approximation of Source's two-layer holographic dome. Reproject
    # its original cubemap into spherical UVs; no replacement sky art is used.
    h,w=1024,2048
    lat=(np.arange(h)[:,None]+.5)*np.pi/h
    lon=(np.arange(w)[None,:]+.5)*2*np.pi/w-np.pi
    x=np.sin(lat)*np.cos(lon);y=np.sin(lat)*np.sin(lon);z=np.broadcast_to(np.cos(lat),(h,w))
    axis=np.argmax(np.abs(np.stack((x,y,z))),axis=0)
    rgb=np.zeros((h,w,3),dtype=np.float32)
    for a in range(3):
        v=(x,y,z)[a]
        for negative in (False,True):
            chosen=(axis==a)&((v<0)==negative);den=np.maximum(np.abs(v),1e-8)
            if a==0:u=(-y if not negative else y)/den;vv=-z/den
            elif a==1:u=(x if not negative else -x)/den;vv=-z/den
            else:u=x/den;vv=(y if not negative else -y)/den
            face=np.asarray(cube[2*a+int(negative)],dtype=np.float32)[:,:,:3]/255
            ix=np.clip(((u+1)*.5*face.shape[1]).astype(int),0,face.shape[1]-1)
            iy=np.clip(((vv+1)*.5*face.shape[0]).astype(int),0,face.shape[0]-1)
            rgb[chosen]=face[iy[chosen],ix[chosen]]
    scan=np.asarray(dome_image,dtype=np.float32)[:,:,:3]/255
    scan=scan[(np.arange(h)[:,None]*4)%scan.shape[0],(np.arange(w)[None,:]*4)%scan.shape[1]]
    # Preserve source layer colors; baked Fresnel is the arena-center view.
    rgb=np.clip(rgb*1.1+scan*np.array([.3,.6,1.])* .35,0,1)
    Image.fromarray((rgb*255).astype('uint8')).save(output/'dome-composite.png')

    for name in names:
        if name.startswith('tools/') or name == BASE:
            manifest[name] = {'target': name, 'native': True}
            continue
        dome = name == 'world/test/kodai_fake_screen_01_world'
        sky = name.startswith('models/vistas/')
        is_blend = name.endswith('_bm') and name in sm
        template = BLEND if is_blend else 'tools/toolsblack' if (sky or dome) else BASE
        src_spec = source.material(sm[name])[0] if not dome else None
        tag = hashlib.sha256(name.encode()).hexdigest()[:16]
        target_name = 'world/mrvn_coliseum/' + tag
        primary, uber = target.material(tm[template])
        family = name.rsplit('/', 1)[-1] + ('_fix' if sky else '_wld')
        slots = copy.deepcopy(primary['$textures'])
        if dome:
            slots = {'0': texture(output / 'dome-composite.png', True)}
        else:
            for slot, guid in src_spec['$textures'].items():
                index = int(slot)
                if index in (0, 1, 2, 3, 22, 23, 24, 25, 26):
                    target_slot = 28 if index == 26 else index
                    slots[str(target_slot)] = resolve(guid, index, family)
            if sky:
                slots = {'0': slots['0']}
        suffix = primary['shaderType']
        colpath = f'material/{target_name}_colpass_{suffix}.rpak'
        for part, path in (('_colpass', colpath), ('', f'material/{target_name}_{suffix}.rpak')):
            spec, buf = target.material(tm[template + part])
            spec['name'] = target_name + part
            spec['$textures'] = slots
            if src_spec:
                spec['width'], spec['height'] = src_spec['width'], src_spec['height']
            if not part:
                spec['$colpassMaterial'] = colpath
            if dome:
                spec['rasterizerFlags'] = '0x2'
            p = assets / Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.with_suffix('.json').write_text(json.dumps(spec, indent=2))
            p.with_suffix('.uber').write_bytes(buf)
            files.append({'_type': 'matl', '_path': path})
        manifest[name] = {'target': target_name, 'template': template, 'shader_type': suffix,
                          'source_textures': src_spec['$textures'] if src_spec else {},
                          'target_textures': slots, 'unlit': sky or dome,
                          'dome_effect_pending': False,
                          'dome_effect_approximation': 'Static cubemap and scanline composite; animated scrolling and view-dependent Fresnel are not reproduced' if dome else None}
    build = dict(version=8, name=PAK_NAME, assetsDir=str(assets), outputDir=str(project / 'build'),
                 keepDevOnly=True, compressLevel=0, hasDynamicLibrary=False, files=files)
    build_path = project / 'build.json'
    build_path.write_text(json.dumps(build, indent=2))
    with (output / 'repak.log').open('wb') as log:
        subprocess.run([str(args.repak.resolve()), str(build_path)], cwd=project,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    built = ApexRPak(project / 'build' / (PAK_NAME + '.rpak'))
    actual = {n.lower() for _, n in built.materials()}
    missing = {x['target'] for x in manifest.values() if not x.get('native')} - actual
    if missing:
        raise ValueError(f'Built RPak lacks materials: {missing}')
    (output / 'materials.json').write_text(json.dumps(manifest, indent=2))
    return dict(materials=len(manifest), textures=len(textures), assets=len(built.assets),
                rpak=str(project / 'build' / (PAK_NAME + '.rpak')))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('tf2-rpak', 'apex-rpak', 'materials', 'asset-list', 'textures', 'vtf-root', 'repak', 'output'):
        p.add_argument('--' + flag, type=Path, required=True)
    print(json.dumps(build(p.parse_args()), indent=2))
