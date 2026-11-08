"""Tests for PlatformIO build and flash runner."""

from __future__ import annotations

import pytest

from hil_cli.flasher import FlashResult, FlashStatus, _find_pio


def test_flash_result_ok():
    res = FlashResult(status=FlashStatus.SUCCESS, duration_s=1.2)
    assert res.ok is True


def test_flash_result_error_summary_pio_missing():
    res = FlashResult(status=FlashStatus.PIO_NOT_FOUND)
    assert res.ok is False
    assert "PlatformIO (`pio`) not found" in res.error_summary()


def test_flash_result_error_summary_upload_failed():
    stderr_sample = "Error: Failed to connect to ESP32: Timed out waiting for packet header"
    res = FlashResult(status=FlashStatus.UPLOAD_FAILED, stderr=stderr_sample)
    assert res.ok is False
    assert "Timed out waiting for packet header" in res.error_summary()


def test_find_pio_lookup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/pio")
    p = _find_pio()
    assert p is not None
    assert str(p) == "/usr/local/bin/pio"
