from __future__ import annotations

from typing import cast

from PySide6.QtCore import QObject, QPoint, QSettings, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QCloseEvent, QGuiApplication, QMouseEvent, QScreen
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from .models import SubtitleSegment, SubtitleState

_POSITION_KEY = "overlay/position"
_POSITION_LOCKED_KEY = "overlay/position_locked"
_BACKGROUND_OPACITY_KEY = "overlay/background_opacity"
_DEFAULT_BACKGROUND_OPACITY = 69
_DEFAULT_AUTO_HIDE_MS = 8_000
_BOTTOM_MARGIN_PX = 56


class _StateBridge(QObject):
    state_changed = Signal(object)
    clear_requested = Signal()


class _SubtitleRow(QWidget):
    def __init__(self) -> None:
        super().__init__(None)
        self.source_label = QLabel()
        self.translation_label = QLabel()
        self.source_label.setTextFormat(Qt.TextFormat.PlainText)
        self.translation_label.setTextFormat(Qt.TextFormat.PlainText)

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.source_label.setWordWrap(True)
        self.translation_label.setWordWrap(True)
        self.source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.translation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self.source_label)
        layout.addWidget(self.translation_label)

    def set_segment(self, segment: SubtitleSegment, *, subdued: bool) -> None:
        self.source_label.setText(segment.source_text)
        self.translation_label.setText(segment.translated_text)
        self.translation_label.setVisible(bool(segment.translated_text))
        if subdued:
            self.source_label.setStyleSheet("font-size: 15px; color: #aaaaaa;")
            self.translation_label.setStyleSheet(
                "font-size: 22px; font-weight: 500; color: #dddddd;"
            )
        else:
            self.source_label.setStyleSheet("font-size: 18px; color: #dddddd;")
            self.translation_label.setStyleSheet("font-size: 28px; font-weight: 600; color: white;")
        self.show()

    def clear(self) -> None:
        self.source_label.clear()
        self.translation_label.clear()
        self.hide()


class SubtitleOverlay(QWidget):
    def __init__(
        self,
        *,
        settings: QSettings | None = None,
        auto_hide_ms: int = _DEFAULT_AUTO_HIDE_MS,
    ) -> None:
        super().__init__(None)
        if auto_hide_ms < 0:
            raise ValueError("auto_hide_ms must not be negative")

        self._bridge = _StateBridge()
        self._settings = settings or QSettings("LiveTranslator", "LiveTranslator")
        self._auto_hide_ms = auto_hide_ms
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._rows = (_SubtitleRow(), _SubtitleRow())
        self._status_label = QLabel()
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        self._drag_offset: QPoint | None = None
        self._last_content_key: object = None
        self._position_locked = cast(
            bool,
            self._settings.value(
                _POSITION_LOCKED_KEY,
                False,
                type=bool,
            ),
        )
        self._background_opacity = cast(
            int,
            self._settings.value(
                _BACKGROUND_OPACITY_KEY,
                _DEFAULT_BACKGROUND_OPACITY,
                type=int,
            ),
        )
        if not 0 <= self._background_opacity <= 100:
            self._background_opacity = _DEFAULT_BACKGROUND_OPACITY

        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("subtitleOverlay")
        self.setFixedWidth(self._target_width())

        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._status_label.setStyleSheet("font-size: 13px; color: #ffcc66;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(10)
        for row in self._rows:
            layout.addWidget(row)
            row.hide()
        layout.addWidget(self._status_label)
        self._status_label.hide()
        self._apply_background_style()

        self._bridge.state_changed.connect(self._apply_state)
        self._bridge.clear_requested.connect(self._clear_labels)
        self._hide_timer.timeout.connect(self.hide)

        saved_position = self._settings.value(_POSITION_KEY)
        self._anchored_to_bottom = not isinstance(saved_position, QPoint)
        if isinstance(saved_position, QPoint):
            self.move(self._clamp_position(saved_position))
        else:
            self._move_to_bottom_center()

    def set_state(self, state: SubtitleState) -> None:
        self._bridge.state_changed.emit(state)

    def clear(self) -> None:
        self._bridge.clear_requested.emit()

    @Slot(bool)
    def set_position_locked(self, locked: bool) -> None:
        self._position_locked = locked
        self._drag_offset = None
        self._settings.setValue(_POSITION_LOCKED_KEY, locked)
        self._settings.sync()

    @Slot(int)
    def set_background_opacity(self, percent: int) -> None:
        if not 0 <= percent <= 100:
            raise ValueError("background opacity must be between 0 and 100")
        self._background_opacity = percent
        self._apply_background_style()
        self._settings.setValue(_BACKGROUND_OPACITY_KEY, percent)
        self._settings.sync()

    @Slot(object)
    def _apply_state(self, raw_state: object) -> None:
        state = cast(SubtitleState, raw_state)
        for row, segment in zip(self._rows, state.segments, strict=False):
            row.set_segment(segment, subdued=segment is not state.current_segment)
        for row in self._rows[len(state.segments) :]:
            row.clear()

        self._status_label.setText(state.message)
        self._status_label.setVisible(bool(state.segments and state.message))
        if not state.segments:
            self._hide_timer.stop()
            self.hide()
            self._last_content_key = None
            return

        self._resize_to_content()
        if self._anchored_to_bottom:
            self._move_to_bottom_center()
        else:
            self.move(self._clamp_position(self.pos()))

        content_key = (
            state.segments,
            state.status,
            state.message,
        )
        if content_key != self._last_content_key:
            self._last_content_key = content_key
            if self._auto_hide_ms:
                self._hide_timer.start(self._auto_hide_ms)
        self.show()
        self.raise_()

    @Slot()
    def _clear_labels(self) -> None:
        self._hide_timer.stop()
        for row in self._rows:
            row.clear()
        self._status_label.clear()
        self._status_label.hide()
        self._last_content_key = None
        self.hide()

    def _target_width(self) -> int:
        screen = QApplication.primaryScreen()
        available_width = screen.availableGeometry().width()
        desired_width = max(640, round(available_width * 0.65))
        return min(1_200, desired_width, max(320, available_width - 32))

    def _resize_to_content(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.activate()
        self.resize(self.width(), self.sizeHint().height())

    def _move_to_bottom_center(self) -> None:
        screen = QApplication.primaryScreen()
        geometry = screen.availableGeometry()
        x = geometry.left() + (geometry.width() - self.width()) // 2
        y = geometry.bottom() - self.height() - _BOTTOM_MARGIN_PX + 1
        self.move(x, y)

    def _clamp_position(self, position: QPoint) -> QPoint:
        screen: QScreen | None = QGuiApplication.screenAt(position)
        if screen is None:
            screen = QApplication.primaryScreen()
        geometry = screen.availableGeometry()
        max_x = max(geometry.left(), geometry.right() - self.width() + 1)
        max_y = max(geometry.top(), geometry.bottom() - self.height() + 1)
        return QPoint(
            min(max(position.x(), geometry.left()), max_x),
            min(max(position.y(), geometry.top()), max_y),
        )

    def _save_position(self) -> None:
        self._settings.setValue(_POSITION_KEY, self.pos())
        self._settings.sync()

    def _apply_background_style(self) -> None:
        alpha = round(255 * self._background_opacity / 100)
        self.setStyleSheet(
            "#subtitleOverlay {"
            " color: white;"
            f" background: rgba(0, 0, 0, {alpha});"
            " border-radius: 12px;"
            "}"
            "QLabel { background: transparent; }"
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._position_locked and event.button() == Qt.MouseButton.LeftButton:
            self._anchored_to_bottom = False
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            not self._position_locked
            and self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            target = event.globalPosition().toPoint() - self._drag_offset
            self.move(self._clamp_position(target))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self._save_position()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_position()
        super().closeEvent(event)

    @property
    def displayed_segments(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (row.source_label.text(), row.translation_label.text())
            for row in self._rows
            if row.isVisible()
        )

    @property
    def displayed_source(self) -> str:
        displayed = self.displayed_segments
        return "" if not displayed else displayed[-1][0]

    @property
    def displayed_translation(self) -> str:
        displayed = self.displayed_segments
        return "" if not displayed else displayed[-1][1]

    @property
    def displayed_status(self) -> str:
        return self._status_label.text()

    @property
    def position_locked(self) -> bool:
        return self._position_locked

    @property
    def background_opacity(self) -> int:
        return self._background_opacity
