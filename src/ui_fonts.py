"""Shared UI fonts for the native gauge app."""
from __future__ import annotations

from PySide6.QtGui import QFont

MONOSPACE_FONT_FAMILY = "Menlo"


def mono_font(point_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    return QFont(MONOSPACE_FONT_FAMILY, point_size, weight)


def mono_stylesheet() -> str:
    return f'font-family: "{MONOSPACE_FONT_FAMILY}";'
