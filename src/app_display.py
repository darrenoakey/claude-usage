"""Main PySide6 application window for Claude Gauge."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
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

from data_access import UsageData, format_time_remaining, poll_usage
from gauge_widget import GaugeWidget

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ASSETS_DIR = Path(__file__).parent.parent / "assets"
STATES_DIR = ASSETS_DIR / "states"
ICON_PATH = next((ASSETS_DIR / f"icon{ext}" for ext in (".png", ".jpg") if (ASSETS_DIR / f"icon{ext}").exists()), ASSETS_DIR / "icon.jpg")

POLL_INTERVAL_MS = 300_000  # 5 minutes
PREFS_PATH = Path.home() / ".claude" / "claude-gauge-prefs.json"

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

CARD_STYLE = "QFrame { background-color: #12121e; border: 1px solid #2a2a40; border-radius: 8px; }"


def _state_image_path(index: int) -> Path | None:
    """Return the best available image path for a state index (PNG preferred over JPG)."""
    for ext in ("png", "jpg"):
        p = STATES_DIR / f"state_{index:02d}.{ext}"
        if p.exists():
            return p
    return None


class ScorePanel(QFrame):
    """Panel showing state image and score text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(CARD_STYLE)

        # Outer VBox with stretch above/below to vertically center content
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 4, 14, 4)

        inner = QHBoxLayout()
        inner.setSpacing(20)
        inner.setContentsMargins(0, 0, 0, 0)

        # State image — transparent background, fills most of panel height
        self._image_label = QLabel()
        self._image_label.setFixedSize(280, 140)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background: transparent; border: none;")
        inner.addWidget(self._image_label)

        # Text column — vertically centered
        text_col = QVBoxLayout()
        text_col.setSpacing(5)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._score_label = QLabel("Score: --")
        self._score_label.setFont(QFont("Courier", 22, QFont.Weight.Bold))
        text_col.addWidget(self._score_label)

        self._state_label = QLabel("---")
        self._state_label.setFont(QFont("Courier", 15, QFont.Weight.Bold))
        text_col.addWidget(self._state_label)

        self._pace_label = QLabel("")
        self._pace_label.setFont(QFont("Courier", 11))
        self._pace_label.setStyleSheet("color: #9090b0; border: none;")
        text_col.addWidget(self._pace_label)

        inner.addLayout(text_col)
        inner.addStretch()

        outer.addStretch(1)
        outer.addLayout(inner)
        outer.addStretch(1)

    def update_data(self, data: UsageData) -> None:
        path = _state_image_path(data.state_index)
        if path:
            pix = QPixmap(str(path))
            self._image_label.setPixmap(
                pix.scaled(
                    self._image_label.width(), self._image_label.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self._image_label.setText(f"[state {data.state_index}]")
            self._image_label.setStyleSheet("color: #606070; background: transparent; border: none;")

        # Positive = good (under budget): elapsed - used
        display_score = -data.score
        label_text, label_color = STATE_LABELS.get(data.state_index, ("---", QColor(160, 160, 160)))
        hex_col = label_color.name()

        if display_score >= 0:
            score_text = f"Ahead: {round(display_score)}%"
        else:
            score_text = f"Behind: {round(-display_score)}%"
        self._score_label.setText(score_text)
        self._score_label.setStyleSheet(f"color: {hex_col}; border: none;")

        self._state_label.setText(label_text)
        self._state_label.setStyleSheet(f"color: {hex_col}; border: none;")

        # Pace uses internal score (negative = good = under budget)
        if data.score < -10:
            pace = "🟢 Well under budget"
        elif data.score < 0:
            pace = "🟡 Slightly under budget"
        elif data.score < 10:
            pace = "🟡 Watch your pace"
        else:
            pace = "🔴 Over budget — slow down!"
        self._pace_label.setText(f"Pace:  {pace}")

    def show_error(self, message: str) -> None:
        self._image_label.setText("⚠")
        self._image_label.setStyleSheet("color: #c04040; font-size: 48px; background: transparent; border: none;")
        self._score_label.setText("Auth Error")
        self._score_label.setStyleSheet("color: #c04040; border: none;")
        self._state_label.setText("Check credentials")
        self._state_label.setStyleSheet("color: #808090; border: none;")
        self._pace_label.setText(message[:80])


def _gauge_card(gauge: GaugeWidget) -> QFrame:
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    frame.setStyleSheet(CARD_STYLE)
    fl = QVBoxLayout(frame)
    fl.setContentsMargins(6, 6, 6, 6)
    fl.addWidget(gauge)
    return frame


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Claude Gauge")
        self.setFixedSize(820, 430)

        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self._build_ui()
        self._setup_status_bar()
        self._setup_timer()
        self._restore_position()

        QTimer.singleShot(100, self._poll)

    def _restore_position(self) -> None:
        """Restore window position from persisted prefs."""
        try:
            if PREFS_PATH.exists():
                prefs = json.loads(PREFS_PATH.read_text())
                x, y = prefs.get("window_x"), prefs.get("window_y")
                if x is not None and y is not None:
                    self.move(int(x), int(y))
        except Exception:
            pass

    def _save_position(self) -> None:
        """Persist window position."""
        try:
            pos = self.pos()
            prefs = {}
            if PREFS_PATH.exists():
                try:
                    prefs = json.loads(PREFS_PATH.read_text())
                except Exception:
                    pass
            prefs["window_x"] = pos.x()
            prefs["window_y"] = pos.y()
            PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
            PREFS_PATH.write_text(json.dumps(prefs, indent=2))
        except Exception:
            pass

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self._save_position()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setStyleSheet("background-color: #0c0c18;")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 6)
        root.setSpacing(8)

        # ── Gauges row ────────────────────────────────────────────
        gauges_row = QHBoxLayout()
        gauges_row.setSpacing(10)

        self._gauge_5h = GaugeWidget("5-HOUR WINDOW")
        self._gauge_7d = GaugeWidget("7-DAY PERIOD")

        gauges_row.addWidget(_gauge_card(self._gauge_5h))
        gauges_row.addWidget(_gauge_card(self._gauge_7d))

        root.addLayout(gauges_row, stretch=3)

        # ── Score panel ───────────────────────────────────────────
        self._score_panel = ScorePanel()
        root.addWidget(self._score_panel, stretch=2)

    def _setup_status_bar(self) -> None:
        bar = QStatusBar()
        bar.setStyleSheet(
            "QStatusBar { background: #0c0c18; color: #505068; font-family: Courier; font-size: 10px; border-top: 1px solid #1e1e2e; }"
        )
        self._updated_label = QLabel("Not yet updated")
        self._updated_label.setStyleSheet("color: #505068;")
        bar.addPermanentWidget(self._updated_label)
        self.setStatusBar(bar)

    def _setup_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_INTERVAL_MS)

    def _poll(self) -> None:
        log.info("Polling usage data...")
        data = poll_usage()
        self._apply_data(data)

    def _apply_data(self, data: UsageData) -> None:
        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self._updated_label.setText(f"Updated {now_str}")

        if data.error:
            log.warning("Poll error: %s", data.error)
            self._gauge_5h.set_no_data()
            self._gauge_7d.set_no_data()
            self._score_panel.show_error(data.error)
            return

        resets_5h = format_time_remaining(data.window_5h.resets_at)
        self._gauge_5h.set_usage(data.window_5h.used_pct, data.window_5h.elapsed_pct, resets_5h)

        if data.period_7d.used_pct == 0 and data.period_7d.elapsed_pct == 0:
            self._gauge_7d.set_no_data()
        else:
            resets_7d = format_time_remaining(data.period_7d.resets_at)
            self._gauge_7d.set_usage(data.period_7d.used_pct, data.period_7d.elapsed_pct, resets_7d)

        self._score_panel.update_data(data)

        if data.raw_headers:
            log.info("Rate limit headers: %s", list(data.raw_headers.keys()))


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
        if sys.platform == "darwin":
            try:
                import AppKit  # type: ignore[import]
                dock_img = AppKit.NSImage.alloc().initWithContentsOfFile_(str(ICON_PATH))
                AppKit.NSApplication.sharedApplication().setApplicationIconImage_(dock_img)
            except Exception:
                pass

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(12, 12, 24))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(210, 210, 230))
    palette.setColor(QPalette.ColorRole.Base, QColor(18, 18, 30))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(28, 28, 42))
    palette.setColor(QPalette.ColorRole.Text, QColor(210, 210, 230))
    palette.setColor(QPalette.ColorRole.Button, QColor(38, 38, 56))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(210, 210, 230))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(80, 80, 160))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
