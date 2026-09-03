from __future__ import annotations

import os
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QSlider

from live_translator.models import SubtitleState
from live_translator.qt_control import ControlWindow
from live_translator.windows_audio import LoopbackDevice


def get_application() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return cast(QApplication, existing)
    return QApplication([])


def test_control_window_tracks_session_state() -> None:
    app = get_application()
    window = ControlWindow(
        [
            LoopbackDevice(
                index=4,
                name="Speakers",
                sample_rate=48_000,
                channels=2,
                is_default=True,
            )
        ]
    )

    assert window.start_enabled
    assert not window.stop_enabled

    window.set_state(SubtitleState(status="running", message=""))
    app.processEvents()
    assert not window.start_enabled
    assert window.stop_enabled
    assert window.displayed_status == "Running"

    window.set_state(SubtitleState(status="error", message="ASR is unavailable."))
    app.processEvents()
    assert window.start_enabled
    assert not window.stop_enabled
    assert "ASR is unavailable." in window.displayed_status
    window.close()


def test_control_window_emits_overlay_lock_changes() -> None:
    app = get_application()
    window = ControlWindow([], allow_start_without_device=True)
    lock_box = window.findChild(QCheckBox)
    spy = QSignalSpy(window.overlay_lock_changed)

    assert lock_box is not None
    lock_box.click()
    app.processEvents()

    assert spy.count() == 1
    assert spy.at(0) == [True]
    window.close()


def test_control_window_emits_overlay_opacity_changes() -> None:
    app = get_application()
    window = ControlWindow(
        [],
        allow_start_without_device=True,
        overlay_background_opacity=69,
    )
    opacity_slider = window.findChild(QSlider)
    spy = QSignalSpy(window.overlay_opacity_changed)

    assert opacity_slider is not None
    opacity_slider.setValue(42)
    app.processEvents()

    assert spy.count() == 1
    assert spy.at(0) == [42]
    window.close()


def test_control_status_is_always_plain_text() -> None:
    app = get_application()
    window = ControlWindow([], allow_start_without_device=True)
    window.set_state(SubtitleState(status="error", message="<b>not markup</b>"))
    app.processEvents()

    status_label = next(
        label for label in window.findChildren(QLabel) if "<b>not markup</b>" in label.text()
    )
    assert status_label.textFormat() == Qt.TextFormat.PlainText
    window.close()
