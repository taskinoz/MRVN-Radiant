#!/usr/bin/env python3
"""Experimental v37 world-scene -> v47 geometry port for local R5Reloaded.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Original encoder; version/encoding provenance and limits are in
docs/respawn/RESPAWN_TF2_TO_APEX.md. No input is modified.
"""
import argparse
import collections
import itertools
import json
import math
import re
from pathlib import Path
import shutil
import struct

from decompile_bsp import collision_owners, payload, parse_entities
from inspect_bsp import inspect, FormatError
from pack_vpk import pack_files
from tricoll import triangle_indices
from validate_records import load_records, validate

LEVEL = 'mp_mrvn_coliseum'
HEADER = 2064


def write_play_setup(root, game, level=LEVEL):
    """Create a separate local playlist, retaining the installed defaults."""
    platform=root/'platform'
    LEVEL=level
    original=(game/'platform/playlists_r5_patch.txt').read_text()
    playlist='''
        mrvn_coliseum
        {
            inherit fs_dm
            vars
            {
                name "Coliseum port preview"
                visible 1
                max_players 2
                max_teams 2
                max_team_size 1
                min_players 1
                match_ending_enabled 0
                waiting_for_players_spawning_enabled 1
                wait_for_players_forever 0
                waiting_for_players_timeout_seconds 1
                waiting_for_players_countdown_seconds 0
                character_select_time_max 0
                character_select_time_min 0
                survival_enable_gladiator_intros 0
                jump_from_plane_enabled 0
                airdrop_enabled 0
                ground_loot_enable 0
                loot_preprocessing_should_be_skipped 1
                sur_circle_start_paused 1
                enable_apex_screens 0
                skydive_ziplines_enabled 0
                flowstateEndlessFFAorTDM 1
                flowstateAutoChangeLevelEnable 0
                flowstateLockPOI 1
                flowstateLockeedPOI 0
                flowstateRandomizePOIS 0
                survival_server_restart_after_end 0
            }
            gamemodes { fs_dm { maps { mp_mrvn_coliseum 1 } } }
        }
'''
    playlist=playlist.replace('mp_mrvn_coliseum 1',LEVEL+' 1')
    text,n=re.subn(r'(\bPlaylists\s*\{)',lambda m:m[0]+playlist,original,count=1)
    if n!=1:raise FormatError('Installed playlist has no Playlists block')
    (platform/'playlists_mrvn_coliseum.txt').write_text(text)
    # Flowstate's deathmatch shared init requires a registered location for
    # each map. Extend the installed script only for this port's unique name.
    # Keep the user's existing script and all other map cases intact.
    shared_path=Path('platform/scripts/vscripts/gamemodes/fs_tdm/sh_gamemode_fsdm.nut')
    shared=(game/shared_path).read_text()
    case=f'''case "{LEVEL}":
        Shared_RegisterLocation( NewLocationSettings( "Coliseum",
            [ NewLocPair(<0,-600,32>,<0,90,0>), NewLocPair(<0,600,32>,<0,-90,0>),
              NewLocPair(<-600,0,32>,<0,0,0>), NewLocPair(<600,0,32>,<0,180,0>) ],
            <0,0,600> ) )
        break
    '''
    if f'case "{LEVEL}":' not in shared:
        shared,n=re.subn(r'(switch\s*\(GetMapName\(\)\)\s*\{)',lambda m:m[0]+'\n    '+case,shared,count=1)
        if n!=1:raise FormatError('Installed Flowstate shared init has no expected map switch')
    target=root/shared_path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(shared)
    (root/'Launch-Coliseum.cmd').write_text('@echo off\ncd /d "%~dp0"\nstart "Coliseum port preview" r5apex.exe -launcher -fnf -showdevmenu -dev -devsdk -console -novid -playlistfile playlists_mrvn_coliseum.txt\n')
    scripts=platform/'scripts';levels=scripts/'levels';levels.mkdir(parents=True,exist_ok=True)
    (levels/(LEVEL+'.rson')).write_text('When: "SERVER"\nScripts:\n[\n mp/levels/_mp_mrvn_coliseum.nut\n]\nWhen: "CLIENT"\nScripts:\n[\n]\nWhen: "SERVER || CLIENT"\nScripts:\n[\n]\n')
    vscripts=scripts/'vscripts/mp/levels';vscripts.mkdir(parents=True,exist_ok=True)
    (vscripts/'_mp_mrvn_coliseum.nut').write_text('''global function CodeCallback_MapInit

void function CodeCallback_MapInit()
{
    print( "MRVN_COLISEUM_MAP_INIT" )
    thread Coliseum_KeepPlayersInArena()
}

void function Coliseum_KeepPlayersInArena()
{
    FlagWait( "EntitiesDidLoad" )
    while ( true )
    {
        foreach ( entity player in GetPlayerArray() )
        {
            vector p = player.GetOrigin()
            if ( IsAlive( player ) && ( fabs( p.x ) > 1600 || fabs( p.y ) > 1600 || p.z < -200 || p.z > 1500 ) )
            {
                player.SetOrigin( <0,-600,64> )
                player.SetAngles( <0,90,0> )
                print( "MRVN_COLISEUM_PLAYER_READY" )
            }
        }
        wait 0.5
    }
}
''')


def packed(fmt, rows):
    return b''.join(struct.pack('<'+fmt, *row) for row in rows)


def mesh_bounds(points):
    low=[min(p[a] for p in points) for a in range(3)]
    high=[max(p[a] for p in points) for a in range(3)]
    center=tuple((low[a]+high[a])/2 for a in range(3))
    radius=max(math.dist(p,center) for p in points)
    return (*center,radius,*[(high[a]-low[a])/2 for a in range(3)],0.)


def entity(values):
    return '{\n'+''.join(f'"{k}" "{v}"\n' for k,v in values)+'}\n'


def brush_triangles(r, index):
    """Recover convex faces from active TF2 brush planes, including cuts."""
    import numpy as np
    b=r[92][index]; planes=[]
    for axis in range(3):
        for sign in (-1,1):
            n=[0.,0.,0.];n[axis]=sign;planes.append((*n,sign*b[axis]+b[axis+6]))
    for j in range(b[4]):
        at=b[9]+j;planes.append(r[1][r[85][0][6]+at-r[93][at][0]])
    if len(planes)>80:raise FormatError('Brush plane count exceeds bounded convex recovery')
    ps=np.array(planes); vertices={}
    for ids in itertools.combinations(range(len(planes)),3):
        a=ps[list(ids),:3]
        if abs(np.linalg.det(a))<1e-9:continue
        v=np.linalg.solve(a,ps[list(ids),3])
        if np.all(ps[:,:3]@v<=ps[:,3]+.02):vertices[tuple(round(x,5) for x in v)]=tuple(v)
    for plane in ps:
        face=[np.array(v) for v in vertices.values() if abs(np.dot(plane[:3],v)-plane[3])<.03]
        if len(face)<3:continue
        center=sum(face)/len(face);n=plane[:3];u=np.cross(n,[0,0,1] if abs(n[2])<.9 else [0,1,0]);u/=np.linalg.norm(u);v=np.cross(n,u)
        face.sort(key=lambda p:math.atan2(np.dot(p-center,v),np.dot(p-center,u)))
        for j in range(1,len(face)-1):yield tuple(tuple(float(x) for x in p)for p in (face[0],face[j],face[j+1]))


def collision_scene(r, omitted_props):
    result=[]
    for (kind,index),contents in collision_owners(r)[0].items():
        if kind==0:
            result.extend((contents,t)for t in brush_triangles(r,index))
        elif kind==0x40:
            h=r[69][index]
            for word, in r[66][h[7]:h[7]+h[4]]:
                t=tuple(tuple(r[3][h[6]+v])for v in triangle_indices(word))
                if len(set(t))==3:result.append((contents,t))
        elif kind==0x60:
            omitted_props.append({'source_prop_index':index,'contents':contents})
        else:raise FormatError(f'Unsupported active world collision kind {kind:#x}')
    return result


def collision_bvh(triangles):
    """Four-way hierarchy, uncompressed triangle leaves, model-local vertices.

    Node references/types occupy the low metadata byte, not the high byte.
    Bounds are four minima then four maxima per axis. Header/triangle encoding
    is provisional pending target-engine ray and hull tests.
    """
    vertices=[]; leaves=bytearray(); objects=[]; masks=[]
    def mask(value):
        if value not in masks:masks.append(value)
        if len(masks)>256:raise FormatError('Apex contents palette exceeds byte index')
        return masks.index(value)
    for contents,t in triangles:
        first=len(vertices)
        if first//1024>65535:raise FormatError('Collision vertex base exceeds leaf range')
        vertices.extend(t);at=len(leaves)//4
        leaves+=struct.pack('<2I',((first//1024)<<16),0xe0100000|(first%1024))
        lo=tuple(math.floor(min(p[a]for p in t)-.125)for a in range(3));hi=tuple(math.ceil(max(p[a]for p in t)+.125)for a in range(3))
        if any(x< -32768 or x>32767 for x in (*lo,*hi)):raise FormatError('World collision bounds exceed selected unit-scale BVH frame')
        objects.append((contents,4,at,lo,hi))
    nodes=[]
    def build(items):
        at=len(nodes);nodes.append(None)
        all_contents=0
        for item in items:all_contents|=item[0]
        contents=mask(all_contents)
        if len(items)<=4 and len({x[0]for x in items})==1:children=items
        else:
            if len({x[0]for x in items})>1:
                groups=collections.defaultdict(list)
                for item in items:groups[item[0]].append(item)
                if len(groups)<=4:parts=list(groups.values())
                else:
                    ordered=sorted(items,key=lambda x:x[0]);step=math.ceil(len(items)/4);parts=[ordered[j:j+step]for j in range(0,len(items),step)]
            else:
                axis=max(range(3),key=lambda a:max(x[4][a]for x in items)-min(x[3][a]for x in items))
                ordered=sorted(items,key=lambda x:x[3][axis]+x[4][axis]);step=math.ceil(len(items)/4);parts=[ordered[j:j+step]for j in range(0,len(items),step)]
            children=[]
            for part in parts:
                child=build(part);lo=tuple(min(x[3][a]for x in part)for a in range(3));hi=tuple(max(x[4][a]for x in part)for a in range(3));children.append((0,0,child,lo,hi))
        children+= [(0,1,0,(32767,)*3,(-32768,)*3)]*(4-len(children))
        bounds=[]
        for axis in range(3):bounds.extend(c[3][axis]for c in children);bounds.extend(c[4][axis]for c in children)
        words=[c[2]<<8 for c in children];words[0]|=contents;words[2]|=children[0][1]|children[1][1]<<4;words[3]|=children[2][1]|children[3][1]<<4
        nodes[at]=(*bounds,*words);return at
    if not objects:raise FormatError('No collision triangles recovered')
    build(objects)
    return packed('3f',vertices),packed('24h4I',nodes),bytes(leaves),packed('I',[(x,)for x in masks])


def write_bsp(path, lumps, gamelump):
    data=bytearray(HEADER);struct.pack_into('<4s3I',data,0,b'rBSP',47,1,127)
    for index,blob in sorted(lumps.items()):
        if not blob:continue
        at=(len(data)+15)&~15;data+=bytes(at-len(data))
        if index==35:
            blob=bytearray(gamelump);struct.pack_into('<I',blob,12,20)
        struct.pack_into('<4I',data,16+16*index,at,len(blob),0,0);data+=blob
    path.write_bytes(data)


def port(source, donor, output, game, material_manifest=None, static_meshes=None, prop_collision=None, level=LEVEL):
    if not re.fullmatch(r'mp_[a-z0-9_]{1,55}',level):raise FormatError('Expected a bounded lowercase multiplayer level name')
    LEVEL=level
    source,donor,output=source.resolve(),donor.resolve(),output.resolve()
    if output.exists():raise FormatError('Output must be new')
    if validate(source)['issues']:raise FormatError('Source TF2 selected-record validation failed')
    inv=inspect(source);r=load_records(source,inv);di=inspect(donor)
    if inv['version_raw']!=37 or di['version_raw']!=47:raise FormatError('Expected TF2 v37 and Apex v47')
    output.mkdir(parents=True);root=output/'R5Coliseum';maps=root/'maps';maps.mkdir(parents=True)
    source_name=source.stem;meshes=[];sorts=[];bounds=[];vertices=[];positions=list(r[3]);normals=list(r[30]);indices=[];materials=[];names_blob=bytearray();tex=[]
    first,count=r[14][0][6:8]
    pools={0:72,0x200:73,0x400:71,0x600:74}
    mapping=json.loads(material_manifest.read_text()) if material_manifest else {}
    strings=payload(source,inv,43)
    table=[x[0] for x in struct.iter_unpack('<I',payload(source,inv,44))]
    source_names=[strings[table[t[3]]:strings.index(0,table[t[3]])].decode().replace('\\','/').lower() for t in r[2]]
    def material_index(name, flags=0):
        material=mapping[name]['target'] if mapping else name
        if material not in materials:
            materials.append(material);tex.append((len(names_blob),512,512,flags));names_blob.extend(material.encode()+b'\0')
        return materials.index(material)
    for mesh in r[80][first:first+count]:
        material='WORLD/DEV/DEV_GRAY_512';flags=mesh[-1];oldsort=r[82][mesh[-2]]
        if flags&4:material='TOOLS/TOOLSSKYBOX'
        if mapping:material=source_names[oldsort[0]]
        td=material_index(material,flags);start=len(vertices);begin=len(indices);pool=r[pools[flags&0x600]]
        for word, in r[79][mesh[0]:mesh[0]+mesh[1]*3]:
            v=pool[oldsort[4]+word];uv=v[8:10]if len(v)>=12 else (.5,.5)
            if len(v)==14:
                tangent=v[-2]
            else:
                n=normals[v[1]];axis=(0.,0.,1.) if abs(n[2])<.9 else (0.,1.,0.)
                t=(n[1]*axis[2]-n[2]*axis[1],n[2]*axis[0]-n[0]*axis[2],n[0]*axis[1]-n[1]*axis[0]);length=math.sqrt(sum(x*x for x in t))
                if length<1e-8:raise FormatError('Cannot form tangent for zero source normal')
                tangent=len(normals);normals.append(tuple(x/length for x in t))
            color=sum(v[4+j]<<(8*j) for j in range(4))
            vertices.append((v[0],v[1],v[2],v[3],color,*uv,tangent));indices.append(len(vertices)-start-1)
        sorts.append((td,oldsort[1],-1,0,start));meshes.append((begin,mesh[1],0,len(vertices)-start-1,*([0]*6),len(sorts)-1,(flags&~0x600)|0x200))
        bounds.append(r[81][first+len(meshes)-1])
    # Bake static, rigid source models into world meshes. Captured DMX corners
    # reverse source winding, so restore it before emitting native BSP indices.
    added_props=[];unlit_vertices=[]
    if static_meshes:
        for item in json.loads(static_meshes.read_text()):
            prop=item['prop'];pitch,yaw,roll=map(math.radians,prop['angles_raw'])
            cp,sp,cy,sy,cr,sr=math.cos(pitch),math.sin(pitch),math.cos(yaw),math.sin(yaw),math.cos(roll),math.sin(roll)
            matrix=((cp*cy,sr*sp*cy-cr*sy,cr*sp*cy+sr*sy),(cp*sy,sr*sp*sy+cr*cy,cr*sp*sy-sr*cy),(-sp,sr*cp,cr*cp))
            def rotate(v):return tuple(sum(row[j]*v[j] for j in range(3)) for row in matrix)
            groups=collections.defaultdict(list)
            for name,_,corners in item['triangles']:groups[name.replace('\\','/').lower()].append(corners)
            for name,triangles in groups.items():
                td=material_index(name,0x400);start=len(unlit_vertices);begin=len(indices);points=[]
                for corners in triangles:
                    for c in (corners[0],corners[2],corners[1]):
                        p=rotate(c[0]);p=tuple(p[a]*prop['scale']+prop['origin'][a] for a in range(3));points.append(p)
                        pi=len(positions);positions.append(p);ni=len(normals);normals.append(rotate(c[1]))
                        tangent=c[3]['tangent'];ti=len(normals);normals.append(rotate(tangent[:3]));ti|=0x80000000 if tangent[3]<0 else 0
                        uv=c[3]['uv']
                        if name=='world/test/kodai_fake_screen_01_world':
                            d=(p[0],p[1],p[2]-64);length=math.sqrt(sum(x*x for x in d))
                            uv=((math.atan2(d[1],d[0])+math.pi)/(2*math.pi),math.acos(max(-1,min(1,d[2]/length)))/math.pi)
                        unlit_vertices.append((pi,ni,*uv,0xffffffff));indices.append(len(unlit_vertices)-start-1)
                    if name=='world/test/kodai_fake_screen_01_world':
                        us=[v[2] for v in unlit_vertices[-3:]]
                        if max(us)-min(us)>.5:
                            unlit_vertices[-3:]=[(*v[:2],v[2]+(1 if v[2]<.5 else 0),*v[3:]) for v in unlit_vertices[-3:]]
                if len(points)>65535:raise FormatError('Static mesh exceeds native vertex index range')
                # Native S3 unlit surfaces have no lightmap and use the
                # unlit surface sentinels observed in the lobby's toolsblack
                # meshes. A zero lightmap index selects the lit surface path.
                sorts.append((td,-1,0,len(points)-1,start));meshes.append((begin,len(triangles),0,len(points)-1,-256,0,0,-1,-1,0,len(sorts)-1,0x100400))
                bounds.append(mesh_bounds(points))
            added_props.append(prop['model'])
    # Native level-info boundaries describe contiguous opaque/decal/trans/sky
    # ranges. Preserve source buckets while inserting baked opaque model meshes.
    source_partitions=struct.unpack_from('<3I',payload(source,inv,123))
    buckets=[0 if i<source_partitions[0] else 1 if i<source_partitions[1] else 2 if i<source_partitions[2] else 3 for i in range(count)]+[0]*(len(meshes)-count)
    order=sorted(range(len(meshes)),key=lambda i:buckets[i]);meshes=[meshes[i] for i in order];bounds=[bounds[i] for i in order]
    partitions=[sum(b<cut for b in buckets) for cut in (1,2,3)]
    omitted_props=[]
    collision=collision_scene(r,omitted_props)
    if prop_collision:
        if prop_collision.stem!='mp_coliseum_dome_01':raise FormatError('This collision adapter targets the Coliseum dome only')
        # R2's exported .pertri retains the model's original quantized vertices.
        # Preserve its triangle winding and exact source solid-contents mask.
        lines=prop_collision.read_text().splitlines()
        if lines[0]!='r2c_pertri 1':raise FormatError('Unsupported per-triangle collision interchange')
        limits=list(map(float,lines[1].split()));nv,nt=map(int,lines[2].split())
        if not 0<nv<=1000000 or not 0<nt<=1000000 or len(lines)!=3+nv+nt:raise FormatError('Invalid per-triangle counts')
        points=[tuple(limits[a]+(limits[a+3]-limits[a])*q/65535 for a,q in enumerate(map(int,line.split()))) for line in lines[3:3+nv]]
        # This asset is the origin-zero Coliseum dome with a 90 degree yaw.
        points=[(-p[1],p[0],p[2]) for p in points]
        for line in lines[3+nv:]:
            a,b,c,flags=map(int,line.split())
            if min(a,b,c)<0 or max(a,b,c)>=nv:raise FormatError('Collision triangle outside model vertices')
            collision.append((13107840,(points[a],points[b],points[c])))
        omitted_props=[p for p in omitted_props if p['source_prop_index']!=2]
    cv,bvh,leaf,masks=collision_bvh(collision);collision_base=len(positions)
    lo=tuple(min(p[a]for p in positions)for a in range(3));hi=tuple(max(p[a]for p in positions)for a in range(3))
    l={1:payload(source,inv,1),2:packed('4I',tex),3:packed('3f',positions)+cv,14:struct.pack('<6f6i4f',*lo,*hi,0,len(meshes),0,0,collision_base,0,0,0,0,1/65536),
       15:bytes(names_blob),16:masks,17:struct.pack('<hBBI',512,0,0,0),18:bvh,19:leaf,24:b'01* env fx script snd spawn\0',30:packed('3f',normals),
       35:bytes(40),37:struct.pack('<I',2)*(len(payload(source,inv,54))//112),38:struct.pack('<I',0),39:b'\xff\xff',
       54:payload(source,inv,54),71:packed('2I2fI',unlit_vertices),72:b'',73:packed('2I2fI2fI',vertices),74:b'',79:packed('H',[(x,)for x in indices]),80:packed('IH8hHI',meshes),81:packed('8f',bounds),82:packed('4hI',sorts),83:payload(source,inv,83),98:payload(source,inv,98),
       106:struct.pack('<iI',-1,0),107:struct.pack('<3Hh',0,0,1,-1),
       119:struct.pack('<3fI3fI',*lo,0x40000000,*hi,(0x40<<24)|len(meshes)),120:packed('I',[(i,)for i in range(len(meshes))]),121:packed('3fI3fI',[(*(b[a]-b[4+a]for a in range(3)),0,*(b[a]+b[4+a]for a in range(3)),0)for b in bounds]),
       123:struct.pack('<5I3fI',*partitions,0,0,0,0,-1,1)}
    # Cell access nodes use count:8, first:16, flags:8. Direct references begin 0.
    if len(meshes)>255:raise FormatError('Prototype direct access root supports at most 255 source meshes')
    headers=list(struct.iter_unpack('<I2H',l[83]));texels=sum(w*h for _,w,h in headers)
    # Match the native S3 neutral texel's fourth byte. An all-ones fill
    # severely overexposes lit materials even when the albedo is correct.
    l[105]=b'\xff\xff\xff\x00'*texels+bytes(5*texels//2);l[122]=struct.pack('<63h',*([0]*63))
    for index in (4,101,103,104):l[index]=payload(source,inv,index)
    l[102]=b''
    world= [('classname','worldspawn'),('world_mins',' '.join(map(str,lo))),('world_maxs',' '.join(map(str,hi))),('spawnclass','idWorldspawn'),('mapversion','1')]
    l[0]=(entity(world)+entity([('classname','info_player_start'),('origin','0 0 128'),('angles','0 0 0')])+entity([('classname','info_target'),('targetname','mrvn_apex_port_marker'),('origin','0 0 128')])).encode()+b'\0'
    l[36]=b''
    empty=struct.pack('<I4sHHII5I',1,b'prps',0,47,0,20,0,0,0,0,0)
    bsp=maps/(LEVEL+'.bsp');write_bsp(bsp,l,empty)
    # Apex takes the model count from every partition's ENTITY02 header.
    for suffix in ('env','fx','script','snd','spawn'):
        text=''
        if suffix=='env':
            for e in parse_entities(payload(source,inv,0).decode(errors='replace')):
                if dict(e).get('classname')=='light_environment':text+=entity(e)
            source_env=source.parent/(source_name+'_env.ent')
            if source_env.exists():
                raw=source_env.read_bytes().split(b'\n',1)[1].decode(errors='replace')
                for e in parse_entities(raw):
                    d=dict(e)
                    if d.get('classname')=='light_environment':text+=entity([(k,('0'if k=='shadows'else v))for k,v in e])
                    # Apex sky cameras require a native model asset. The
                    # source's MDL-backed cameras cannot reference our baked
                    # world geometry; an empty model produces fallback props.
                    # The baked dome supplies the arena's visible sky instead.
        if suffix=='spawn':text+=entity([('classname','info_spawnpoint_human_start'),('origin','0 0 128'),('angles','0 0 0'),('teamnum','2')])
        (maps/(LEVEL+'_'+suffix+'.ent')).write_bytes(('ENTITIES02 num_models=1\n'+text).encode()+b'\0')
    paks=root/'paks/Win64';paks.mkdir(parents=True)
    for suffix in ('.rpak','_loadscreen.rpak'):
        if suffix=='.rpak' and material_manifest:continue
        p=game/'paks/Win64'/('mp_lobby'+suffix)
        if p.exists():shutil.copyfile(p,paks/(LEVEL+suffix))
    settings=root/'platform/scripts/levels/settings';settings.mkdir(parents=True)
    if material_manifest:
        material_pak=material_manifest.parent/'project/build/mrvn_coliseum_materials.rpak'
        # The engine keeps its native lobby RPak as a static base pack. Use
        # our unique assets as the level RPak instead of copying that lobby
        # under another name, which duplicates native asset GUIDs on reload.
        shutil.copyfile(material_pak,paks/(LEVEL+'.rpak'))
    # Follow installed custom-map dependencies for the native models and
    # shader resources referenced by Flowstate's shared gameplay scripts.
    (settings/(LEVEL+'.kv')).write_text('"LevelSet"\n{\n "PakList" { "mp_rr_canyonlands_mu1" "1" "mp_rr_desertlands_64k_x_64k" "1" "common_flowstate_small" "1" "flowstate_all_loot" "1" }\n "StreamDB" "mp_rr_desertlands_64k_x_64k"\n}\n')
    if static_meshes:write_play_setup(root,game,level)
    pack_files({f'maps/{p.name}':p.read_bytes() for p in maps.iterdir() if p.is_file()},
               root/'vpk', f'client_{LEVEL}.bsp.pak000')
    pack_files({f'maps/{p.name}':p.read_bytes() for p in maps.iterdir() if p.is_file()},
               root/'vpk', f'server_{LEVEL}.bsp.pak000')
    report={'level':LEVEL,'source':str(source),'target':'Apex S3 R5Reloaded v47','render_triangles':sum(m[1]for m in meshes),'render_meshes':len(meshes),'collision_triangles':len(collision),'collision_leaf_encoding_engine_verified':False,'collision_bvh_nodes':len(bvh)//64,
            'materials':materials,'baked_static_props':added_props,'omitted_static_props':3-len(added_props),'omitted_prop_collision':omitted_props,'limits':['This generated revision needs native loading/render/collision verification','Dome uses a static approximation of the original animated Fresnel effect','Lighting translation is provisional; no Apex bake claimed']}
    (output/'port-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--donor',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--game',type=Path,required=True)
    p.add_argument('--material-manifest',type=Path);p.add_argument('--static-meshes',type=Path)
    p.add_argument('--prop-collision',type=Path)
    p.add_argument('--level',default=LEVEL)
    print(json.dumps(port(**vars(p.parse_args())),indent=2))
