"""Check cubemap orientation recovery using a continuous synthetic sky."""
import unittest

import numpy as np
from PIL import Image

from build_apex_coliseum_materials import orient_cube_faces


class CubeOrientationTests(unittest.TestCase):
    def test_recovers_rotated_and_reflected_faces(self):
        u,v=np.meshgrid(np.linspace(-1,1,64),np.linspace(-1,1,64))
        one=np.ones_like(u)
        directions=((one,-u,-v),(-one,u,-v),(u,one,-v),
                    (-u,-one,-v),(u,v,one),(u,-v,-one))
        originals=[];scrambled=[]
        for i,xyz in enumerate(directions):
            d=np.stack(xyz,axis=2);d/=np.linalg.norm(d,axis=2)[:,:,None]
            im=Image.fromarray(np.round((d+1)*127.5).astype('uint8')).convert('RGBA')
            originals.append(im)
            changed=im.rotate((i%4)*90)
            if i%2:changed=changed.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            scrambled.append(changed)
        recovered=orient_cube_faces(scrambled)
        for expected,actual in zip(originals,recovered):
            np.testing.assert_array_equal(np.asarray(actual),np.asarray(expected))


if __name__=='__main__':
    unittest.main()
