"""Tests for USB board detection."""

from __future__ import annotations

from unittest.mock import patch

from serial.tools.list_ports_common import ListPortInfo

from hil_cli.detector import (
    DetectedBoard,
    _classify_port,
    detect_boards,
    pick_port_for_target,
)


def test_classify_esp32_by_vid_pid():
    """Test ESP32 detection by known VID/PID."""
    info = ListPortInfo("/dev/ttyUSB0")
    info.vid = 0x10C4
    info.pid = 0xEA60
    info.description = "CP2102 USB to UART"

    board = _classify_port(info)
    assert board is not None
    assert board.family == "esp32"
    assert board.port == "/dev/ttyUSB0"
    assert "CP2102" in board.board_label


def test_classify_rp2040_by_vid_pid():
    """Test RP2040 detection by known VID/PID."""
    info = ListPortInfo("/dev/ttyACM0")
    info.vid = 0x2E8A
    info.pid = 0x000A
    info.description = "Pico"

    board = _classify_port(info)
    assert board is not None
    assert board.family == "rp2040"
    assert "Pico" in board.board_label


def test_classify_by_description_fallback():
    """Test fallback to description-based detection."""
    info = ListPortInfo("/dev/ttyUSB1")
    info.vid = 0x9999  # Unknown VID
    info.pid = 0x9999
    info.description = "ESP32-WROOM-32 Development Board"

    board = _classify_port(info)
    assert board is not None
    assert board.family == "esp32"


def test_classify_unrecognized_device():
    """Test that unrecognized devices return None."""
    info = ListPortInfo("/dev/ttyUSB2")
    info.vid = 0x1234
    info.pid = 0x5678
    info.description = "Generic Serial Adapter"

    board = _classify_port(info)
    assert board is None


@patch("hil_cli.detector.serial.tools.list_ports.comports")
def test_detect_boards_filters_by_family(mock_comports):
    """Test that detect_boards filters by family."""
    esp32_info = ListPortInfo("/dev/ttyUSB0")
    esp32_info.vid = 0x10C4
    esp32_info.pid = 0xEA60
    esp32_info.description = "ESP32"

    rp2040_info = ListPortInfo("/dev/ttyACM0")
    rp2040_info.vid = 0x2E8A
    rp2040_info.pid = 0x000A
    rp2040_info.description = "RP2040"

    mock_comports.return_value = [esp32_info, rp2040_info]

    # No filter
    all_boards = detect_boards()
    assert len(all_boards) == 2

    # ESP32 only
    esp32_boards = detect_boards(family_filter="esp32")
    assert len(esp32_boards) == 1
    assert esp32_boards[0].family == "esp32"

    # RP2040 only
    rp2040_boards = detect_boards(family_filter="rp2040")
    assert len(rp2040_boards) == 1
    assert rp2040_boards[0].family == "rp2040"


@patch("hil_cli.detector.detect_boards")
def test_pick_port_for_target_prefers_explicit(mock_detect):
    """Test that explicit port is preferred over auto-detection."""
    mock_detect.return_value = []  # No boards detected
    port = pick_port_for_target("esp32", preferred_port="/dev/ttyUSB99")
    assert port == "/dev/ttyUSB99"
    mock_detect.assert_not_called()


@patch("hil_cli.detector.detect_boards")
def test_pick_port_for_target_auto_detect(mock_detect):
    """Test auto-detection when no explicit port given."""
    board = DetectedBoard(
        port="/dev/ttyUSB0",
        description="ESP32",
        board_label="ESP32",
        family="esp32",
        vid=0x10C4,
        pid=0xEA60,
    )
    mock_detect.return_value = [board]

    port = pick_port_for_target("esp32", preferred_port=None)
    assert port == "/dev/ttyUSB0"
    mock_detect.assert_called_once_with(family_filter="esp32")


@patch("hil_cli.detector.detect_boards")
def test_pick_port_returns_none_when_not_found(mock_detect):
    """Test that None is returned when no board is detected."""
    mock_detect.return_value = []
    port = pick_port_for_target("rp2040", preferred_port=None)
    assert port is None
