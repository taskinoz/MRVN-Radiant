#!/usr/bin/env python3
"""Convert a Java Minecraft world to an editable TF2/Northstar map.

Pass --world and --name for any world: the build is found automatically, or set
--bounds, --anchor and --spawns yourself. See docs/respawn/RESPAWN_MINECRAFT_PORTS.md.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Minecraft inputs/assets remain local, with their original ownership.
"""
import argparse
from collections import Counter
import copy
from functools import lru_cache
import hashlib
import io
import itertools
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import zipfile

from PIL import Image, ImageChops
from build_northstar_test_mod import box_brush, enclosure
from build_quake_materials import mip_chain, write_dds, solid
from compiler_regression import entity
from pack_vpk import pack_files
from rpak import RPak
from validate_records import validate, load_records
from inspect_bsp import inspect
import numpy as np
import stbsp
from minecraft_world import sections
from minecraft_scenery import menu_stage, sky_dome, sky_texture, sky_void_texture

SCALE = 48
VERSION = '0.5.2'
# Each map owns its asset names: every installed mod's pak loads with Coliseum,
# and a shared name would make one map draw the other map's copy of a texture.
ASSET_ROOT = 'world/minecraft_ports/'
# World units per mesh cluster, so distant parts of the build still frustum cull.
MESH_CLUSTER = 3072
# UMA lost whole sections at wide FOV with 3139 world meshes and none with 929.
# The engine limit behind this was not identified; the budget is measured.
MESH_BUDGET = 1000
MAX_MESH_CLUSTER = 24576
BARRIER_HEADROOM = 192
BARRIER_THICKNESS = 64
TORCH_SPACING = 6  # blocks
MAX_TORCHES = 96
TORCH_DARK = .2  # fraction of sky rays that get out
SKY_RADIUS = 16000
# Above the gameplay dome's top, so the stage can't be seen from the arena.
MENU_Z = 18000
LOADSCREEN_SIZE = (1920, 1080)
SPAWN_SIGHT = 8  # blocks
# Same values as retail mp_glitch's four ziplines.
ROPE_KEYS = dict(Zipline='1',RopeMaterial='cable/zipline.vmt',ZiplineSagEnable='0',ZiplineSagHeight='50',
                 ZiplineMoveSpeedScale='1',ZiplineAutoDetachDistance='200',Width='2',Slack='25',Subdiv='2',MoveSpeed='64',TextureScale='1',
                 PositionInterpolator='2',spawnflags='1',Type='0',UseWind='0',Dangling='0',Collide='0',Breakable='0',
                 Barbed='0',disableX360='0',mingpulevel='0',mincpulevel='0',maxgpulevel='0',maxcpulevel='0')
FACES = ('down', 'up', 'south', 'east', 'north', 'west')
NORMALS = {'down':(0,-1,0),'up':(0,1,0),'south':(0,0,1),
           'north':(0,0,-1),'east':(1,0,0),'west':(-1,0,0)}
SKIP = {'air','cave_air','void_air','barrier','light','structure_void',
        'structure_block','command_block','chain_command_block','repeating_command_block',
        'short_grass','grass','tall_grass','large_fern','fern','poppy','dandelion',
        'fire_coral_fan','dead_bush','redstone_wire','tripwire','tripwire_hook'}
# Terrain and command setups a world may have around its build, ignored when finding it.
NATURAL = {'air','cave_air','void_air','stone','granite','diorite','andesite','deepslate','tuff','dirt','grass_block',
           'coarse_dirt','podzol','sand','red_sand','sandstone','gravel','clay','water','lava','bedrock','snow','ice',
           'short_grass','grass','tall_grass','fern','large_fern','seagrass','kelp','kelp_plant','dandelion','poppy',
           'command_block','chain_command_block','repeating_command_block','structure_block','redstone_wire','repeater','comparator'}
# Settings for the two worlds this importer was developed on. Bounds were chosen by
# inspecting them; UMA's glass is the author's roof, and Glitch's pit bottoms out seven
# blocks below its only other low floor, like retail's hole.
PRESETS = {
    'uma':dict(bounds=(-144,16,-64,32,75,56),anchor=(-48,33,0),spawns=((-100,0),(2,0)),display_name='UMA (Minecraft)',
               author='BirthdayTrain',source_url='https://www.planetminecraft.com/project/ru-titanfall-2-uma/',
               invisible_block=['white_stained_glass:50']),
    'glitch':dict(bounds=(-64,188,-68,180,225,48),anchor=(64,199,-8),spawns=((42,9),(143,-16)),display_name='Glitch (Minecraft)',
                  author='Oblivering',source_url='https://www.planetminecraft.com/project/glitch-titanfall-2/',
                  kill_z=-192,iron_bar_ziplines=True,spawn_open_sky=True,fill_floor_notches=True)}


def largest_group(cells):
    """Largest group of touching chunks, weighted by the authored blocks in them."""
    remaining=set(cells);best=[]
    while remaining:
        pending=[remaining.pop()];group=[]
        while pending:
            cell=pending.pop();group.append(cell)
            for step in itertools.product((-1,0,1),repeat=2):
                near=(cell[0]+step[0],cell[1]+step[1])
                if near in remaining:remaining.remove(near);pending.append(near)
        if sum(cells[c] for c in group)>sum(cells[c] for c in best):best=group
    return best


def largest_band(layers,gap=8,sparse=8):
    """Heights of the fullest run of layers; worlds stack test copies above each other."""
    best=();run=[];empty=0
    for y in range(min(layers),max(layers)+gap+1):
        if layers.get(y,0)<sparse:
            empty+=1
            if empty>=gap and run:
                if sum(layers[v] for v in run)>sum(layers[v] for v in best):best=tuple(run)
                run=[]
        else:
            empty=0;run.append(y)
    return (best[0],best[-1])


def detect_build(world):
    """Find the main build in a world: (bounds, anchor, spawns), all in Minecraft coordinates."""
    cells=Counter();columns={}
    for (x,y,z),palette,values in sections(world):
        authored=[state['Name'].split(':')[-1] not in NATURAL for state in palette]
        if not any(authored):continue
        cell=(x//16,z//16);layers=columns.setdefault(cell,Counter())
        for i,v in enumerate(values):
            if authored[v]:cells[cell]+=1;layers[y+i//256]+=1
    cells=Counter({c:n for c,n in cells.items() if n>=32})
    if not cells:raise ValueError('no authored build found; pass --bounds, --anchor and --spawns')
    group=largest_group(cells)
    layers=Counter()
    for c in group:layers.update(columns[c])
    low,high=largest_band(layers)
    bounds=(min(c[0] for c in group)*16,low,min(c[1] for c in group)*16,max(c[0] for c in group)*16+15,high,max(c[1] for c in group)*16+15)
    blocks=select_world(world,bounds)
    kept=[(x,y,z) for x,y,z,state in blocks if state['Name'].split(':')[-1] not in NATURAL]
    bounds=(*(min(p[i] for p in kept) for i in range(3)),*(max(p[i] for p in kept) for i in range(3)))
    # The main floor is the commonest walkable surface; glass roofs and barriers are not floors.
    filled={(x,y,z) for x,y,z,state in blocks}
    walkable={(x,y,z) for x,y,z,state in blocks if 'glass' not in state['Name'] and state['Name']!='minecraft:barrier'}
    floors=Counter(y for x,y,z in walkable if bounds[0]<=x<=bounds[3] and bounds[2]<=z<=bounds[5] and (x,y+1,z) not in filled)
    cx,cz=(bounds[0]+bounds[3])//2,(bounds[2]+bounds[5])//2
    anchor=(cx,floors.most_common(1)[0][0],cz)
    if bounds[3]-bounds[0]>=bounds[5]-bounds[2]:
        inset=(bounds[3]-bounds[0])*7//20;spawns=((cx-inset,cz),(cx+inset,cz))
    else:
        inset=(bounds[5]-bounds[2])*7//20;spawns=((cx,cz-inset),(cx,cz+inset))
    return bounds,anchor,spawns,glass_roof_rules(blocks,bounds)


def glass_roof_rules(blocks,bounds):
    """Invisible-block rules for glass layers that cover the build: an author's containment."""
    layers=Counter((state['Name'].split(':')[-1],y) for x,y,z,state in blocks if 'glass' in state['Name'])
    area=(bounds[3]-bounds[0]+1)*(bounds[5]-bounds[2]+1)
    roofs={}
    for (name,y),count in layers.items():
        if count>=area/4:roofs[name]=min(roofs.get(name,y),y-3)
    return [f'{name}:{y}' for name,y in sorted(roofs.items())]


def resolve_settings(args):
    """Fill unset options from the world's preset, then from detecting the build."""
    for key,value in PRESETS.get(args.name,{}).items():
        if getattr(args,key) in (None,False,[]):setattr(args,key,value)
    if not (args.bounds and args.anchor and args.spawns):
        if not args.world:raise ValueError('--blocks needs --bounds, --anchor and --spawns')
        bounds,anchor,spawns,roofs=detect_build(args.world)
        print(f'detected bounds {bounds}, anchor {anchor}, spawn areas {spawns}, invisible glass roofs {roofs}',flush=True)
        args.invisible_block=args.invisible_block or roofs
        args.bounds=args.bounds or bounds;args.anchor=args.anchor or anchor;args.spawns=args.spawns or spawns
    args.display_name=args.display_name or args.name.replace('_',' ').title()+' (Minecraft)'
    args.author=args.author or 'Unknown';args.source_url=args.source_url or ''
    args.spawns=[tuple(s) for s in args.spawns]
    return args


def fill_floor_notches(blocks,floor_y):
    """Blocks completing the main floor's rectangle where empty columns reach its edge.

    Unfinished worlds can miss a corner of terrain. Enclosed holes such as pits stay open.
    """
    floor=[(x,z,state) for x,y,z,state in blocks if y==floor_y]
    if not floor:return []
    columns={(x,z) for x,y,z,_ in blocks}
    x0,x1=min(f[0] for f in floor),max(f[0] for f in floor)
    z0,z1=min(f[1] for f in floor),max(f[1] for f in floor)
    edge=[(x,z) for x in range(x0,x1+1) for z in (z0,z1)]+[(x,z) for x in (x0,x1) for z in range(z0,z1+1)]
    pending=[c for c in edge if c not in columns];empty=set(pending)
    while pending:
        x,z=pending.pop()
        for near in ((x+1,z),(x-1,z),(x,z+1),(x,z-1)):
            if near in empty or near in columns or not (x0<=near[0]<=x1 and z0<=near[1]<=z1):continue
            empty.add(near);pending.append(near)
    state=json.loads(Counter(json.dumps(f[2],sort_keys=True) for f in floor).most_common(1)[0][0])
    return [[x,floor_y,z,state] for x,z in sorted(empty)]


def select_world(world, bounds):
    blocks=[]
    for (x,y,z),palette,values in sections(world,bounds):
        for i,v in enumerate(values):
            p=(x+i%16,y+i//256,z+(i//16)%16);state=palette[v]
            if state['Name'] in ('minecraft:air','minecraft:cave_air','minecraft:void_air'):continue
            if all(bounds[j]<=p[j]<=bounds[j+3] for j in range(3)):blocks.append([*p,state])
    return blocks


class Models:
    def __init__(self, jar):
        self.jar = zipfile.ZipFile(jar)
        self.omitted = Counter()
        self.approximated = Counter()

    @lru_cache(None)
    def model(self, name):
        name = name.removeprefix('minecraft:')
        raw = json.loads(self.jar.read('assets/minecraft/models/'+name+'.json'))
        parent = copy.deepcopy(self.model(raw['parent'])) if 'parent' in raw else {}
        tex = {**parent.get('textures', {}), **raw.get('textures', {})}
        parent.update(raw); parent['textures'] = tex
        return parent

    @staticmethod
    def matches(condition, props):
        if 'OR' in condition: return any(Models.matches(c, props) for c in condition['OR'])
        if 'AND' in condition: return all(Models.matches(c, props) for c in condition['AND'])
        return all(str(props.get(k, '')) in str(v).split('|') for k,v in condition.items())

    @staticmethod
    def rotate(p, rx, ry, center=8):
        x,y,z = [v-center for v in p]
        # Minecraft blockstate rotations are clockwise looking down each axis.
        for _ in range(rx//90 % 4): y,z = z,-y
        for _ in range(ry//90 % 4): x,z = -z,x
        return tuple(round(v+center,6) for v in (x,y,z))

    @lru_cache(None)
    def shapes(self, encoded):
        state = json.loads(encoded); name = state['Name'].split(':')[-1]
        if name in SKIP or name.endswith(('_sign','_wall_sign','_banner','_wall_banner')):
            self.omitted[name] += 1; return ()
        try: definition = json.loads(self.jar.read('assets/minecraft/blockstates/'+name+'.json'))
        except KeyError:
            self.omitted[name] += 1; return ()
        props = state.get('Properties', {}); applies = []
        for variant, spec in definition.get('variants', {}).items():
            condition = dict(pair.split('=') for pair in variant.split(',') if pair)
            if self.matches(condition, props): applies.append(spec); break
        for part in definition.get('multipart', []):
            if self.matches(part.get('when', {}), props): applies.append(part['apply'])
        result = []; seen = set()
        for spec in applies:
            if isinstance(spec, list): spec = spec[0]
            model = self.model(spec['model']); tex = model.get('textures', {})
            for el in model.get('elements', []):
                lo,hi = el['from'], el['to']
                if any(a==b for a,b in zip(lo,hi)):
                    self.omitted[name] += 1; continue
                if el.get('rotation', {}).get('angle', 0):
                    self.approximated[name] += 1
                points = [self.rotate(p,spec.get('x',0),spec.get('y',0))
                          for p in itertools.product(*zip(lo,hi))]
                a = tuple(min(p[j] for p in points) for j in range(3))
                b = tuple(max(p[j] for p in points) for j in range(3))
                if (a,b) in seen: continue  # overlay faces, e.g. grass
                seen.add((a,b)); mats = {}
                for face, data in el['faces'].items():
                    t = data['texture']; visited = set()
                    while t.startswith('#'):
                        if t in visited: raise ValueError('cyclic model texture')
                        visited.add(t); t = tex[t[1:]]
                    t = t.removeprefix('minecraft:').removeprefix('block/')
                    normal = self.rotate(NORMALS[face],spec.get('x',0),spec.get('y',0),0)
                    dest = next(k for k,v in NORMALS.items() if v==normal)
                    mats[dest] = t
                material = tuple(mats.get(f,'_nodraw') for f in FACES)
                if not any(t!='_nodraw' for t in material): continue
                result.append((a,b,material))
        return tuple(result)


def merge_cubes(cubes):
    """Lossless greedy rectangular merging, keyed by all six face materials."""
    remaining = dict(cubes); boxes = []
    for pos in sorted(cubes):
        if pos not in remaining: continue
        mat = remaining[pos]; x,y,z = pos
        X=x+1
        while remaining.get((X,y,z))==mat: X+=1
        Z=z+1
        while all(remaining.get((a,y,Z))==mat for a in range(x,X)): Z+=1
        Y=y+1
        while all(remaining.get((a,Y,c))==mat for a in range(x,X) for c in range(z,Z)): Y+=1
        for a in range(x,X):
            for b in range(y,Y):
                for c in range(z,Z): del remaining[a,b,c]
        boxes.append(((x,y,z),(X,Y,Z),mat))
    return boxes


def zipline_routes(blocks):
    """Endpoints of Glitch's iron-bar lines: the block-built stand-ins for ziplines."""
    remaining={(x,y,z) for x,y,z,s in blocks if s['Name']=='minecraft:iron_bars'}
    routes=[]
    while remaining:
        pending=[remaining.pop()];line=[]
        while pending:
            p=pending.pop();line.append(p)
            for step in itertools.product((-1,0,1),repeat=3):
                q=tuple(a+b for a,b in zip(p,step))
                if q in remaining:remaining.remove(q);pending.append(q)
        axis=max((0,2),key=lambda a:max(p[a] for p in line)-min(p[a] for p in line))
        ends=[[p for p in line if p[axis]==edge] for edge in (min(p[axis] for p in line),max(p[axis] for p in line))]
        routes.append([tuple(sum(p[i] for p in end)/len(end)+.5 for i in range(3)) for end in ends])
    return sorted(routes)


def torch_sites(cubes,occupied,starts):
    """Wall spots in dark areas pilots can reach: [(x,y,z,dx,dz)] with (dx,dz) toward the wall."""
    lo=[min(p[i] for p in occupied)-1 for i in range(3)];hi=[max(p[i] for p in occupied)+1 for i in range(3)]
    air=set();pending=[s for s in starts if s not in occupied]
    air.update(pending)
    while pending:
        x,y,z=pending.pop()
        for near in ((x+1,y,z),(x-1,y,z),(x,y+1,z),(x,y-1,z),(x,y,z+1),(x,y,z-1)):
            if near in air or near in occupied or not all(lo[i]<=near[i]<=hi[i] for i in range(3)):continue
            air.add(near);pending.append(near)
    rays=[(math.cos(e)*math.cos(a),math.sin(e),math.cos(e)*math.sin(a)) for e in (.35,.8,1.25) for a in (i*math.tau/6 for i in range(6))]
    def openness(p):
        escaped=0
        for ray in rays:
            for step in range(1,48):
                q=tuple(round(p[i]+ray[i]*step) for i in range(3))
                if q in cubes:break
                if q[1]>hi[1]:escaped+=1;break
            else:escaped+=1
        return escaped/len(rays)
    found=[]
    for x,y,z in sorted(air):
        # A checkerboard is plenty at this spacing, and reaches walls on any row or column.
        if (x+z)%2 or (x,y-1,z) not in air or (x,y-2,z) not in cubes:continue
        wall=next(((dx,dz) for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)) if (x+dx,y,z+dz) in cubes),None)
        if wall is None:continue
        amount=openness((x,y,z))
        if amount<TORCH_DARK:found.append((amount,x,y,z,*wall))
    chosen=[]
    for _,x,y,z,dx,dz in sorted(found):
        if all(math.dist((x,y,z),q[:3])>=TORCH_SPACING for q in chosen):chosen.append((x,y,z,dx,dz))
        if len(chosen)==MAX_TORCHES:break
    return chosen


def torch_parts(x,y,z,dx,dz):
    """Stick and flame boxes on the wall, plus a light position, in Minecraft coordinates."""
    fx,fz=x+.5+dx*.5,z+.5+dz*.5
    def box(low,high):
        if dx:a=(min(fx,fx-dx*.1875),low,z+.4375);b=(max(fx,fx-dx*.1875),high,z+.5625)
        else:a=(x+.4375,low,min(fz,fz-dz*.1875));b=(x+.5625,high,max(fz,fz-dz*.1875))
        return a,b
    stick=(*box(y+.2,y+.68),('_torch_stick',)*6)
    flame=(*box(y+.68,y+.82),('_torch_flame',)*6)
    return [stick,flame],(fx-dx*.6,y+.8,fz-dz*.6)


def barrier_boxes(lo,hi,bottom):
    """Roof and four walls around the build's bounds, in world units."""
    t=BARRIER_THICKNESS;top=hi[2]+BARRIER_HEADROOM
    a=(lo[0]-t,lo[1]-t);b=(hi[0]+t,hi[1]+t)
    return [((a[0],a[1],top),(b[0],b[1],top+t)),
            ((a[0],a[1],bottom),(lo[0],b[1],top)),((hi[0],a[1],bottom),(b[0],b[1],top)),
            ((lo[0],a[1],bottom),(hi[0],lo[1],top)),((lo[0],hi[1],bottom),(hi[0],b[1],top))]


def build_loadscreen(out,args,level):
    """Retail loadscreen pak: one 1920x1080 single-mip BC1 texture and one _gen material."""
    assets=out/'loadscreen-assets'
    im=Image.open(args.loadscreen).convert('RGBA')
    if im.size!=LOADSCREEN_SIZE:raise ValueError('loadscreen must be 1920x1080')
    name='loadscreens/'+level+'_widescreen'
    texture='texture/'+name+'.rpak';material='material/'+name+'_gen.rpak'
    write_dds_bc1(assets/Path(texture).with_suffix('.dds'),[(*im.size,im.tobytes())])
    spec=json.loads(args.loadscreen_template.with_suffix('.json').read_text())
    spec.update(name=name);spec['$textures']={'0':texture}
    dst=assets/material;dst.parent.mkdir(parents=True,exist_ok=True)
    dst.with_suffix('.json').write_text(json.dumps(spec,indent=2))
    shutil.copyfile(args.loadscreen_template.with_suffix('.uber'),dst.with_suffix('.uber'))
    manifest={'version':7,'name':level+'_loadscreen','keepDevOnly':True,'assetsDir':str(assets),
              'outputDir':str(out/'pak-build'),'compressLevel':0,'hasDynamicLibrary':False,
              'files':[{'_type':'txtr','_path':texture,'$disableStreaming':True},{'_type':'matl','_path':material}]}
    (out/'build-loadscreen.json').write_text(json.dumps(manifest,indent=2))
    with (out/'repak-loadscreen.log').open('wb') as log:
        subprocess.run([str(args.repak.resolve()),str(out/'build-loadscreen.json')],cwd=out,stdout=log,stderr=subprocess.STDOUT,check=True)
    return out/'pak-build'/(level+'_loadscreen.rpak')


def visibility_coverage(records):
    """Check reachable refs, including byte-count truncation missed by ranges."""
    seen=set();objects=set();pending=[0]
    while pending:
        index=pending.pop()
        if index in seen:continue
        if not 0<=index<len(records[119]):raise ValueError('visibility child out of bounds')
        seen.add(index);node=records[119][index]
        children,count,first,ref=node[3],node[4],node[9],node[10]
        objects.update(r[0] for r in records[120][ref:ref+count])
        pending.extend(range(first,first+children))
    expected=set(range(records[123][0][2]))
    missing=expected-objects
    if missing:raise ValueError(f'{len(missing)} world meshes unreachable through visibility tree')
    return {'reachable_nodes':len(seen),'reachable_objects':len(objects),'expected_world_meshes':len(expected),'missing_world_meshes':0}


def bc1_block_encode(pixels):
    """Encode N 4x4 RGB blocks. Nearest-upscaled texels are mostly uniform blocks."""
    luma=pixels@np.array((.299,.587,.114))
    index=np.arange(len(pixels))
    hi=pixels[index,luma.argmax(1)].astype(np.int32);lo=pixels[index,luma.argmin(1)].astype(np.int32)
    def r565(c): return (c[...,0]>>3)<<11|(c[...,1]>>2)<<5|c[...,2]>>3
    def rgb(v): return np.stack(((v>>11&31)*255//31,(v>>5&63)*255//63,(v&31)*255//31),-1)
    c0,c1=r565(hi),r565(lo)
    swap=c0<c1;c0,c1=np.where(swap,c1,c0),np.where(swap,c0,c1)
    a,b=rgb(c0),rgb(c1)
    palette=np.stack((a,b,(2*a+b)//3,(a+2*b)//3),1)
    distance=((pixels[:,:,None,:].astype(np.int32)-palette[:,None,:,:])**2).sum(-1)
    picks=np.where(c0[:,None]==c1[:,None],0,distance.argmin(-1)).astype(np.uint32)
    bits=(picks<<(2*np.arange(16,dtype=np.uint32))).sum(1,dtype=np.uint32)
    return np.stack((c0.astype(np.uint32)|c1.astype(np.uint32)<<16,bits),1).astype('<u4').tobytes()


def bc1_level(width,height,data):
    rows=np.frombuffer(data,np.uint8).reshape(height,width,4)[...,:3]
    rows=np.pad(rows,((0,-height%4),(0,-width%4),(0,0)),'edge')
    h,w=rows.shape[:2]
    blocks=rows.reshape(h//4,4,w//4,4,3).transpose(0,2,1,3,4).reshape(-1,16,3)
    return bc1_block_encode(blocks)


def write_dds_bc1(path,levels):
    """Opaque sRGB BC1 DDS. A 256px RGBA8 mip chain costs 350 KB; UMA's 49 MB of those
    rendered only low mips in-game, so UMA's textures looked blurry."""
    width,height,_=levels[0]
    encoded=[bc1_level(*level) for level in levels]
    header=struct.pack('<4sI',b'DDS ',124)
    header+=struct.pack('<6I',0x1|0x2|0x4|0x1000|0x20000|0x80000,height,width,len(encoded[0]),0,len(levels))
    header+=bytes(44)
    header+=struct.pack('<2I4s5I',32,0x4,b'DX10',0,0,0,0,0)
    header+=struct.pack('<5I',0x1000|0x400000|0x8,0,0,0,0)
    header+=struct.pack('<5I',72,3,0,1,0)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(header+b''.join(encoded))


def materials(models, names, out, args, prefix):
    assets = out/'assets'; files=[]; substitutions={}
    def tx(name, levels, srgb, compress=False):
        path='texture/minecraft_ports/'+args.name+'/'+name+'.rpak'
        if compress: write_dds_bc1(assets/Path(path).with_suffix('.dds'),levels)
        else: write_dds(assets/Path(path).with_suffix('.dds'),levels,srgb)
        files.append({'_type':'txtr','_path':path,'$disableStreaming':True}); return path
    flats={str(i):tx(n,solid(c),False) for i,n,c in (
        (1,'_normal',(128,128,255,255)),(2,'_gloss',(18,18,18,255)),(3,'_spec',(5,5,5,255)))}
    shader=[]
    for name in sorted(names):
        if name=='_nodraw':
            shader.append('textures/'+prefix+name+'\n{\n $compileflag nodraw\n}\n');continue
        if name=='_clip':
            shader.append('textures/'+prefix+name+'\n{\n $compileflag nodraw\n $contentflag playerclip\n}\n');continue
        if name=='_sky': im=sky_texture()
        elif name=='_sky_void': im=sky_void_texture()
        elif name.startswith('_torch'):
            im=Image.open(io.BytesIO(models.jar.read('assets/minecraft/textures/block/torch.png'))).convert('RGBA')
            im=im.crop((7,6,9,8) if name=='_torch_flame' else (7,8,9,16)).resize((16,16),Image.Resampling.NEAREST)
        else:
            try: im=Image.open(io.BytesIO(models.jar.read('assets/minecraft/textures/block/'+name+'.png'))).convert('RGBA')
            except KeyError: raise ValueError('missing block texture '+name)
            if im.height>im.width: im=im.crop((0,0,im.width,im.width))
            if name.endswith('_leaves') and not name.startswith(('cherry','azalea','flowering_azalea')):
                im=ImageChops.multiply(im,Image.new('RGBA',im.size,(115,165,80,255)))
            if name in ('grass_block_top','grass_block_side_overlay'):
                im=ImageChops.multiply(im,Image.new('RGBA',im.size,(135,185,90,255)))
            if im.getextrema()[3][0]<255:
                base=Image.new('RGBA',im.size,(105,145,100,255) if 'leaves' in name else (172,192,201,255))
                base.alpha_composite(im);im=base
                substitutions[name]='alpha composited onto opaque backing'
        if not name.startswith('_sky'):
            im=im.resize((im.width*16,im.height*16),Image.Resampling.NEAREST)
        dest=assets/('textures/'+prefix+name+'.png');dest.parent.mkdir(parents=True,exist_ok=True);im.save(dest)
        albedo=tx(name,mip_chain(im.width,im.height,im.tobytes()),True,True)
        for suffix in ('_colpass_wld','_wld'):
            src=args.material_template.with_name(args.material_template.name+suffix)
            spec=json.loads(src.with_suffix('.json').read_text())
            spec.update(name=prefix+name+('_colpass' if suffix.startswith('_colpass') else ''),width=im.width,height=im.height)
            spec['$textures']={'0':albedo,**flats}
            spec['$colpassMaterial']='0x0' if suffix.startswith('_colpass') else 'material/'+prefix+name+'_colpass_wld.rpak'
            dst=assets/('material/'+prefix+name+suffix+'.rpak');dst.parent.mkdir(parents=True,exist_ok=True)
            dst.with_suffix('.json').write_text(json.dumps(spec,indent=2));shutil.copyfile(src.with_suffix('.uber'),dst.with_suffix('.uber'))
            files.append({'_type':'matl','_path':dst.relative_to(assets).as_posix()})
        shader.append('textures/'+prefix+name+'\n{\n $shadertype LitBumpGeneric\n'+
                      (' $compileflag sky\n' if name.startswith('_sky') else '')+
                      (' $contentflag nonsolid\n' if name.startswith('_torch') else '')+'}\n')
    shaders=assets/'shaders';shaders.mkdir(parents=True);(shaders/'minecraft_ports.shader').write_text('\n'.join(shader))
    manifest={'version':7,'name':'minecraft_'+args.name,'keepDevOnly':True,'assetsDir':str(assets),
              'outputDir':str(out/'pak-build'),'compressLevel':0,'hasDynamicLibrary':False,'files':files}
    (out/'build-rpak.json').write_text(json.dumps(manifest,indent=2))
    with (out/'repak.log').open('wb') as log:
        subprocess.run([str(args.repak.resolve()),str(out/'build-rpak.json')],cwd=out,stdout=log,stderr=subprocess.STDOUT,check=True)
    (out/'material-substitutions.json').write_text(json.dumps(substitutions,indent=2))
    return RPak(out/('pak-build/minecraft_'+args.name+'.rpak'))


def build(args):
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    args=resolve_settings(args)
    blocks=json.loads(args.blocks.read_text()) if args.blocks else select_world(args.world,args.bounds)
    if args.fill_floor_notches:
        filled=fill_floor_notches(blocks,args.anchor[1]);blocks+=filled
        print(f'filled {len(filled)} missing floor columns',flush=True)
    (out/'selected-blocks.json').write_text(json.dumps(blocks))
    models=Models(args.jar)
    prefix=ASSET_ROOT+args.name+'/'
    cubes={}; small=[]; counts=Counter(); names={'_sky','_sky_void','_nodraw'}
    anchor=tuple(args.anchor)
    invisible=[tuple(rule.split(':')) for rule in ['barrier',*(args.invisible_block or [])]]
    clip_cells={}
    def transform(p): return ((p[0]-anchor[0])*SCALE,-(p[2]-anchor[2])*SCALE,(p[1]-anchor[1])*SCALE)
    routes=zipline_routes(blocks) if args.iron_bar_ziplines else []
    for x,y,z,state in blocks:
        name=state['Name'].split(':')[-1];counts[name]+=1
        # Barrier blocks, and glass the author used as a roof, keep blocking pilots unseen.
        if any(rule[0]==name and y>=int((*rule,0)[1]) for rule in invisible):
            clip_cells[x,y,z]=('_clip',)*6;continue
        if name in SKIP or (routes and name=='iron_bars'): continue
        shapes=models.shapes(json.dumps(state,sort_keys=True))
        for lo,hi,mat in shapes:
            names.update(mat)
            if lo==(0,0,0) and hi==(16,16,16) and len(shapes)==1: cubes[x,y,z]=mat
            else: small.append((tuple(v+a/16 for v,a in zip((x,y,z),lo)),tuple(v+b/16 for v,b in zip((x,y,z),hi)),mat))
    # Find spawn sites with two blocks of air and a full solid floor. Keep
    # spawns on the primary gameplay elevation, away from decorative rooftops.
    occupied={(x,y,z):s for x,y,z,s in blocks if s['Name'].split(':')[-1] not in SKIP or (x,y,z) in clip_cells}
    candidates=[]
    sky_y=max(p[1] for p in occupied)
    spawn_targets=args.spawns
    middle=tuple((a+b)/2 for a,b in zip(*spawn_targets))
    for (x,y,z),mat in cubes.items():
        if y != anchor[1] or mat[1] in ('_sky','_nodraw') or 'glass' in mat[1] or 'leaves' in mat[1]:continue
        # Headroom above the pilot, not just two blocks: a low overhang traps the hull.
        if any((x,y+d,z) in occupied for d in (1,2,3,4)):continue
        # Sealed, unlit rooms pass every other check, but under roof beams this rule would
        # push spawns outside the arena, so maps opt in.
        if args.spawn_open_sky and any((x,top,z) in occupied for top in range(y+5,sky_y+1)):continue
        # A clear 5x5 of floor and air: a hull that fits can still look buried in a wall.
        around=tuple(itertools.product(range(-2,3),repeat=2))
        if not all((x+dx,y,z+dz) in cubes for dx,dz in around):continue
        if any((x+dx,y+d,z+dz) in occupied for dx,dz in around for d in (1,2,3)):continue
        # Open line of sight toward the middle of the map, the way the spawn faces.
        heading=math.atan2(middle[1]-z,middle[0]-x)
        if any((x+round(i*math.cos(heading)),y+2,z+round(i*math.sin(heading))) in occupied for i in range(3,SPAWN_SIGHT)):continue
        candidates.append((x,y,z))
    if len(candidates)<8: raise ValueError(f'not enough safe spawn sites on floor {anchor[1]}; set --anchor to the main floor')
    chosen=[]
    for target in spawn_targets:
        team=[]
        for p in sorted(candidates,key=lambda p:math.dist((p[0],p[2]),target)):
            if all(math.dist((p[0],p[2]),(q[0],q[2]))>=3 for q in team):team.append(p)
            if len(team)==4:break
        chosen.append(team)
    torches=torch_sites(cubes,occupied,[(x,y+1,z) for team in chosen for x,y,z in team])
    lights=[]
    for site in torches:
        parts,light=torch_parts(*site)
        small+=parts;lights.append(light);names.update(parts[0][2]+parts[1][2])
    names.add('_clip')
    stage_brushes,stage_materials=menu_stage(prefix,MENU_Z)
    names.update(stage_materials)
    boxes=merge_cubes(cubes)+small
    pak=materials(models,names,out,args,prefix)
    brushes=[]; geometry=[]
    for lo,hi,mat in boxes:
        a=transform(lo);b=transform(hi);low=tuple(min(v,w) for v,w in zip(a,b));high=tuple(max(v,w) for v,w in zip(a,b))
        lines=box_brush(low,high,'TEMP').splitlines()
        for i,m in enumerate(mat): lines[i+1]=lines[i+1].replace('TEMP',prefix+m).replace(' 0 0 0 1 1 0 0 0',' 0 0 0 0.1875 0.1875 0 0 0')
        brushes.append('\n'.join(lines));geometry.append([low,high,mat])
    lo=tuple(min(b[0][i] for b in geometry) for i in range(3));hi=tuple(max(b[1][i] for b in geometry) for i in range(3))
    # Sky dome around the build. The level script kills pilots before they reach its floor.
    sky_centre=((lo[0]+hi[0])//2,(lo[1]+hi[1])//2);sky_base=lo[2]-2000
    brushes+=sky_dome(prefix+'_sky',prefix+'_sky_void',sky_centre,SKY_RADIUS,sky_base)
    brushes+=stage_brushes
    kill_z=args.kill_z if args.kill_z is not None else lo[2]-768
    for low,high in barrier_boxes(lo,hi,min(kill_z,lo[2])-128):
        brushes.append(box_brush(low,high,prefix+'_clip'))
    for a,b,_ in merge_cubes(clip_cells):
        a=transform(a);b=transform(b)
        brushes.append(box_brush(tuple(min(v,w) for v,w in zip(a,b)),tuple(max(v,w) for v,w in zip(a,b)),prefix+'_clip'))
    def world_entity(cluster):
        return '\n'.join(['{','"classname" "worldspawn"','"skyname" "sky_day01_01"',
            '"_lightmapscale" "16"','"_bouncescale" "0"','"_skyocclusion" "1"','"_skysamples" "128"','"_skyfixedpattern" "1"',f'"_meshcluster" "{cluster}"',*(['"_viewportals" "1"'] if args.view_portals else []),*brushes,'}'])+'\n'
    text=''
    text+=entity(classname='light_environment',origin='0 0 1024',angles='45 135 0',pitch='-45',
                 _light='255 244 228 510',_ambient='232 247 255 170',lightEnvironmentIndex='*0',shadows='1')
    text+=entity(classname='mrvn_mp_menu',origin=f'0 0 {MENU_Z}',angles='0 -90 0',lightEnvironmentIndex='1')
    for x,y,z in lights:
        # Static: baked with shadows, so any number of torches costs no realtime slots.
        text+=entity(classname='light',origin=' '.join(f'{v:g}' for v in transform((x,y,z))),_light='255 224 176 300',
                     realtime='0',_zero_percent_distance='760',_fifty_percent_distance='260')
    for i,(start,end) in enumerate(routes):
        # The far end comes first and carries the name, as in retail.
        text+=entity(**ROPE_KEYS,classname='move_rope',origin=' '.join(f'{v:g}' for v in transform(end)),targetname=f'zipline_{i}')
        text+=entity(**ROPE_KEYS,classname='move_rope',origin=' '.join(f'{v:g}' for v in transform(start)),NextKey=f'zipline_{i}')
    spawninfo=[]
    for team,sites in zip((2,3),chosen):
        for x,y,z in sites:
            p=transform((x+.5,y+1,z+.5));p=(p[0],p[1],p[2]+2)
            # Blocks use +Z south and the map flips it, hence the negated Z difference.
            yaw=math.degrees(math.atan2(-(middle[1]-z-.5),middle[0]-x-.5))
            spawninfo.append({'team':team,'origin':p,'yaw':round(yaw)})
            for cls in ('info_spawnpoint_human','info_spawnpoint_human_start'):
                text+=entity(classname=cls,origin=' '.join(f'{v:g}' for v in p),angles=f'0 {round(yaw)} 0',teamnum=str(team))
    text+=entity(classname='info_player_start',origin=' '.join(str(v) for v in spawninfo[0]['origin']))
    level='mp_minecraft_'+args.name;path=out/(level+'.map')
    (out/'geometry.json').write_text(json.dumps(geometry))
    (out/'spawns.json').write_text(json.dumps(spawninfo,indent=2))
    print(f'{args.name}: {len(blocks)} blocks -> {len(boxes)} brushes, {len(names)} textures, {len(torches)} torches',flush=True)
    cluster=args.mesh_cluster
    while True:
        path.write_text(world_entity(cluster)+text)
        with (out/'compile.log').open('wb') as log:
            subprocess.run([str(args.remap.resolve()),'-game','titanfall2','-fs_basepath',str(out),'-bsp',str(path)],stdout=log,stderr=subprocess.STDOUT,check=True)
        meshes=len(load_records(path.with_suffix('.bsp'),inspect(path.with_suffix('.bsp')))[80])
        print(f'{meshes} world meshes at cluster size {cluster}',flush=True)
        if meshes<=MESH_BUDGET:break
        if cluster>=MAX_MESH_CLUSTER:raise ValueError(f'{meshes} meshes exceed the budget of {MESH_BUDGET}: too many textures or lightmap pages')
        cluster*=2
    report=validate(path.with_suffix('.bsp'));(out/'validation.json').write_text(json.dumps(report,indent=2))
    if report['issues']: raise ValueError(report['issues'])
    coverage=visibility_coverage(load_records(path.with_suffix('.bsp'),inspect(path.with_suffix('.bsp'))))
    (out/'visibility-coverage.json').write_text(json.dumps(coverage,indent=2))
    stbsp.write(out/(level+'.stbsp'),[(n,a['guid']) for a,n in pak.materials() if not n.endswith('_colpass')],lo[:2],hi[:2])
    modname='MRVN.Minecraft'+args.name.title().replace('_','');mod=out/modname;maps=mod/'mod/maps';maps.mkdir(parents=True)
    members={}
    for part in ('env','fx','script','snd','spawn'):
        p=out/(level+'_'+part+'.ent')
        if not p.exists():p.write_bytes(b'ENTITIES01\n\0')
    for p in out.glob(level+'*'):
        if p.suffix in ('.bsp','.ent','.stbsp'):
            shutil.copyfile(p,maps/p.name);members['maps/'+p.name]=p.read_bytes()
    pack_files(members,mod/'vpk','client_'+level+'.bsp.pak000')
    scripts=mod/'mod/scripts/vscripts/mp/levels';scripts.mkdir(parents=True)
    (scripts/(level+'.nut')).write_text('''global function CodeCallback_MapInit
void function CodeCallback_MapInit()
{
 ClassicMP_SetLevelIntro( ClassicMP_DefaultNoIntro_Setup, ClassicMP_DefaultNoIntro_GetLength() )
 ClassicMP_ForceDisableEpilogue( true )
 Riff_ForceTitanAvailability( eTitanAvailability.Never )
 thread KillFallenPilots()
}
void function KillFallenPilots()
{
 while ( true )
 {
  foreach ( entity player in GetPlayerArray() )
  {
   if ( IsAlive( player ) && player.GetOrigin().z < KILL_Z )
    player.TakeDamage( 10000, null, null, { damageSourceId = eDamageSourceId.fall } )
  }
  wait 0.1
 }
}
'''.replace('KILL_Z',f'{kill_z}.0'))
    paks=mod/'paks';paks.mkdir();pakname='minecraft_'+args.name+'.rpak'
    shutil.copyfile(out/'pak-build'/pakname,paks/pakname)
    aliases={level+'.rpak':'mp_coliseum.rpak'}
    # Northstar loads a mod pak named after the level's own loadscreen pak on request.
    if args.loadscreen:shutil.copyfile(build_loadscreen(out,args,level),paks/(level+'_loadscreen.rpak'))
    else:aliases[level+'_loadscreen.rpak']='mp_coliseum_loadscreen.rpak'
    (paks/'rpak.json').write_text(json.dumps({'Aliases':aliases,'Postload':{pakname:'mp_coliseum.rpak'}},indent=2))
    author=args.author;source=args.source_url
    # The loading screen and menus look up "#<level>"; without these the raw token shows.
    resource=mod/'mod/resource';resource.mkdir(parents=True)
    tokens={level:args.display_name,level+'_ALLCAPS':args.display_name.upper(),level+'_CLASSIC':args.display_name,
            level+'_CLASSIC_DESC':'Minecraft build by '+author,level+'_DESC':'Minecraft build by '+author}
    body=''.join(f'\t\t"{k}" "{v}"\n' for k,v in tokens.items())
    (resource/(level+'_english.txt')).write_bytes(b'\xff\xfe'+('"lang"\n{\n\t"Language" "english"\n\t"Tokens"\n\t{\n'+body+'\t}\n}\n').encode('utf-16-le'))
    (mod/'mod.json').write_text(json.dumps({'Name':modname,'Version':VERSION,'LoadPriority':200,'RequiredOnClient':True,
        'Description':args.display_name+'. Original Minecraft build by '+author,
        'Localisation':['resource/'+level+'_%language%.txt'],
        'Scripts':[{'Path':'mp/levels/'+level+'.nut','RunOn':'SERVER && MP && MAP_'+level}]},indent=2))
    readme=f'''# {args.display_name}: Minecraft to Titanfall 2 test port

Original Minecraft map: {author}, {source}
Original game: Respawn Entertainment. Minecraft assets: Mojang/Microsoft.
Local conversion by MRVN-Radiant. Retain these credits with any derivative.

Extract {modname} into R2Northstar/mods. In a local Northstar session use:
`map {level} tdm`

This is an experimental pilot-only geometry port. No navmesh, Titans, AI,
objective placements, Minecraft commands/redstone, or moving mechanisms.
48 Source units per block. Shape boxes follow Java blockstate/model variants;
rotated subelements use unrotated bounds. Plants, signs and zero-thickness
elements are omitted. Glass/leaf alpha is composited onto opaque backing.
Animated textures use their first frame. Per-face model UV rotations and
subrectangle UVs are approximated by world-aligned 48-unit tiling.
Safe spawn sites are selected on the primary floor. Runtime behavior still
requires in-game verification; a successful compile is not proof of playability.

Editable source: {level}.map and assets/ in the adjacent source ZIP.
Use this output directory as the editor/compiler basepath.
Third-party game assets are for local use; no redistribution license is granted.
'''
    (mod/'README.md').write_text(readme);(out/'README.md').write_text(readme)
    metadata={'level':level,'author':author,'source':source,'scale':SCALE,'anchor_minecraft':anchor,
        'selected_blocks':len(blocks),'merged_full_cubes':len(cubes),'brushes':len(boxes),
        'textures':len(names),'omitted_model_types':dict(models.omitted),
        'approximated_rotated_types':dict(models.approximated),'engine_verified':False,
        'input_sha256':hashlib.sha256((args.blocks or args.world).read_bytes()).hexdigest(),
        'selection_bounds_minecraft':args.bounds,'spawn_areas_minecraft':args.spawns,
        'world_meshes':meshes,'mesh_cluster':cluster,'torches':len(torches),'kill_z':kill_z}
    (out/'conversion.json').write_text(json.dumps(metadata,indent=2))
    with zipfile.ZipFile(out/(modname+'-'+VERSION+'.zip'),'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(mod.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(out))
    with zipfile.ZipFile(out/(modname+'-source-'+VERSION+'.zip'),'x',zipfile.ZIP_DEFLATED) as z:
        for p in [path,out/'README.md',out/'conversion.json',*sorted((out/'assets').rglob('*.png')),*sorted((out/'assets').rglob('*.shader'))]:z.write(p,p.relative_to(out))
    return metadata


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--name',required=True,type=lambda v:v if v.replace('_','').isalnum() and v.islower() else p.error('--name must be lowercase letters, digits and _'),
                   help='Map becomes mp_minecraft_NAME; uma and glitch have presets')
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--blocks',type=Path)
    source.add_argument('--world',type=Path,help='Original downloaded world ZIP')
    for name in ('jar','output','remap','repak','material-template'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--display-name',help='Name shown in-game')
    p.add_argument('--author');p.add_argument('--source-url')
    p.add_argument('--bounds',type=int,nargs=6,metavar=('X1','Y1','Z1','X2','Y2','Z2'),help='Minecraft block bounds; detected if unset')
    p.add_argument('--anchor',type=int,nargs=3,metavar=('X','Y','Z'),help='Map origin; Y is the main floor spawns stand on')
    p.add_argument('--spawns',type=int,nargs=4,metavar=('X1','Z1','X2','Z2'),help='Centre of each team\'s spawn area')
    p.add_argument('--kill-z',type=int,help='World Z below which pilots die; default is below the build')
    p.add_argument('--invisible-block',action='append',metavar='NAME[:MIN_Y]',help='Block type to make invisible but solid; barrier always is')
    p.add_argument('--iron-bar-ziplines',action='store_true',help='Turn iron bar lines into ziplines, for maps that use them that way')
    p.add_argument('--spawn-open-sky',action='store_true',help='Only spawn under open sky')
    p.add_argument('--fill-floor-notches',action='store_true',help='Complete the main floor where its rectangle is missing edge pieces')
    p.add_argument('--mesh-cluster',type=int,default=MESH_CLUSTER,help='World units per render mesh cluster')
    p.add_argument('--view-portals',action='store_true',help='Build visibility cells and portals (experimental culling)')
    p.add_argument('--loadscreen',type=Path,help='1920x1080 image; without it the map shows Coliseum\'s')
    p.add_argument('--loadscreen-template',type=Path,help='Base path of a retail loadscreen _gen material .json/.uber pair')
    parsed=p.parse_args()
    if parsed.spawns:parsed.spawns=[parsed.spawns[:2],parsed.spawns[2:]]
    print(json.dumps(build(parsed),indent=2))
