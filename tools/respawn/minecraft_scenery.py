"""Procedural Minecraft sky dome and block-built multiplayer menu scenery."""
import math
import numpy as np
from PIL import Image
from build_northstar_test_mod import box_brush

# Minecraft's default overworld sky colours and its 12-block cloud pixels.
ZENITH=(120,167,255)
HORIZON=(192,216,255)
CLOUD_CELL=576
CLOUD_HEIGHT=8000
SKY_LEVEL=0.82  # the sky material glows at a constant level; leave room for bloom
SUN_ANGLES=(45,135)  # light_environment pitch and yaw


def cloud_tile(size=64,seed=7274):
    # Wrapping clumps like Minecraft's clouds.png: smoothed noise, thresholded.
    rng=np.random.default_rng(seed)
    noise=rng.random((size,size))
    for _ in range(3):
        noise=sum(np.roll(np.roll(noise,x,0),y,1) for x in (-1,0,1) for y in (-1,0,1))/9
    return noise>np.quantile(noise,.68)


def sky_texture(size=2048):
    # Azimuthal projection of the upper hemisphere: radius is the angle from the
    # zenith. Clouds are what a flat layer overhead looks like, so they shrink
    # toward the horizon the way Minecraft's do instead of stretching.
    axis=(np.arange(size)+.5)/size*2-1
    u,v=np.meshgrid(axis,axis)
    r=np.minimum(np.hypot(u,v),1)
    theta=r*math.pi/2
    fade=np.clip(1-np.cos(theta),0,1)**1.5
    rgb=np.stack([z+(h-z)*fade for z,h in zip(ZENITH,HORIZON)],-1)
    tan=np.tan(np.minimum(theta,1.5))/np.maximum(r,1e-6)
    tile=cloud_tile()
    x=np.floor(u*tan*CLOUD_HEIGHT/CLOUD_CELL).astype(int)%tile.shape[1]
    y=np.floor(v*tan*CLOUD_HEIGHT/CLOUD_CELL).astype(int)%tile.shape[0]
    cover=tile[y,x]*np.clip((1.45-theta)/.35,0,1)[...]
    rgb+=(np.array((255,255,255))-rgb)*cover[...,None]*.92
    # Square sun opposite the light direction.
    pitch,yaw=(math.radians(a) for a in SUN_ANGLES)
    sun=(math.pi/2-pitch)/(math.pi/2)
    su,sv=sun*math.cos(yaw-math.pi),sun*math.sin(yaw-math.pi)
    half=.055
    mask=(np.abs(u-su)<half)&(np.abs(v-sv)<half)
    rgb[mask]=(255,251,214)
    rgb=np.clip(rgb*SKY_LEVEL,0,255).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb,np.full((size,size),255,np.uint8)]),'RGBA')


def sky_void_texture():
    colour=tuple(int(c*SKY_LEVEL) for c in HORIZON)+(255,)
    return Image.new('RGBA',(64,64),colour)


def sky_dome(material,floor_material,centre=(0,0),radius=16000,base=-3000,floor=True):
    patches=[]
    # 24 azimuth sectors, 6 polar bands. UVs match sky_texture's projection;
    # row-azimuth/column-polar winding faces inward.
    for sector in range(24):
        for band in range(6):
            rows=[]
            for row in range(3):
                phi=(sector+row/2)*math.tau/24
                points=[]
                for col in range(3):
                    theta=max((band+col/2)*(math.pi/2)/6,.0001)
                    x=radius*math.sin(theta)*math.cos(phi)
                    y=radius*math.sin(theta)*math.sin(phi)
                    z=base+radius*math.cos(theta)
                    r=theta/(math.pi/2)
                    points.append(f'( {centre[0]+x:g} {centre[1]+y:g} {z:g} {.5+r*math.cos(phi)/2:g} {.5+r*math.sin(phi)/2:g} )')
                rows.append('( '+' '.join(points)+' )')
            patches.append('{\npatchDef2\n{\n'+material+'\n( 3 3 0 0 0 )\n(\n'+'\n'.join(rows)+'\n)\n}\n}')
    if floor:
        # Plain horizon colour below the floating builds, not a tiled sky image.
        patches.append(box_brush((centre[0]-radius,centre[1]-radius,base-64),(centre[0]+radius,centre[1]+radius,base),floor_material))
    return patches


def menu_stage(prefix,z):
    brushes=[]
    def box(a,b,t):
        a=(a[0],a[1],a[2]+z);b=(b[0],b[1],b[2]+z)
        brushes.append(box_brush(a,b,prefix+t).replace(' 0 0 0 1 1 0 0 0',' 0 0 0 0.1875 0.1875 0 0 0'))
    # A small grass island under its own sky, reachable only by the menu camera.
    box((-2064,-2064,-96),(2064,2064,-2),'dirt')
    box((-2064,-2064,-2),(2064,2064,0),'grass_block_top')
    # Behind the menu Titan: it stands at about (122,172) and needs clear ground
    # out to y=500 or its legs sink into the bricks.
    box((-480,576,0),(480,960,96),'stone_bricks')
    box((-360,624,96),(360,912,192),'stone_bricks')
    for x,y in ((-650,350),(700,450),(-950,850),(1050,950)):
        box((x-24,y-24,0),(x+24,y+24,336),'oak_log')
        box((x-144,y-144,240),(x+144,y+144,384),'oak_leaves')
        box((x-96,y-96,384),(x+96,y+96,432),'oak_leaves')
    for x in (-1100,1100):
        box((x-48,150,0),(x+48,246,384),'stone_bricks')
        box((x-60,138,384),(x+60,258,480),'glowstone')
    # Own dome: the gameplay dome hides this one and everything inside it.
    brushes+=sky_dome(prefix+'_sky',prefix+'_sky_void',(0,0),2040,z,floor=False)
    return brushes,{'dirt','grass_block_top','stone_bricks','oak_log','oak_leaves','glowstone'}
