from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from live_translator import security


def test_acl_check_is_skipped_outside_windows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(security.sys, "platform", "linux")

    assert security.private_file_acl_warning(tmp_path / ".env") is None


def test_acl_check_reports_broad_permissions_without_exposing_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "private-name.env"
    monkeypatch.setattr(security.sys, "platform", "win32")
    monkeypatch.setattr(security.os, "environ", {"SystemRoot": r"C:\Windows"})

    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=["powershell.exe"], returncode=3)

    monkeypatch.setattr(security.subprocess, "run", fake_run)

    warning = security.private_file_acl_warning(path)

    assert warning is not None
    assert str(path) not in warning
