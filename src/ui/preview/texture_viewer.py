"""2D Texture Viewer for KCD2 DDS textures.

Features:
- Checkerboard transparent background
- Zoom modes: Fit, 100%, 200%
- Channel extraction: RGB, R, G, B, ALPHA (critical for _ddna textures where alpha is gloss)
- Metadata banner: Resolution, DXGI/FourCC format, Mip count, Alpha status
"""
from __future__ import annotations

import io
import struct
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui import theme

# DXGI Format ID lookup
DXGI_FORMAT_NAMES = {
    0: "UNKNOWN",
    2: "R32G32B32A32_FLOAT",
    10: "R16G16B16A16_FLOAT",
    28: "R8G8B8A8_UNORM",
    29: "R8G8B8A8_UNORM_SRGB",
    70: "BC1_TYPELESS",
    71: "BC1_UNORM",
    72: "BC1_UNORM_SRGB",
    73: "BC2_TYPELESS",
    74: "BC2_UNORM",
    75: "BC2_UNORM_SRGB",
    76: "BC3_TYPELESS",
    77: "BC3_UNORM",
    78: "BC3_UNORM_SRGB",
    79: "BC4_TYPELESS",
    80: "BC4_UNORM",
    81: "BC4_SNORM",
    82: "BC5_TYPELESS",
    83: "BC5_UNORM",
    84: "BC5_SNORM",
    94: "BC6H_TYPELESS",
    95: "BC6H_UF16",
    96: "BC6H_SF16",
    97: "BC7_TYPELESS",
    98: "BC7_UNORM",
    99: "BC7_UNORM_SRGB",
}


def parse_dds_metadata(data: bytes) -> dict[str, Any]:
    """Parses DDS header structure (128 bytes + optional DX10 header)."""
    if len(data) < 128 or data[:4] != b"DDS ":
        return {"valid": False}

    h_size, flags, height, width, pitch, depth, mips = struct.unpack("<IIIIIII", data[4:32])
    pf_size, pf_flags, fourcc, rgb_bits, r_mask, g_mask, b_mask, a_mask = struct.unpack(
        "<II4sIIIII", data[76:108]
    )

    fourcc_str = fourcc.decode("ascii", errors="ignore").rstrip("\x00")
    dxgi_name = ""
    dxgi_id = None

    if fourcc == b"DX10" and len(data) >= 148:
        dxgi_id = struct.unpack("<I", data[128:132])[0]
        dxgi_name = DXGI_FORMAT_NAMES.get(dxgi_id, f"DXGI_{dxgi_id}")

    has_alpha = bool((pf_flags & 0x1) or a_mask or (dxgi_id in (28, 29, 74, 75, 77, 78, 98, 99)))

    return {
        "valid": True,
        "width": width,
        "height": height,
        "mips": max(mips, 1),
        "fourcc": fourcc_str or "Uncompressed",
        "dxgi_id": dxgi_id,
        "dxgi_name": dxgi_name,
        "has_alpha": has_alpha,
    }


class TextureCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.raw_image: QImage | None = None
        self.display_pixmap: QPixmap | None = None
        self.channel_mode = "RGB"  # "RGB", "R", "G", "B", "A"
        self.zoom_mode = "Fit"      # "Fit", "100%", "200%"
        self.custom_scale = 1.0

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Pre-render checkerboard tile
        self._checker_tile = QPixmap(16, 16)
        p = QPainter(self._checker_tile)
        p.fillRect(0, 0, 8, 8, QColor(36, 38, 42))
        p.fillRect(8, 0, 8, 8, QColor(48, 51, 56))
        p.fillRect(0, 8, 8, 8, QColor(48, 51, 56))
        p.fillRect(8, 8, 8, 8, QColor(36, 38, 42))
        p.end()

    def set_image(self, qimg: QImage | None) -> None:
        self.raw_image = qimg
        self._update_channel_pixmap()

    def set_channel(self, mode: str) -> None:
        self.channel_mode = mode
        self._update_channel_pixmap()

    def set_zoom(self, zoom: str) -> None:
        self.zoom_mode = zoom
        self.update()

    def _update_channel_pixmap(self) -> None:
        if self.raw_image is None or self.raw_image.isNull():
            self.display_pixmap = None
            self.update()
            return

        img = self.raw_image.convertToFormat(QImage.Format_RGBA8888)
        w, h = img.width(), img.height()

        if self.channel_mode == "RGB":
            self.display_pixmap = QPixmap.fromImage(img)
            self.update()
            return

        # Extract individual channel using numpy
        ptr = img.bits()
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 4)).copy()

        ch_idx = {"R": 0, "G": 1, "B": 2, "A": 3}.get(self.channel_mode, 0)
        ch_data = arr[:, :, ch_idx]

        # Convert to grayscale RGBA
        gray_arr = np.zeros_like(arr)
        gray_arr[:, :, 0] = ch_data
        gray_arr[:, :, 1] = ch_data
        gray_arr[:, :, 2] = ch_data
        gray_arr[:, :, 3] = 255

        out_img = QImage(
            gray_arr.data, w, h, w * 4, QImage.Format_RGBA8888
        ).copy()
        self.display_pixmap = QPixmap.fromImage(out_img)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()

        painter.fillRect(0, 0, w, h, QColor(18, 19, 22))

        if self.display_pixmap is None or self.display_pixmap.isNull():
            painter.setPen(QColor(theme.TEXT_DIM))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "No texture loaded or preview unavailable for this format.",
            )
            return

        pw = self.display_pixmap.width()
        ph = self.display_pixmap.height()

        # Calculate display size
        if self.zoom_mode == "Fit":
            scale = min((w - 40) / max(pw, 1), (h - 40) / max(ph, 1), 1.0)
            dw = int(pw * scale)
            dh = int(ph * scale)
        elif self.zoom_mode == "100%":
            dw, dh = pw, ph
        elif self.zoom_mode == "200%":
            dw, dh = pw * 2, ph * 2
        else:
            dw, dh = pw, ph

        dx = (w - dw) // 2
        dy = (h - dh) // 2
        target_rect = QRect(dx, dy, dw, dh)

        painter.drawTiledPixmap(target_rect, self._checker_tile)

        painter.drawPixmap(target_rect, self.display_pixmap)

        painter.setPen(QColor(60, 65, 75))
        painter.drawRect(target_rect)


class TextureViewer2D(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Top Controls Toolbar
        toolbar = QFrame()
        toolbar.setStyleSheet(f"background: {theme.BG1}; border-bottom: 1px solid {theme.BORDER};")
        t_lay = QHBoxLayout(toolbar)
        t_lay.setContentsMargins(10, 6, 10, 6)
        t_lay.setSpacing(8)

        # Channel Buttons
        t_lay.addWidget(QLabel("Channels:"))
        self.btn_rgb = QPushButton("RGB")
        self.btn_r = QPushButton("R")
        self.btn_g = QPushButton("G")
        self.btn_b = QPushButton("B")
        self.btn_a = QPushButton("ALPHA")

        self.btn_rgb.setCheckable(True)
        self.btn_r.setCheckable(True)
        self.btn_g.setCheckable(True)
        self.btn_b.setCheckable(True)
        self.btn_a.setCheckable(True)
        self.btn_rgb.setChecked(True)

        self.btn_group = QButtonGroup(self)
        for b in (self.btn_rgb, self.btn_r, self.btn_g, self.btn_b, self.btn_a):
            self.btn_group.addButton(b)
            t_lay.addWidget(b)

        self.btn_rgb.clicked.connect(lambda: self.canvas.set_channel("RGB"))
        self.btn_r.clicked.connect(lambda: self.canvas.set_channel("R"))
        self.btn_g.clicked.connect(lambda: self.canvas.set_channel("G"))
        self.btn_b.clicked.connect(lambda: self.canvas.set_channel("B"))
        self.btn_a.clicked.connect(lambda: self.canvas.set_channel("A"))

        t_lay.addSpacing(16)

        # Zoom options
        t_lay.addWidget(QLabel("Zoom:"))
        self.zoom_cb = QComboBox()
        self.zoom_cb.addItems(["Fit", "100%", "200%"])
        self.zoom_cb.currentTextChanged.connect(self._on_zoom_changed)
        t_lay.addWidget(self.zoom_cb)

        t_lay.addStretch(1)

        lay.addWidget(toolbar)

        # Canvas
        self.canvas = TextureCanvas(self)
        lay.addWidget(self.canvas, 1)

        # Bottom Info Bar
        self.info_bar = QFrame()
        self.info_bar.setStyleSheet(f"background: {theme.BG1}; border-top: 1px solid {theme.BORDER}; padding: 4px 10px;")
        info_lay = QHBoxLayout(self.info_bar)
        info_lay.setContentsMargins(10, 4, 10, 4)

        self.lbl_dims = QLabel("—")
        self.lbl_format = QLabel("—")
        self.lbl_mips = QLabel("—")
        self.lbl_alpha = QLabel("—")

        for lbl in (self.lbl_dims, self.lbl_format, self.lbl_mips, self.lbl_alpha):
            lbl.setObjectName("Dim")
            info_lay.addWidget(lbl)
        info_lay.addStretch(1)

        lay.addWidget(self.info_bar)

    def _on_zoom_changed(self, text: str) -> None:
        self.canvas.set_zoom(text)

    def load_texture_data(self, raw_bytes: bytes, filename: str) -> None:
        """Parses DDS or image bytes and displays it."""
        meta = parse_dds_metadata(raw_bytes)

        if meta.get("valid"):
            fmt_str = meta["dxgi_name"] or meta["fourcc"]
            self.lbl_dims.setText(f"Dimensions: {meta['width']} × {meta['height']}")
            self.lbl_format.setText(f"Format: {fmt_str}")
            self.lbl_mips.setText(f"Mip levels: {meta['mips']}")
            self.lbl_alpha.setText(f"Alpha: {'Yes' if meta['has_alpha'] else 'No'}")
        else:
            self.lbl_dims.setText(f"Size: {len(raw_bytes):,} bytes")
            self.lbl_format.setText(f"File: {filename}")
            self.lbl_mips.setText("")
            self.lbl_alpha.setText("")

        # Attempt to decode with Pillow or Qt
        loaded_qimg = None
        try:
            pil_img = Image.open(io.BytesIO(raw_bytes))
            pil_img = pil_img.convert("RGBA")
            data = pil_img.tobytes("raw", "RGBA")
            loaded_qimg = QImage(
                data, pil_img.width, pil_img.height, QImage.Format_RGBA8888
            ).copy()
        except Exception:
            # Fallback to direct QImage
            qimg = QImage()
            if qimg.loadFromData(raw_bytes):
                loaded_qimg = qimg

        self.canvas.set_image(loaded_qimg)
