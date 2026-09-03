from __future__ import annotations

import os
from pathlib import Path
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from live_translator.models import SubtitleSegment, SubtitleState
from live_translator.qt_overlay import SubtitleOverlay


def get_application() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return cast(QApplication, existing)
    return QApplication([])


def make_settings(path: Path) -> QSettings:
    return QSettings(str(path), QSettings.Format.IniFormat)


def make_segment(
    seq: int,
    source_text: str,
    translated_text: str = "",
) -> SubtitleSegment:
    return SubtitleSegment(
        session_id="session",
        seq=seq,
        source_text=source_text,
        translated_text=translated_text,
        translation_status="translated" if translated_text else "pending",
        audio_start_ms=(seq - 1) * 100,
        audio_end_ms=seq * 100,
    )


def test_overlay_renders_two_segment_rows_without_changing_width(tmp_path: Path) -> None:
    app = get_application()
    overlay = SubtitleOverlay(
        settings=make_settings(tmp_path / "overlay.ini"),
        auto_hide_ms=0,
    )
    initial_width = overlay.width()

    overlay.set_state(
        SubtitleState(
            segments=(
                make_segment(1, "一つ", "第一条"),
                make_segment(2, "二つ", "第二条"),
            ),
            status="running",
        )
    )
    app.processEvents()

    assert overlay.displayed_segments == (("一つ", "第一条"), ("二つ", "第二条"))
    assert overlay.displayed_source == "二つ"
    assert overlay.displayed_translation == "第二条"
    assert overlay.displayed_status == ""
    assert overlay.width() == initial_width

    overlay.set_state(
        SubtitleState(
            segments=(
                make_segment(
                    3,
                    "これは固定幅を確認するための長い字幕です。",
                    "这是一条用来确认悬浮窗宽度固定的长字幕。",
                ),
            ),
            status="running",
        )
    )
    app.processEvents()

    assert overlay.width() == initial_width
    overlay.clear()
    app.processEvents()
    assert not overlay.isVisible()
    overlay.close()


def test_overlay_auto_hides_after_inactivity(tmp_path: Path) -> None:
    get_application()
    overlay = SubtitleOverlay(
        settings=make_settings(tmp_path / "auto-hide.ini"),
        auto_hide_ms=10,
    )
    overlay.set_state(
        SubtitleState(
            segments=(make_segment(1, "こんにちは", "你好"),),
            status="running",
        )
    )
    QTest.qWait(30)

    assert not overlay.isVisible()
    overlay.close()


def test_overlay_position_is_restored_from_settings(tmp_path: Path) -> None:
    app = get_application()
    settings_path = tmp_path / "position.ini"
    overlay = SubtitleOverlay(settings=make_settings(settings_path), auto_hide_ms=0)
    overlay.move(QPoint(40, 40))
    overlay.close()
    app.processEvents()

    restored = SubtitleOverlay(settings=make_settings(settings_path), auto_hide_ms=0)

    assert restored.pos() == QPoint(40, 40)
    restored.close()


def test_overlay_position_lock_is_persisted(tmp_path: Path) -> None:
    get_application()
    settings_path = tmp_path / "position-lock.ini"
    overlay = SubtitleOverlay(settings=make_settings(settings_path), auto_hide_ms=0)

    overlay.set_position_locked(True)
    overlay.close()
    restored = SubtitleOverlay(settings=make_settings(settings_path), auto_hide_ms=0)

    assert restored.position_locked
    restored.close()


def test_overlay_background_opacity_is_persisted(tmp_path: Path) -> None:
    get_application()
    settings_path = tmp_path / "background-opacity.ini"
    overlay = SubtitleOverlay(settings=make_settings(settings_path), auto_hide_ms=0)

    overlay.set_background_opacity(42)
    overlay.close()
    restored = SubtitleOverlay(settings=make_settings(settings_path), auto_hide_ms=0)

    assert restored.background_opacity == 42
    restored.close()


def test_overlay_treats_transcript_translation_and_status_as_plain_text(tmp_path: Path) -> None:
    app = get_application()
    overlay = SubtitleOverlay(
        settings=make_settings(tmp_path / "plain-text.ini"),
        auto_hide_ms=0,
    )
    overlay.set_state(
        SubtitleState(
            segments=(make_segment(1, "<b>source</b>", "<i>translation</i>"),),
            status="degraded",
            message="<a href='x'>status</a>",
        )
    )
    app.processEvents()

    populated_labels = [label for label in overlay.findChildren(QLabel) if label.text()]
    assert populated_labels
    assert all(label.textFormat() == Qt.TextFormat.PlainText for label in populated_labels)
    overlay.close()
