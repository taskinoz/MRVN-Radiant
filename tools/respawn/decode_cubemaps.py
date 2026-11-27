"""Decode MRVN mode-11 BC6H cubemaps.hdr.vtf from an Apex/TF2 BSP PAKFILE into PNG strips (evidence only)."""
import io, struct, sys, zipfile
import numpy as np
from PIL import Image
W = [0,4,9,13,17,21,26,30,34,38,43,47,51,55,60,64]
def half(h):
    return np.frombuffer(np.array(h, dtype=np.uint16).tobytes(), dtype=np.float16).astype(np.float32)
def unq(x):
    return 0 if x == 0 else (0xFFFF if x == 1023 else ((x << 16) + 0x8000) >> 10)
def block(b):
    v = int.from_bytes(b, 'little'); pos = 0
    def get(n):
        nonlocal pos; r = (v >> pos) & ((1 << n) - 1); pos += n; return r
    assert get(5) == 3, 'not mode 11'
    e = [[unq(get(10)) for _ in range(3)] for _ in range(2)]
    idx = [get(3)] + [get(4) for _ in range(15)]
    out = np.zeros((16, 3), np.float32)
    for p, i in enumerate(idx):
        out[p] = half([(((64 - W[i]) * e[0][c] + W[i] * e[1][c] + 32) >> 6) * 31 >> 6 for c in range(3)])
    return out
def faces(vtf, frame, mip):
    frames = struct.unpack_from('<H', vtf, 24)[0]
    off = struct.unpack_from('<I', vtf, 12)[0]
    # resource dictionary: find the image data offset ('\x30\0\0\0' entry)
    nres = struct.unpack_from('<I', vtf, 68)[0]
    for r in range(nres):
        tag, data = vtf[80 + r * 8:84 + r * 8], struct.unpack_from('<I', vtf, 84 + r * 8)[0]
        if tag[:1] == b'0': off = data
    for m in range(8, mip, -1):
        s = max(256 >> m, 4); off += frames * 6 * (s // 4) ** 2 * 16
    s = max(256 >> mip, 4); n = (s // 4) ** 2 * 16
    off += frame * 6 * n
    res = []
    for f in range(6):
        img = np.zeros((s, s, 3), np.float32)
        for k in range(n // 16):
            px = block(vtf[off + f * n + k * 16: off + f * n + k * 16 + 16]).reshape(4, 4, 3)
            by, bx = divmod(k, s // 4); img[by*4:by*4+4, bx*4:bx*4+4] = px
        res.append(img)
    return res
bsp = open(sys.argv[1], 'rb').read()
o, l = struct.unpack_from('<ii', bsp, 16 + 0x28 * 16)
z = zipfile.ZipFile(io.BytesIO(bsp[o:o + l])); vtf = z.read(z.namelist()[0])
frames = struct.unpack_from('<H', vtf, 24)[0]
rows = []
for fr in range(frames):
    fs = faces(vtf, fr, 2)
    print('frame', fr, 'mean RGB', [round(float(x), 4) for x in np.mean([f.mean((0, 1)) for f in fs], 0)], 'max', round(float(max(f.max() for f in fs)), 3))
    rows.append(np.concatenate(fs, 1))
img = np.concatenate(rows, 0)
img = img / (1 + img)  # Reinhard for viewing
Image.fromarray((np.clip(img ** (1 / 2.2), 0, 1) * 255).astype(np.uint8)).resize((img.shape[1] * 2, img.shape[0] * 2)).save(sys.argv[2])
