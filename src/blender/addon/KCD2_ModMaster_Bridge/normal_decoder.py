"""DDS block decoding, independent of Blender's unsupported BC5S image loader.

KCD2 textureLib.cfi GetXYNormalMap reads .yx from signed BC5; GetNormalMap
reconstructs positive Z. DDS scanlines run top to bottom, Blender pixels bottom
to top. The bridge GLB UVs are flipped by Blender's importer, so tangent Y must
also change sign. No color transform is applied to these vector components.
"""
from pathlib import Path
import struct
import numpy as np


def decode_bc4_blocks(blocks, signed=False):
    blocks = np.asarray(blocks, dtype=np.uint8).reshape(-1, 8)
    ends = blocks[:, :2].astype(np.int16)
    if signed:
        ends = np.maximum(np.where(ends > 127, ends - 256, ends), -127)
    ends = ends.astype(np.float32) / (127 if signed else 255)
    a, b = ends[:, 0], ends[:, 1]
    table = np.empty((len(blocks), 8), dtype=np.float32)
    table[:, :2] = ends
    for i in range(2, 8):
        table[:, i] = np.where(a > b, ((8-i)*a+(i-1)*b)/7,
                              ((6-i)*a+(i-1)*b)/5 if i < 6 else (-1 if signed else 0) if i == 6 else 1)
    bits = np.zeros(len(blocks), dtype=np.uint64)
    for i in range(6):
        bits |= blocks[:, i+2].astype(np.uint64) << (8*i)
    indices = ((bits[:, None] >> (3*np.arange(16, dtype=np.uint64))) & 7).astype(np.intp)
    return np.take_along_axis(table, indices, axis=1)


def read_bc_dds(path):
    data = Path(path).read_bytes()
    if data[:4] != b'DDS ' or len(data) < 148 or data[84:88] != b'DX10':
        raise ValueError(f'Expected DX10 DDS: {path}')
    height, width = struct.unpack_from('<II', data, 12)
    fmt = struct.unpack_from('<I', data, 128)[0]
    if fmt not in (80, 81, 83, 84):
        raise ValueError(f'Unsupported block format {fmt}: {path}')
    channels = 2 if fmt in (83, 84) else 1
    bw, bh = (width+3)//4, (height+3)//4
    length = bw*bh*8*channels
    if len(data) < 148+length:
        raise ValueError(f'Incomplete DDS top mip: {path}')
    blocks = np.frombuffer(data, np.uint8, count=length, offset=148).reshape(-1, channels, 8)
    result = np.empty((height, width, channels), np.float32)
    for c in range(channels):
        tiles = decode_bc4_blocks(blocks[:, c], fmt in (81, 84))
        result[:, :, c] = tiles.reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh*4, bw*4)[:height, :width]
    return result, fmt


def decode_normal(path):
    rg, fmt = read_bc_dds(path)
    if fmt not in (83, 84):
        raise ValueError(f'Expected BC5 normal, got {fmt}')
    if fmt == 83:
        rg = rg*2-1
    # Actual KCD2 shader swizzle, then adapt its V-down tangent basis.
    x, y = rg[:, :, 1], -rg[:, :, 0]
    z = np.sqrt(np.maximum(0, 1-x*x-y*y))
    xyz = np.stack((x, y, z), axis=-1)
    xyz /= np.maximum(np.linalg.norm(xyz, axis=-1, keepdims=True), 1e-8)
    return xyz*.5+.5
