"""Retro analog gauge widget using QPainter."""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QSizePolicy, QWidget


# Colour zones: (start_pct, end_pct, colour)
ZONES = [
    (0, 60, QColor(30, 180, 50)),    # green
    (60, 80, QColor(220, 160, 0)),   # amber
    (80, 100, QColor(210, 40, 30)),  # red
]

NEEDLE_ZONE_COLORS = {
    "green": QColor(30, 220, 60),
    "amber": QColor(255, 180, 0),
    "red": QColor(230, 50, 40),
}


def _needle_color(pct: float) -> QColor:
    if pct < 60:
        return NEEDLE_ZONE_COLORS["green"]
    elif pct < 80:
        return NEEDLE_ZONE_COLORS["amber"]
    else:
        return NEEDLE_ZONE_COLORS["red"]


class GaugeWidget(QWidget):
    """Retro analog speedometer-style gauge.

    Features:
    - Semicircular arc (180°) with coloured zones
    - Major tick marks every 10% and minor every 2%
    - Usage needle (thick, coloured by zone)
    - Elapsed-time needle (thin, grey) behind usage needle
    - Digital readout below the dial
    """

    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self._used_pct: float = 0.0
        self._elapsed_pct: float = 0.0
        self._resets_label: str = ""
        self._no_data: bool = True

        self.setMinimumSize(280, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_usage(self, used_pct: float, elapsed_pct: float, resets_label: str = "") -> None:
        """Update gauge values and trigger repaint."""
        self._used_pct = max(0.0, min(100.0, used_pct))
        self._elapsed_pct = max(0.0, min(100.0, elapsed_pct))
        self._resets_label = resets_label
        self._no_data = False
        self.update()

    def set_no_data(self) -> None:
        self._no_data = True
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event=None) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw(painter)
        painter.end()

    def _draw(self, p: QPainter) -> None:
        w = self.width()
        h = self.height()

        # Reserve bottom 76px for text readout (2 lines: used, elapsed+resets combined)
        gauge_h = h - 76
        size = min(w, gauge_h * 2)  # semicircle diameter
        cx = w // 2
        cy = gauge_h  # bottom of gauge area = flat edge of semicircle

        radius = int((size // 2 - 10) * 0.75)  # 25% smaller than maximum fit
        if radius < 50:
            return

        # Background panel
        p.fillRect(0, 0, w, h, QColor(20, 20, 28))

        # Draw bezel shadow
        self._draw_bezel(p, cx, cy, radius)
        # Draw coloured arc zones
        self._draw_zones(p, cx, cy, radius)
        # Draw tick marks
        self._draw_ticks(p, cx, cy, radius)
        # Draw elapsed needle (behind)
        if not self._no_data:
            self._draw_elapsed_needle(p, cx, cy, radius, self._elapsed_pct)
        # Draw usage needle (on top)
        if not self._no_data:
            self._draw_usage_needle(p, cx, cy, radius, self._used_pct)
        # Centre hub
        self._draw_hub(p, cx, cy)
        # Text readout
        self._draw_readout(p, cx, cy, w, h)
        # Title
        self._draw_title(p, cx, w, cy, radius)

    def _pct_to_angle_rad(self, pct: float) -> float:
        """Map 0-100% to an angle in radians.

        Gauge arc: 180° semicircle, 0% at left (π), 100% at right (0).
        """
        # 0% → π (left), 100% → 0 (right)
        return math.pi - (pct / 100.0) * math.pi

    def _angle_to_point(self, cx: int, cy: int, radius: float, angle_rad: float) -> tuple[float, float]:
        return (
            cx + radius * math.cos(angle_rad),
            cy - radius * math.sin(angle_rad),
        )

    def _draw_bezel(self, p: QPainter, cx: int, cy: int, radius: int) -> None:
        # Outer metallic ring
        bezel_r = radius + 8
        rect = QRectF(cx - bezel_r, cy - bezel_r, bezel_r * 2, bezel_r * 2)

        # Metallic gradient
        grad = QLinearGradient(cx - bezel_r, cy - bezel_r, cx + bezel_r, cy + bezel_r)
        grad.setColorAt(0.0, QColor(90, 90, 100))
        grad.setColorAt(0.5, QColor(50, 50, 58))
        grad.setColorAt(1.0, QColor(90, 90, 100))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawChord(rect, 0, 180 * 16)  # semicircle

        # Inner dark background
        inner_r = radius + 2
        inner_rect = QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
        p.setBrush(QBrush(QColor(18, 18, 24)))
        p.drawChord(inner_rect, 0, 180 * 16)

    def _draw_zones(self, p: QPainter, cx: int, cy: int, radius: int) -> None:
        arc_width = max(12, radius // 6)
        inner_r = radius - arc_width

        for start_pct, end_pct, color in ZONES:
            start_angle_deg = 180 - start_pct * 180 / 100  # Qt angles
            span_deg = -(end_pct - start_pct) * 180 / 100

            outer_rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
            inner_rect = QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)

            path = QPainterPath()
            path.arcMoveTo(outer_rect, start_angle_deg)
            path.arcTo(outer_rect, start_angle_deg, span_deg)
            path.arcTo(inner_rect, start_angle_deg + span_deg, -span_deg)
            path.closeSubpath()

            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(path)

    def _draw_ticks(self, p: QPainter, cx: int, cy: int, radius: int) -> None:
        major_len = max(10, radius // 8)
        minor_len = max(5, radius // 16)

        for i in range(0, 101, 2):
            angle = self._pct_to_angle_rad(i)
            is_major = i % 10 == 0

            tick_len = major_len if is_major else minor_len
            outer_x, outer_y = self._angle_to_point(cx, cy, radius - 2, angle)
            inner_x, inner_y = self._angle_to_point(cx, cy, radius - 2 - tick_len, angle)

            color = QColor(220, 220, 220) if is_major else QColor(140, 140, 140)
            width = 2 if is_major else 1
            p.setPen(QPen(color, width))
            p.drawLine(
                QPoint(int(outer_x), int(outer_y)),
                QPoint(int(inner_x), int(inner_y)),
            )

            if is_major and i in (0, 25, 50, 75, 100):
                label = str(i)
                font = QFont("Courier", 7, QFont.Weight.Bold)
                p.setFont(font)
                p.setPen(QPen(QColor(200, 200, 200)))
                label_r = radius - 2 - major_len - 12
                lx, ly = self._angle_to_point(cx, cy, label_r, angle)
                fm = QFontMetrics(font)
                tw = fm.horizontalAdvance(label)
                p.drawText(int(lx - tw / 2), int(ly + 4), label)

    def _draw_elapsed_needle(self, p: QPainter, cx: int, cy: int, radius: int, pct: float) -> None:
        angle = self._pct_to_angle_rad(pct)
        needle_r = radius - 20

        tip_x, tip_y = self._angle_to_point(cx, cy, needle_r, angle)
        back_x, back_y = self._angle_to_point(cx, cy, -15, angle)

        p.setPen(QPen(QColor(120, 120, 130, 180), 2))
        p.drawLine(QPoint(int(back_x), int(back_y)), QPoint(int(tip_x), int(tip_y)))

    def _draw_usage_needle(self, p: QPainter, cx: int, cy: int, radius: int, pct: float) -> None:
        angle = self._pct_to_angle_rad(pct)
        needle_r = radius - 10

        # Build a tapered needle path
        tip_x, tip_y = self._angle_to_point(cx, cy, needle_r, angle)
        back_x, back_y = self._angle_to_point(cx, cy, -20, angle)

        perp_angle = angle + math.pi / 2
        half_w = 4
        base_l_x = back_x + half_w * math.cos(perp_angle)
        base_l_y = back_y - half_w * math.sin(perp_angle)
        base_r_x = back_x - half_w * math.cos(perp_angle)
        base_r_y = back_y + half_w * math.sin(perp_angle)

        path = QPainterPath()
        path.moveTo(tip_x, tip_y)
        path.lineTo(base_l_x, base_l_y)
        path.lineTo(base_r_x, base_r_y)
        path.closeSubpath()

        color = _needle_color(pct)
        p.setBrush(QBrush(color))
        p.setPen(QPen(color.darker(130), 1))
        p.drawPath(path)

    def _draw_hub(self, p: QPainter, cx: int, cy: int) -> None:
        r = 8
        grad = QRadialGradient(cx - 2, cy - 2, r)
        grad.setColorAt(0.0, QColor(200, 200, 210))
        grad.setColorAt(1.0, QColor(80, 80, 90))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(50, 50, 60), 1))
        p.drawEllipse(QPoint(cx, cy), r, r)

    def _draw_readout(self, p: QPainter, _cx: int, cy: int, w: int, _h: int) -> None:
        readout_y = cy + 20  # extra gap so arc hub doesn't overlap text
        if self._no_data:
            p.setFont(QFont("Courier", 11, QFont.Weight.Bold))
            p.setPen(QPen(QColor(120, 120, 130)))
            p.drawText(QRect(0, readout_y, w, 50), Qt.AlignmentFlag.AlignHCenter, "N/A")
            return

        # Used percentage (large)
        used_text = f"{self._used_pct:.1f}%"
        font_large = QFont("Courier", 17, QFont.Weight.Bold)
        p.setFont(font_large)
        color = _needle_color(self._used_pct)
        p.setPen(QPen(color))
        p.drawText(QRect(0, readout_y, w, 32), Qt.AlignmentFlag.AlignHCenter, f"Used: {used_text}")

        # Elapsed + resets on one line, extends wider than "Used" line above
        font_small = QFont("Courier", 10)
        p.setFont(font_small)
        p.setPen(QPen(QColor(155, 158, 178)))
        elapsed_part = f"Elapsed: {self._elapsed_pct:.1f}%"
        resets_part = f"  Resets: {self._resets_label}" if self._resets_label else ""
        p.drawText(QRect(0, readout_y + 32, w, 20), Qt.AlignmentFlag.AlignHCenter, elapsed_part + resets_part)

    def _draw_title(self, p: QPainter, _cx: int, w: int, cy: int = 0, radius: int = 0) -> None:
        if not self._title:
            return
        font = QFont("Courier", 11, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(QColor(160, 165, 210)))
        # Position title just above the bezel arc so it never overlaps
        bezel_top = cy - (radius + 8)
        title_y = max(3, bezel_top - 22)
        p.drawText(QRect(0, title_y, w, 22), Qt.AlignmentFlag.AlignHCenter, self._title)
