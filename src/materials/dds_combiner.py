"""CryEngine/KCD2 split DDS mip stream combiner."""
from __future__ import annotations


def combine_cryengine_dds(base_dds_data: bytes, parts_data: list[tuple[int, bytes]]) -> bytes:
    """Combines CryEngine/KCD2 split DDS mip streams into a valid complete DDS file.

    CryEngine streams textures by splitting the highest resolution mipmaps into
    separate files (.dds.1, .dds.2, ..., .dds.N):
      - Base .dds: contains the DDS header (128 bytes, or 148 bytes for DX10)
        plus the lowest mips (e.g. 680 bytes for 32x32 down to 4x4).
      - .dds.N: Mip 0 (highest resolution, e.g. 1024x1024 or 2048x2048).
      - .dds.1: lowest streamed mip (e.g. 64x64).

    A valid DDS file requires mips in strict descending order immediately following
    the header:
      [Header (128 or 148 bytes)]
      [Mip 0 (.dds.N)]
      [Mip 1 (.dds.N-1)]
      ...
      [Mip K (.dds.1)]
      [Lowest mips from base file tail (680 bytes)]
    """
    if not parts_data:
        return base_dds_data

    is_dx10 = len(base_dds_data) >= 88 and base_dds_data[84:88] == b"DX10"
    header_size = 148 if is_dx10 else 128
    if len(base_dds_data) < header_size:
        return base_dds_data

    header = base_dds_data[:header_size]
    lowest_mips = base_dds_data[header_size:]

    # Sort descending by part number (e.g. 5, 4, 3, 2, 1)
    parts_data.sort(key=lambda x: x[0], reverse=True)

    combined = bytearray(header)
    for _, part_bytes in parts_data:
        combined.extend(part_bytes)
    combined.extend(lowest_mips)
    return bytes(combined)
