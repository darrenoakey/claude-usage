"""Native PySide6 desktop app: subscription-usage gauges for Codex, Claude & GLM-5.

A standalone dock app (with the speedometer icon) that renders agentd's unified
subscription-usage snapshot using native QPainter gauges. agentd is the single
poller; this app just GETs its feed every minute and draws it. No web view.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, str(Path(__file__).parent))

from data_access import Provider, UsageData, format_time_remaining, poll_usage
from gauge_widget import GaugeWidget

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ASSETS_DIR = Path(__file__).parent.parent / "assets"
STATES_DIR = ASSETS_DIR / "states"
ICON_PATH = next((ASSETS_DIR / f"icon{ext}" for ext in (".png", ".jpg") if (ASSETS_DIR / f"icon{ext}").exists()), ASSETS_DIR / "icon.jpg")

POLL_INTERVAL_MS = 60_000  # agentd does the real polling; we just refresh the view

STATE_LABELS = {
    1: ("CRUSHING IT", QColor(30, 220, 80)),
    2: ("VERY COMFY", QColor(50, 210, 100)),
    3: ("LOOKING GOOD", QColor(80, 220, 80)),
    4: ("AHEAD OF PACE", QColor(130, 230, 60)),
    5: ("ON TRACK", QColor(180, 230, 40)),
    6: ("ZEN BALANCE", QColor(220, 210, 40)),
    7: ("WATCH IT...", QColor(240, 170, 20)),
    8: ("PANIC MODE", QColor(240, 110, 20)),
    9: ("RED ALERT!", QColor(230, 45, 20)),
    10: ("MELTDOWN 💥", QColor(210, 0, 0)),
}

CARD_STYLE = "QFrame { background-color: #12121e; border: 1px solid #2a2a40; border-radius: 10px; }"


def _state_image_path(index: int) -> Path | None:
    for ext in ("png", "jpg"):
        p = STATES_DIR / f"state_{index:02d}.{ext}"
        if p.exists():
            return p
    return None


class ProviderCard(QFrame):
    """One provider column: a big weekly dial + a small 5-hour dial."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(CARD_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self._name = QLabel(title)
        self._name.setFont(QFont("Courier", 13, QFont.Weight.Bold))
        self._name.setStyleSheet("color: #aab0e0; border: none;")
        header.addWidget(self._name)
        header.addStretch()
        self._plan = QLabel("")
        self._plan.setFont(QFont("Courier", 9))
        self._plan.setStyleSheet("color: #7e84a8; border: none;")
        header.addWidget(self._plan)
        layout.addLayout(header)

        self._weekly = GaugeWidget("7-DAY")
        self._session = GaugeWidget("5-HOUR")
        self._session.setMinimumSize(180, 150)
        layout.addWidget(self._weekly, stretch=3)
        layout.addWidget(self._session, stretch=2)

        self._reason = QLabel("")
        self._reason.setWordWrap(True)
        self._reason.setFont(QFont("Courier", 9))
        self._reason.setStyleSheet("color: #c98a8a; border: none;")
        layout.addWidget(self._reason)

    def update_provider(self, p: Provider) -> None:
        self._plan.setText(p.plan.upper())
        if not p.available:
            self._weekly.set_no_data()
            self._session.set_no_data()
            self._reason.setText(p.reason or "unavailable")
            return
        self._reason.setText("")
        if p.weekly:
            self._weekly.set_usage(p.weekly.used_pct, p.weekly.elapsed_pct, format_time_remaining(p.weekly.resets_at))
        else:
            self._weekly.set_no_data()
        if p.session:
            self._session.set_usage(p.session.used_pct, p.session.elapsed_pct, format_time_remaining(p.session.resets_at))
        else:
            self._session.set_no_data()

    def set_offline(self, message: str) -> None:
        self._weekly.set_no_data()
        self._session.set_no_data()
        self._reason.setText(message)


class CombinedPanel(QFrame):
    """Bottom mood panel: the worst-skewed combined state with its robot."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(CARD_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 6, 16, 6)
        inner = QHBoxLayout()
        inner.setSpacing(20)

        self._image = QLabel()
        self._image.setFixedSize(240, 120)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setStyleSheet("background: transparent; border: none;")
        inner.addWidget(self._image)

        text = QVBoxLayout()
        text.setSpacing(4)
        text.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._score = QLabel("Score: --")
        self._score.setFont(QFont("Courier", 24, QFont.Weight.Bold))
        text.addWidget(self._score)
        self._state = QLabel("---")
        self._state.setFont(QFont("Courier", 15, QFont.Weight.Bold))
        text.addWidget(self._state)
        self._pace = QLabel("")
        self._pace.setFont(QFont("Courier", 11))
        self._pace.setStyleSheet("color: #9090b0; border: none;")
        text.addWidget(self._pace)
        inner.addLayout(text)
        inner.addStretch()

        outer.addStretch(1)
        outer.addLayout(inner)
        outer.addStretch(1)

    def update_combined(self, data: UsageData) -> None:
        path = _state_image_path(data.combined_state)
        if path:
            pix = QPixmap(str(path))
            self._image.setPixmap(pix.scaled(
                self._image.width(), self._image.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self._image.setText(f"[state {data.combined_state}]")

        label, color = STATE_LABELS.get(data.combined_state, ("---", QColor(160, 160, 160)))
        hex_col = color.name()
        display = -data.combined_score  # negative score = under budget = good
        if display >= 0:
            self._score.setText(f"Ahead: {round(display)}%")
        else:
            self._score.setText(f"Behind: {round(-display)}%")
        self._score.setStyleSheet(f"color: {hex_col}; border: none;")
        self._state.setText(label)
        self._state.setStyleSheet(f"color: {hex_col}; border: none;")
        self._pace.setText(f"Pace:  {data.combined_pace}")

    def show_error(self, message: str) -> None:
        self._image.setText("⚠")
        self._image.setStyleSheet("color: #c04040; font-size: 48px; background: transparent; border: none;")
        self._score.setText("Offline")
        self._score.setStyleSheet("color: #c04040; border: none;")
        self._state.setText("agentd not reachable")
        self._state.setStyleSheet("color: #808090; border: none;")
        self._pace.setText(message[:90])


class MainWindow(QMainWindow):
    _poll_finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Agentd Gauges")
        self.setMinimumSize(900, 560)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self._polling = False
        self._cards: dict[str, ProviderCard] = {}
        self._build_ui()
        self._setup_status_bar()
        self._poll_finished.connect(self._apply_data)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_INTERVAL_MS)
        QTimer.singleShot(100, self._poll)

    def _build_ui(self) -> None:
        central = QWidget()
        central.setStyleSheet("background-color: #0c0c18;")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 6)
        root.setSpacing(10)

        self._cards_row = QHBoxLayout()
        self._cards_row.setSpacing(10)
        # Fixed provider order to match the web dashboard.
        for name, title in (("codex", "Codex"), ("claude", "Claude"), ("zai", "GLM-5")):
            card = ProviderCard(title)
            self._cards[name] = card
            self._cards_row.addWidget(card)
        root.addLayout(self._cards_row, stretch=3)

        self._combined = CombinedPanel()
        root.addWidget(self._combined, stretch=2)

    def _setup_status_bar(self) -> None:
        bar = QStatusBar()
        bar.setStyleSheet("QStatusBar { background: #0c0c18; color: #505068; font-family: Courier; font-size: 10px; border-top: 1px solid #1e1e2e; }")
        self._updated = QLabel("Connecting to agentd…")
        self._updated.setStyleSheet("color: #505068;")
        bar.addPermanentWidget(self._updated)
        self.setStatusBar(bar)

    def _poll(self) -> None:
        if self._polling:
            return
        self._polling = True

        def _bg() -> None:
            try:
                data = poll_usage()
            except Exception as e:  # noqa: BLE001
                data = UsageData(error=f"error: {e}")
            self._poll_finished.emit(data)

        Thread(target=_bg, daemon=True).start()

    def _apply_data(self, data: UsageData) -> None:
        self._polling = False
        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        if data.error:
            self._updated.setText(f"Offline {now_str} — {data.error}")
            for card in self._cards.values():
                card.set_offline(data.error)
            self._combined.show_error(data.error)
            return

        for p in data.providers:
            card = self._cards.get(p.name)
            if card:
                card.update_provider(p)
        self._combined.update_combined(data)
        self._updated.setText(f"Updated {now_str} · source: agentd")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("Agentd Gauges")

    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
        if sys.platform == "darwin":
            try:
                import AppKit  # type: ignore[import]
                dock_img = AppKit.NSImage.alloc().initWithContentsOfFile_(str(ICON_PATH))
                AppKit.NSApplication.sharedApplication().setApplicationIconImage_(dock_img)
            except Exception:  # noqa: BLE001
                pass

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(12, 12, 24))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(210, 210, 230))
    palette.setColor(QPalette.ColorRole.Base, QColor(18, 18, 30))
    palette.setColor(QPalette.ColorRole.Text, QColor(210, 210, 230))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
