from PySide6.QtGui import QFont

from ui_fonts import MONOSPACE_FONT_FAMILY, mono_font, mono_stylesheet


def test_mono_font_uses_single_configured_family():
    font = mono_font(11, QFont.Weight.Bold)
    assert font.family() == MONOSPACE_FONT_FAMILY
    assert font.pointSize() == 11
    assert font.weight() == QFont.Weight.Bold


def test_mono_stylesheet_uses_same_family():
    assert mono_stylesheet() == f'font-family: "{MONOSPACE_FONT_FAMILY}";'
