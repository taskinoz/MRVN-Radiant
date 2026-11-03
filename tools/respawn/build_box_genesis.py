#!/usr/bin/env python3
"""Author a stream-inspired mp_box test yard for Northstar, without editing inputs.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
This is an approximate reconstruction, not Respawn's original map source.
Requires Pillow, remap, RePak and a previously exported native material template.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import zipfile

from PIL import Image, ImageDraw, ImageFont

from build_northstar_test_mod import box_brush, enclosure
from build_quake_materials import mip_chain, write_dds, solid
from compiler_regression import entity
from pack_vpk import pack_files
from rpak import RPak
from validate_records import validate
import stbsp

LEVEL = 'mp_box_genesis'
MOD = 'MRVN.BoxGenesis'
VERSION = '0.2.1'
SKY_MODEL = 'models/vistas/homestead_sky.mdl'
BASE_PAK = 'mp_homestead'
PREFIX = 'world/box_genesis/'
COLOURS = {'floor': (99, 102, 104), 'white': (192, 195, 193),
           'dark': (44, 47, 49), 'red': (153, 44, 43),
           'blue': (30, 96, 124), 'orange': (213, 119, 32),
           'yellow': (236, 201, 65), 'black': (20, 24, 26),
           'sky': (139, 173, 195)}


def textures(folder):
    folder.mkdir(parents=True)
    font = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 92)
    small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 24)
    images = {}
    for name, colour in COLOURS.items():
        im = Image.new('RGBA', (512, 512), (*colour, 255)); d = ImageDraw.Draw(im)
        if name not in ('black', 'sky'):
            for at in range(0, 512, 64):
                line = tuple(min(255, c + 35) for c in colour)
                d.line((at, 0, at, 511), fill=line); d.line((0, at, 511, at), fill=line)
            d.rectangle((0, 0, 511, 511), outline=tuple(min(255, c + 65) for c in colour), width=2)
        if name == 'white':
            d.text((8, 10), '512x512', font=small, fill='#55585a')
        # A flat blue backdrop avoids repeated gradient bands on the sky shell.
        images[name] = im
    for colour in ('blue', 'red'):
        im=Image.new('RGBA',(512,512),(*COLOURS[colour],255)); d=ImageDraw.Draw(im)
        d.text((256,190),'APEX',anchor='mm',font=font,fill='white')
        d.text((256,258),'L E G E N D S',anchor='mm',font=small,fill='white')
        d.line((140,287,372,287),fill='white',width=3)
        images['banner_'+colour]=im
    for h, label in ((24,'CROUCH FIRING'),(40,'STANDING FIRING'),(48,'CROUCH COVER'),
                     (64,'STANDING COVER'),(72,'STANDING FULL'),(124,'MANTLE TEST')):
        im=images['orange'].copy(); d=ImageDraw.Draw(im)
        d.rectangle((32,32,480,109),fill='#303032')
        d.text((256,72),label,anchor='mm',font=small,fill='white')
        d.text((256,275),str(h),anchor='mm',font=font,fill='#202124')
        d.line((65,150,65,405),fill='#242525',width=8)
        d.polygon(((65,128),(48,167),(82,167)),fill='#242525')
        d.polygon(((65,427),(48,389),(82,389)),fill='#242525')
        images['height_'+str(h)]=im
    for name,im in images.items(): im.save(folder/(name+'.png'))
    return images


class Yard:
    def __init__(self): self.brushes=[]; self.surfaces=[]; self.features=[]

    def box(self,lo,hi,material='white',feature=None):
        assert all(a<b for a,b in zip(lo,hi)), (lo,hi)
        brush=box_brush(lo,hi,PREFIX+material)
        if material.startswith(('banner_', 'height_')):
            # Fit sign artwork to each face rather than cropping a 512-unit tile.
            lines=brush.splitlines()
            for face,axes in enumerate(((0,1),(0,1),(0,2),(1,2),(0,2),(1,2))):
                u,v=axes;sx=(hi[u]-lo[u])/512;sy=(hi[v]-lo[v])/512
                lines[face+1]=lines[face+1].rsplit(' 0 0 0 1 1 0 0 0',1)[0]+f' {-lo[u]/sx:g} {hi[v]/sy:g} 0 {sx:g} {sy:g} 0 0 0'
            brush='\n'.join(lines)
        self.brushes.append(brush)
        x,y,z=lo; X,Y,Z=hi
        self.surfaces.extend([(material,pts) for pts in (
            [(x,y,z),(x,Y,z),(X,Y,z),(X,y,z)],
            [(x,y,Z),(X,y,Z),(X,Y,Z),(x,Y,Z)],
            [(x,y,z),(X,y,z),(X,y,Z),(x,y,Z)],
            [(X,y,z),(X,Y,z),(X,Y,Z),(X,y,Z)],
            [(X,Y,z),(x,Y,z),(x,Y,Z),(X,Y,Z)],
            [(x,Y,z),(x,y,z),(x,y,Z),(x,Y,Z)])])
        if feature:self.features.append({'name':feature,'mins':lo,'maxs':hi})

    def ramp(self,x,y,width,length,height,material):
        # A closed wedge, with a flat bottom and four side planes.
        a=(x,y,0); b=(x+width,y,0); c=(x+width,y+length,0); d=(x,y+length,0)
        e=(x,y+length,height); f=(x+width,y+length,height)
        faces=[(b,a,d),(a,b,f),(b,c,f),(c,d,e),(d,a,e)]
        self.brushes.append('{\n'+'\n'.join(' '.join('( %g %g %g )'%v for v in reversed(vs))+
            f' {PREFIX+material} 0 0 0 1 1 0 0 0' for vs in faces)+'\n}')
        for vs in ([a,b,f,e],[b,c,f],[c,d,e,f],[d,a,e]):self.surfaces.append((material,vs))


def scene():
    y=Yard()
    y.box((-3072,-2304,-64),(1792,2304,0),'floor','yard')
    # Walls bound the compact west test yard and east duelling arena.
    y.box((-3136,-2368,-64),(-3072,2368,640),'white')
    y.box((-3072,-2368,-64),(1856,-2304,640),'white')
    y.box((-3072,2304,-64),(1856,2368,640),'white')
    y.box((1792,-2304,-64),(1856,2304,640),'white')
    # East arena: red end, blue end, central low cover, side alleys.
    y.box((256,1792,0),(1792,2304,384),'red','red end platform')
    y.box((256,-2304,0),(1792,-1792,384),'blue','blue end platform')
    y.box((736,640,0),(1248,960,104),'red','red central cover')
    y.box((864,512,0),(928,640,104),'red')
    y.box((672,-1184,0),(1184,-864,104),'blue','blue central cover')
    y.box((864,-864,0),(928,-704,104),'blue')
    y.box((1600,192,0),(1648,896,104),'red')
    y.box((1600,-1408,0),(1648,-704,104),'blue')
    y.ramp(1344,1536,256,256,384,'red')
    y.ramp(1344,-1792,256,256,384,'blue')
    # Long central building: walkable north/south corridor and a cross passage.
    # It stands between the old arena and the expanded test yard, as on minimap.
    for x0,x1 in ((-256,-224),(-32,0)):
        for a,b in ((-1792,-96),(96,1280)):
            y.box((x0,a,0),(x1,b,320),'white','corridor wall')
        y.box((x0,-96,176),(x1,96,320),'white')
    y.box((-256,-1792,320),(0,1280,352),'dark','corridor roof')
    y.box((-256,-1792,0),(0,1280,8),'dark')
    # Projecting upper facade, dark windows and open aperture.
    y.box((-32,-1376,320),(16,-192,528),'white','main white facade')
    for a,b in ((-1280,-1024),(-928,-672)):
        y.box((16,a,352),(28,b,464),'black','dark upper window')
        y.box((28,a-8,344),(36,b+8,352),'dark')
        y.box((28,a-8,464),(36,b+8,472),'dark')
    y.box((-32,-576,352),(28,-560,464),'dark')
    y.box((-32,-400,352),(28,-384,464),'dark')
    y.box((-32,-560,464),(28,-400,480),'dark')
    y.box((-32,-560,336),(28,-400,352),'dark')
    # Entrance arch, with broad red header and paired blue banners.
    y.box((-32,96,0),(0,288,640),'white','banner arch south pillar')
    y.box((-32,1088,0),(0,1280,640),'white','banner arch north pillar')
    y.box((-256,288,512),(0,1088,640),'dark','arch lintel')
    y.box((0,288,516),(8,1088,636),'banner_red')
    for a in (-1584,144,1136):
        y.box((8,a,96),(16,a+96,512),'banner_blue')
        y.box((0,a-12,512),(24,a+108,528),'dark')
    # Three door test booths. Doors are authored geometry, not Apex entities.
    for a in (-1728,-1376,-1024):
        y.box((-608,a,0),(-256,a+48,256),'white')
        y.box((-608,a+256,0),(-256,a+304,256),'white')
        y.box((-608,a+48,192),(-256,a+256,256),'white')
        y.box((-608,a+48,0),(-584,a+80,192),'orange')
        y.box((-608,a+224,0),(-584,a+256,192),'orange')
        # Half open door leaves preserve a walkable opening.
        y.box((-592,a+72,0),(-400,a+88,176),'dark','door bay')
        y.box((-580,a+88,16),(-428,a+96,160),'red')
        y.box((-648,a+16,0),(-608,a+288,16),'white')
    # West-side L-shaped enclosed testing block.
    y.box((-2880,-2048,0),(-2368,-2016,320),'white')
    y.box((-2880,-2016,0),(-2848,-768,320),'white')
    y.box((-2880,-768,0),(-2368,-736,320),'white')
    y.box((-2400,-2016,0),(-2368,-1664,320),'white')
    y.box((-2400,-1472,0),(-2368,-736,320),'white')
    y.box((-2880,-2048,320),(-2368,-736,352),'white','west L block')
    y.box((-2368,-2048,0),(-2048,-1536,320),'white')
    # Firing and movement yard: orange labelled cover is measured in source units.
    for x,h in ((-2816,72),(-2464,48),(-2112,64),(-1760,24),(-1408,40)):
        y.box((x,384,0),(x+256,448,h),'height_'+str(h),'cover '+str(h))
    # Full-height mantle walls and target plinths at the back.
    for x in (-2816,-2048):
        y.box((x,1600,0),(x+640,1664,256),'orange','rear test wall')
        y.box((x+256,1588,256),(x+384,1672,288),'height_124')
        for xx in (x+64,x+320,x+576):
            y.box((xx-12,1600,256),(xx+12,1624,312),'dark')
            y.box((xx-20,1592,312),(xx+20,1632,352),'dark')
    y.ramp(-2208,768,160,384,192,'yellow')
    y.ramp(-1920,768,160,384,192,'red')
    y.ramp(-1120,1248,160,352,256,'white')
    y.box((-1152,640,0),(-896,704,160),'orange','large concealment block')
    # Approximate faceted red/yellow test dome, built from convex wedge sectors.
    cx,cy,r=-768,1824,256
    for ring in range(4):
        z0=ring*64;z1=(ring+1)*64
        r0=math.sqrt(max(1,r*r-z0*z0));r1=math.sqrt(max(1,r*r-z1*z1))
        for k in range(16):
            a=k*math.tau/16;b=(k+1)*math.tau/16
            # Truncated cone wedges, including radial planes.
            p=(cx+r0*math.cos(a),cy+r0*math.sin(a),z0)
            q=(cx+r0*math.cos(b),cy+r0*math.sin(b),z0)
            P=(cx+r1*math.cos(a),cy+r1*math.sin(a),z1)
            Q=(cx+r1*math.cos(b),cy+r1*math.sin(b),z1)
            c=(cx,cy,z0);C=(cx,cy,z1)
            mat='yellow' if ring==3 else 'red'
            # Outward normal winding agrees with box_brush (inward MAP planes).
            faces=[(q,p,c),(C,P,Q),(p,q,Q),(c,p,P),(q,c,C)]
            y.brushes.append('{\n'+'\n'.join(' '.join('( %g %g %g )'%v for v in reversed(vs))+
                f' {PREFIX+mat} 0 0 0 1 1 0 0 0' for vs in faces)+'\n}')
            y.surfaces.append((mat,[p,q,Q,P]))
    # Cross-yard beam / elevated walkway, visible in stream minimap.
    y.box((-1856,0,224),(-256,128,256),'white','elevated cross-yard beam')
    y.box((-1856,0,0),(-1792,128,224),'white')
    # Diagonal blocks in west yard.
    for i in range(5):
        y.box((-2496+i*224,-64-i*192,0),(-2368+i*224,64-i*192,96),'white')
    # East arena midpoint arch retains free movement beneath it.
    y.box((0,-160,0),(288,-96,256),'white')
    y.box((1536,-160,0),(1792,-96,256),'white')
    y.box((288,-160,256),(1536,-96,352),'white','arena cross arch')
    return y


SCRIPT = '''global function CodeCallback_MapInit
void function CodeCallback_MapInit()
{
 ClassicMP_SetLevelIntro( ClassicMP_DefaultNoIntro_Setup, ClassicMP_DefaultNoIntro_GetLength() )
 ClassicMP_ForceDisableEpilogue( true )
 Riff_ForceTitanAvailability( eTitanAvailability.Never )
 thread GenesisCheck()
}
void function GenesisCheck()
{
 wait 0.2
 TraceResults floor = TraceLine( <800,0,128>, <800,0,-128>, null, TRACE_MASK_SOLID_BRUSHONLY, TRACE_COLLISION_GROUP_NONE )
 TraceResults wall = TraceLine( <1700,0,64>, <1950,0,64>, null, TRACE_MASK_SOLID_BRUSHONLY, TRACE_COLLISION_GROUP_NONE )
 TraceResults hall = TraceLine( < -128,-1600,64>, < -128,1100,64>, null, TRACE_MASK_SOLID_BRUSHONLY, TRACE_COLLISION_GROUP_NONE )
 printl( "[MRVN.Genesis] floor=" + floor.fraction + " end=" + floor.endPos )
 printl( "[MRVN.Genesis] wall=" + wall.fraction + " corridor=" + hall.fraction )
}
'''


def build(args):
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    images=textures(out/'textures'); yard=scene()
    matroot=out/'assets'; files=[]
    def tx(name,levels,srgb):
        path='texture/box_genesis/'+name+'.rpak'
        write_dds(matroot/Path(path).with_suffix('.dds'),levels,srgb)
        files.append({'_type':'txtr','_path':path,'$disableStreaming':True});return path
    flats={slot:tx(name,solid(colour),False) for slot,name,colour in (
        ('1','normal',(128,128,255,255)),('2','gloss',(64,64,64,255)),('3','spec',(10,10,10,255)))}
    # Input is the paired JSON/uber native dev-gray material exported earlier.
    # It contains shader configuration only, never any Quake texture pixels.
    for name,im in images.items():
        albedo=tx(name,mip_chain(im.width,im.height,im.tobytes()),True)
        for suffix in ('_colpass_wld','_wld'):
            src=args.material_template.with_name(args.material_template.name+suffix)
            spec=json.loads(src.with_suffix('.json').read_text())
            spec=copy.deepcopy(spec);spec['name']=PREFIX+name+('_colpass' if suffix.startswith('_colpass') else '')
            spec['width']=512;spec['height']=512;spec['$textures']={'0':albedo,**flats}
            spec['$colpassMaterial']='0x0' if suffix.startswith('_colpass') else 'material/'+PREFIX+name+'_colpass_wld.rpak'
            dest=matroot/('material/'+PREFIX+name+suffix+'.rpak');dest.parent.mkdir(parents=True,exist_ok=True)
            dest.with_suffix('.json').write_text(json.dumps(spec,indent=2))
            shutil.copyfile(src.with_suffix('.uber'),dest.with_suffix('.uber'))
            files.append({'_type':'matl','_path':str(dest.relative_to(matroot)).replace('\\','/')})
    manifest={'version':7,'name':'box_genesis','keepDevOnly':True,'assetsDir':str(matroot),
              'outputDir':str(out/'pak-build'),'compressLevel':0,'hasDynamicLibrary':False,'files':files}
    (out/'build-rpak.json').write_text(json.dumps(manifest,indent=2))
    with (out/'repak.log').open('wb') as log:
        subprocess.run([str(args.repak.resolve()),str(out/'build-rpak.json')],cwd=out,stdout=log,stderr=subprocess.STDOUT,check=True)
    pak=RPak(out/'pak-build/box_genesis.rpak')
    names={n for _,n in pak.materials()}
    assert all(PREFIX+n in names for n in images), 'missing generated material'
    shaders=out/'assets/shaders';shaders.mkdir(parents=True,exist_ok=True)
    shader='\n'.join('textures/'+PREFIX+n+'\n{\n'+
        (' $shadertype LitBumpGeneric\n $compileflag sky\n' if n=='sky'
         else ' $shadertype LitBumpGeneric\n')+'}\n' for n in images)
    (shaders/'box_genesis.shader').write_text(shader)
    # The compiler reads dimensions from these images, as does Radiant.
    for name,im in images.items():
        dest=out/('assets/textures/'+PREFIX+name+'.png');dest.parent.mkdir(parents=True,exist_ok=True);im.save(dest)
    world=['{','"classname" "worldspawn"','"skyname" "sky_day01_01"','"_lightmapscale" "32"',
           '"_bouncescale" "0"','"_skyocclusion" "1"','"_skysamples" "128"']+yard.brushes
    world+=enclosure((-25000,-25000,-5000),(25000,25000,20000),PREFIX+'sky',margin=1024)
    world+=['}']
    text='\n'.join(world)+'\n'+entity(classname='light_environment',origin='800 0 1024',
        angles='40 135 0',pitch='-40',_light='255 244 228 510',_ambient='232 247 255 100',
        lightEnvironmentIndex='*0',shadows='1',SunSpreadAngle='1',targetname='light_environment_1')
    # Keep the vista's terrain well below the playable floor. Only its cloud
    # canopy should frame the yard; a far self-lit shell seals the background.
    text+=entity(classname='prop_static',model=SKY_MODEL,origin='-640 0 -8192',
        angles='0 90 0',modelscale='16',solid='0',flags='84',_cullradius='30000')
    text+=entity(classname='info_player_start',origin='800 0 32',angles='0 180 0')
    text+=entity(classname='info_target',targetname='mrvn_genesis_marker',origin='800 0 32')
    for team, yy in ((2,-1536),(3,1536)):
        for x in (512,768,1024,1280):
            for cls in ('info_spawnpoint_human','info_spawnpoint_human_start'):
                text+=entity(classname=cls,origin=f'{x} {yy} 32',angles=f'0 {90 if team==2 else 270} 0',teamnum=str(team))
    for yy in range(-1536,1280,384):
        text+=entity(classname='light',origin=f'-128 {yy} 224',_light='220 235 255 200',_distance='400')
    path=out/(LEVEL+'.map');path.write_text(text)
    with (out/'compile.log').open('wb') as log:
        subprocess.run([str(args.remap.resolve()),'-game','titanfall2','-fs_basepath',str(out),'-bsp',str(path)],
                       stdout=log,stderr=subprocess.STDOUT,check=True)
    report=validate(path.with_suffix('.bsp'))
    (out/'validation.json').write_text(json.dumps(report,indent=2))
    if report['issues']:raise ValueError(report['issues'])
    catalogue=out/(LEVEL+'.stbsp')
    stbsp.write(catalogue,[(name,asset['guid']) for asset,name in pak.materials() if not name.endswith('_colpass')],
                (-4224,-3456),(2944,3456))
    assert len(stbsp.read(catalogue)['materials'])==len(images)
    for part in ('env','fx','script','snd','spawn'):
        partition=out/(LEVEL+'_'+part+'.ent')
        if not partition.exists():partition.write_bytes(b'ENTITIES01\n\0')
    mod=out/MOD;maps=mod/'mod/maps';maps.mkdir(parents=True)
    sky_target=mod/'mod'/SKY_MODEL;sky_target.parent.mkdir(parents=True)
    sky_bytes=args.sky_model.read_bytes()
    if not sky_bytes.startswith(b'IDST'):raise ValueError('Sky model must be an extracted Titanfall 2 MDL')
    sky_target.write_bytes(sky_bytes)
    members={}
    for p in out.glob(LEVEL+'*'):
        if p.suffix in ('.bsp','.ent','.stbsp'):
            shutil.copyfile(p,maps/p.name);members['maps/'+p.name]=p.read_bytes()
    pack_files(members,mod/'vpk','client_'+LEVEL+'.bsp.pak000')
    scripts=mod/'mod/scripts/vscripts/mp/levels';scripts.mkdir(parents=True)
    (scripts/(LEVEL+'.nut')).write_text(SCRIPT)
    (mod/'paks').mkdir();shutil.copyfile(out/'pak-build/box_genesis.rpak',mod/'paks/box_genesis.rpak')
    (mod/'paks/rpak.json').write_text(json.dumps({'Aliases':{LEVEL+'.rpak':BASE_PAK+'.rpak',
        LEVEL+'_loadscreen.rpak':BASE_PAK+'_loadscreen.rpak'},'Postload':{'box_genesis.rpak':BASE_PAK+'.rpak'}},indent=2))
    (mod/'mod.json').write_text(json.dumps({'Name':MOD,'Version':VERSION,'LoadPriority':200,
        'RequiredOnClient':True,'Description':'Approximate Genesis dev-stream mp_box reconstruction. Load '+LEVEL+'.',
        'Scripts':[{'Path':'mp/levels/'+LEVEL+'.nut','RunOn':'SERVER && MP && MAP_'+LEVEL}]},indent=2))
    (out/'features.json').write_text(json.dumps(yard.features,indent=2))
    (out/'preview-geometry.json').write_text(json.dumps(yard.surfaces))
    repo=Path(__file__).resolve().parents[2];shutil.copyfile(repo/'GPL',mod/'COPYING')
    shutil.copyfile(repo/'docs/respawn/RESPAWN_BOX_GENESIS.md',mod/'README.md')
    package=out/(MOD+'-'+VERSION+'.zip')
    with zipfile.ZipFile(package,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(mod.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(out))
    with zipfile.ZipFile(out/(MOD+'-source-'+VERSION+'.zip'),'x',zipfile.ZIP_DEFLATED) as z:
        z.write(path,path.name)
        for p in sorted((out/'assets').rglob('*')):
            if p.is_file() and p.suffix in ('.png','.shader'):z.write(p,p.relative_to(out))
        z.write(repo/'docs/respawn/RESPAWN_BOX_GENESIS.md','README.md')
        z.write(repo/'GPL','COPYING')
    (out/'package.json').write_text(json.dumps({'level':LEVEL,'brushes':len(yard.brushes),
        'materials':len(images),'package':str(package),'sha256':hashlib.sha256(package.read_bytes()).hexdigest(),
        'engine_verified':False,'source':'User-supplied ToonCraft Live Genesis stream; visual approximation'},indent=2))
    return package


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--remap',type=Path,required=True)
    p.add_argument('--repak',type=Path,required=True)
    p.add_argument('--sky-model',type=Path,required=True,help='Locally extracted models/vistas/homestead_sky.mdl')
    p.add_argument('--material-template',type=Path,required=True,help='Base path before _wld.json / _colpass_wld.json and matching .uber')
    print(build(p.parse_args()))
