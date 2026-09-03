from __future__ import annotations

from typing import cast

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .models import SubtitleState
from .windows_audio import LoopbackDevice


class _ControlBridge(QObject):
    state_changed = Signal(object)


class ControlWindow(QWidget):
    start_requested = Signal(object)
    stop_requested = Signal()
    overlay_lock_changed = Signal(bool)
    overlay_opacity_changed = Signal(int)

    def __init__(
        self,
        devices: list[LoopbackDevice],
        *,
        allow_start_without_device: bool = False,
        overlay_position_locked: bool = False,
        overlay_background_opacity: int = 69,
    ) -> None:
        super().__init__(None)
        self._bridge = _ControlBridge()
        self._device_box = QComboBox()
        self._start_button = QPushButton("Start")
        self._stop_button = QPushButton("Stop")
        self._status_label = QLabel("Idle")
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        self._overlay_lock = QCheckBox("Lock subtitle position")
        self._overlay_lock.setChecked(overlay_position_locked)
        self._overlay_opacity = QSlider(Qt.Orientation.Horizontal)
        self._overlay_opacity.setRange(0, 100)
        self._overlay_opacity.setValue(overlay_background_opacity)
        self._allow_start_without_device = allow_start_without_device

        self.setWindowTitle("Live Translator")
        self.setMinimumWidth(480)
        for device in devices:
            suffix = " (default)" if device.is_default else ""
            self._device_box.addItem(f"{device.name}{suffix}", device.index)

        button_row = QHBoxLayout()
        button_row.addWidget(self._start_button)
        button_row.addWidget(self._stop_button)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("Subtitle background"))
        opacity_row.addWidget(self._overlay_opacity)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("WASAPI loopback device"))
        layout.addWidget(self._device_box)
        layout.addLayout(button_row)
        layout.addWidget(self._overlay_lock)
        layout.addLayout(opacity_row)
        layout.addWidget(self._status_label)

        self._start_button.clicked.connect(self._emit_start)
        self._stop_button.clicked.connect(self.stop_requested.emit)
        self._overlay_lock.toggled.connect(self.overlay_lock_changed.emit)
        self._overlay_opacity.valueChanged.connect(self.overlay_opacity_changed.emit)
        self._bridge.state_changed.connect(self._apply_state)
        self._apply_state(SubtitleState())

    def set_state(self, state: SubtitleState) -> None:
        self._bridge.state_changed.emit(state)

    def clear(self) -> None:
        self._bridge.state_changed.emit(SubtitleState())

    def select_device(self, device_index: int | None) -> None:
        if device_index is None:
            return
        index = self._device_box.findData(device_index)
        if index >= 0:
            self._device_box.setCurrentIndex(index)

    @Slot()
    def _emit_start(self) -> None:
        self.start_requested.emit(self._device_box.currentData())

    @Slot(object)
    def _apply_state(self, raw_state: object) -> None:
        state = cast(SubtitleState, raw_state)
        running = state.status in {"connecting", "running", "stopping"}
        has_device = self._device_box.count() > 0 or self._allow_start_without_device
        self._start_button.setEnabled(not running and has_device)
        self._stop_button.setEnabled(running)
        label = state.status.capitalize()
        if state.message:
            label = f"{label}: {state.message}"
        self._status_label.setText(label)

    @property
    def displayed_status(self) -> str:
        return self._status_label.text()

    @property
    def start_enabled(self) -> bool:
        return self._start_button.isEnabled()

    @property
    def stop_enabled(self) -> bool:
        return self._stop_button.isEnabled()
