"""Format decoding and geometry-preservation checks for Minecraft import."""
import math
import struct
import unittest

import numpy as np

from build_minecraft_ports import (BARRIER_THICKNESS, barrier_boxes, bc1_level, fill_floor_notches, glass_roof_rules, largest_band, largest_group, merge_cubes, Models,
                                   torch_parts, torch_sites, visibility_coverage, zipline_routes)
from minecraft_scenery import HORIZON, SKY_LEVEL, sky_dome, sky_texture
from minecraft_world import read_nbt


class MinecraftTests(unittest.TestCase):
    def test_nbt_compound_signed_height(self):
        data=b'\x0a\x00\x00\x01\x00\x01Y\xfc\x00'
        self.assertEqual(read_nbt(data), {'Y':-4})

    def test_nbt_rejects_truncation(self):
        with self.assertRaises(ValueError): read_nbt(b'\x0a\x00')

    def test_nbt_unsigned_packed_long(self):
        data=b'\x0a\0\0\x0c\0\x01a'+struct.pack('>iQ',1,0xffffffffffffffff)+b'\0'
        self.assertEqual(read_nbt(data)['a'],[0xffffffffffffffff])

    def test_merge_preserves_every_voxel_and_material(self):
        blocks={(x,y,z):('a',)*6 for x in range(7) for y in range(3) for z in range(5)}
        del blocks[2,1,3];blocks[4,1,2]=('b',)*6
        restored={}
        for lo,hi,mat in merge_cubes(blocks):
            for x in range(lo[0],hi[0]):
                for y in range(lo[1],hi[1]):
                    for z in range(lo[2],hi[2]):
                        self.assertNotIn((x,y,z),restored)
                        restored[x,y,z]=mat
        self.assertEqual(blocks,restored)

    def test_merge_solid_room_to_one_brush(self):
        blocks={(x,y,z):('a',)*6 for x in range(5) for y in range(3) for z in range(7)}
        self.assertEqual(merge_cubes(blocks),[((0,0,0),(5,3,7),('a',)*6)])

    def test_blockstate_rotation_keeps_normals_axial(self):
        for x in (0,90,180,270):
            for y in (0,90,180,270):
                self.assertEqual(sum(abs(v) for v in Models.rotate((1,0,0),x,y,0)),1)

    def test_wall_button_rotates_toward_its_support(self):
        # Floor contact y=0 becomes the SOUTH contact for a north-facing button.
        self.assertEqual(Models.rotate((8,0,8),90,0),(8,8,16))
        self.assertEqual(Models.rotate((8,0,8),90,90),(0,8,8))

    def test_bc1_block_is_exact_for_uniform_texels(self):
        # Upscaled Minecraft texels fill whole blocks: one endpoint, index zero.
        data=bytes((248,252,0,255))*16
        c0,bits=struct.unpack('<2I',bc1_level(4,4,data))
        self.assertEqual(c0&0xffff,0xffe0)
        self.assertEqual(bits,0)

    def test_bc1_picks_nearest_of_two_colours(self):
        white,black=(255,255,255,255),(0,0,0,255)
        data=bytes(sum(([*white]*2+[*black]*2 for _ in range(4)),[]))
        c0,bits=struct.unpack('<2I',bc1_level(4,4,data))
        self.assertEqual(c0,0x0000ffff)
        # Each row: two white (index 0), then two black (index 1).
        self.assertEqual(bits,0x50505050)

    def test_bc1_pads_small_mips_to_a_whole_block(self):
        self.assertEqual(len(bc1_level(2,2,bytes(16))),8)
        self.assertEqual(len(bc1_level(1,1,bytes(4))),8)

    def test_sky_rim_is_horizon_colour_and_opaque(self):
        sky=np.asarray(sky_texture(256))
        expected=[int(c*SKY_LEVEL) for c in HORIZON]
        self.assertLessEqual(max(abs(int(a)-b) for a,b in zip(sky[128,1][:3],expected)),4)
        self.assertTrue((sky[...,3]==255).all())

    def test_sky_dome_uvs_stay_inside_the_circular_image(self):
        text=''.join(sky_dome('sky','void',(100,200),16000,-3000,floor=False))
        points=[l.split() for l in text.split('\n') if l.startswith('( (')]
        self.assertEqual(text.count('patchDef2'),144)
        for row in points:
            values=[v for v in row if v not in '()']
            for u,v in zip(values[3::5],values[4::5]):
                self.assertLessEqual(math.hypot(float(u)-.5,float(v)-.5),.5001)

    def test_zipline_routes_join_each_stair_stepped_line_end_to_end(self):
        bars={'Name':'minecraft:iron_bars'}
        line=[[x,10+x//2,5,bars] for x in range(6)]
        other=[[x,10,20,bars] for x in range(3)]
        stone=[[0,10,5,{'Name':'minecraft:stone'}]]
        self.assertEqual(zipline_routes(line+other+stone),
                         [[(.5,10.5,5.5),(5.5,12.5,5.5)],[(.5,10.5,20.5),(2.5,10.5,20.5)]])

    def test_largest_group_ignores_a_small_detached_setup(self):
        cells={(0,0):900,(1,0):900,(1,1):900,(9,9):100}
        self.assertEqual(sorted(largest_group(cells)),[(0,0),(1,0),(1,1)])

    def test_largest_band_keeps_a_band_at_the_top_of_the_world(self):
        layers={y:20 for y in range(0,4)}
        layers.update({y:500 for y in range(100,130)})
        self.assertEqual(largest_band(layers),(100,129))

    def test_torch_goes_on_a_wall_in_a_dark_room_but_not_outdoors(self):
        cubes={}
        for x in range(-7,8):
            for z in range(-7,8):
                cubes[x,0,z]=1
                # A sealed room with a door, beside an open yard.
                for y in range(1,8):
                    if x in (-7,0) or z in (-7,7) or (y==7 and x<=0):
                        if not (x==0 and z==0 and y<4):cubes[x,y,z]=1
        sites=torch_sites(cubes,cubes,[(3,1,0)])
        self.assertTrue(sites)
        self.assertTrue(all(x<=0 for x,*_ in sites))  # the room and its doorway
        for x,y,z,dx,dz in sites:self.assertIn((x+dx,y,z+dz),cubes)

    def test_torch_touches_its_wall_and_its_light_stands_clear(self):
        parts,light=torch_parts(5,10,5,1,0)
        for low,high,_ in parts:self.assertEqual(high[0],6)
        self.assertLess(light[0],parts[0][0][0])

    def test_barrier_encloses_the_build_on_five_sides(self):
        lo,hi=(-100,-50,0),(100,50,200)
        boxes=barrier_boxes(lo,hi,-500)
        self.assertEqual(len(boxes),5)
        self.assertTrue(all(a[i]<b[i] for a,b in boxes for i in range(3)))
        self.assertEqual(min(a[0] for a,b in boxes),lo[0]-BARRIER_THICKNESS)
        self.assertEqual(max(b[2] for a,b in boxes),max(a[2] for a,b in boxes)+BARRIER_THICKNESS)
        self.assertEqual(min(a[2] for a,b in boxes),-500)

    def test_only_glass_covering_the_build_counts_as_a_roof(self):
        roof=[[x,20,z,{'Name':'minecraft:white_stained_glass'}] for x in range(10) for z in range(10)]
        window=[[0,5,z,{'Name':'minecraft:glass'}] for z in range(10)]
        self.assertEqual(glass_roof_rules(roof+window,(0,0,0,9,20,9)),['white_stained_glass:17'])

    def test_floor_fill_completes_a_corner_but_keeps_a_pit(self):
        grass={'Name':'minecraft:grass_block'}
        blocks=[[x,5,z,grass] for x in range(8) for z in range(8)
                if not (x>=6 and z>=6) and not (3<=x<=4 and 3<=z<=4)]
        filled=fill_floor_notches(blocks,5)
        self.assertEqual([(b[0],b[2]) for b in filled],[(6,6),(6,7),(7,6),(7,7)])
        self.assertTrue(all(b[1]==5 and b[3]==grass for b in filled))

    def test_multipart_alternatives(self):
        self.assertTrue(Models.matches({'OR':[{'north':'true'},{'east':'true'}]},{'east':'true'}))
        self.assertFalse(Models.matches({'half':'top|double'},{'half':'bottom'}))

    def test_visibility_detects_truncated_byte_count(self):
        records={119:[(0,0,0,0,44,300,1,1,1,0,0)],
                 120:[(i,) for i in range(300)],123:[(0,0,300,0,0,0,0)]}
        with self.assertRaisesRegex(ValueError,'256 world meshes unreachable'):
            visibility_coverage(records)

    def test_visibility_follows_bounded_child_groups(self):
        records={119:[(0,0,0,2,0,300,1,1,1,1,0),
                      (0,0,0,0,150,150,1,1,1,0,0),
                      (0,0,0,0,150,150,1,1,1,0,150)],
                 120:[(i,) for i in range(300)],123:[(0,0,300,0,0,0,0)]}
        self.assertEqual(visibility_coverage(records)['missing_world_meshes'],0)


if __name__=='__main__': unittest.main()
