"""Pytest fixtures and configuration."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from serial.tools.list_ports_common import ListPortInfo

from hil_cli.config import BoardConfig, HilConfig
from hil_cli.serial_monitor import CrashEvent, CrashKind


@pytest.fixture
def temp_project_dir(tmp_path: Path) -> Path:
    """Create a temporary PlatformIO project directory."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "platformio.ini").write_text(
        "[env:test]\nplatform = espressif32\nboard = esp32dev\n"
    )
    (project / "src").mkdir()
    (project / "src" / "main.cpp").write_text(
        "#include <Arduino.h>\nvoid setup() {}\nvoid loop() {}\n"
    )
    return project


@pytest.fixture
def sample_board_config(temp_project_dir: Path) -> BoardConfig:
    """Sample BoardConfig for testing."""
    return BoardConfig(
        name="test-esp32",
        target="esp32",
        port="/dev/ttyUSB0",
        baud_rate=115200,
        pio_env="test",
        pio_project_dir=str(temp_project_dir),
        firmware_elf=None,
        stability_window=5,
        max_heal_cycles=3,
    )


@pytest.fixture
def sample_hil_config(sample_board_config: BoardConfig) -> HilConfig:
    """Sample HilConfig for testing."""
    return HilConfig(
        version=1,
        boards=[sample_board_config],
        dashboard_port=3000,
        ai_model="claude-opus-5-5",
        ai_max_tokens=4096,
    )


@pytest.fixture
def esp32_crash_dump() -> str:
    """Sample ESP32 Guru Meditation crash dump."""
    return """
Guru Meditation Error: Core  0 panic'ed (LoadProhibited). Exception was unhandled.

Core  0 register dump:
PC      : 0x400d1b3a  PS      : 0x00060330  A0      : 0x800d1c6d  A1      : 0x3ffb1f90
A2      : 0x00000000  A3      : 0x3ffb2020  A4      : 0x00000001  A5      : 0x00000000

Backtrace: 0x400d1b37:0x3ffb1f90 0x400d1c6a:0x3ffb1fb0 0x400d1015:0x3ffb1fd0
"""


@pytest.fixture
def rp2040_crash_dump() -> str:
    """Sample RP2040 panic dump."""
    return """
*** PANIC ***

HardFault at pc=0x10001234
  r0  0x20001000
  r1  0x00000042
  lr  0x10000abc
  pc  0x10001234
"""


@pytest.fixture
def esp32_crash_event(esp32_crash_dump: str) -> CrashEvent:
    """CrashEvent from ESP32 dump."""
    return CrashEvent(
        kind=CrashKind.GURU_MEDITATION,
        raw_dump=esp32_crash_dump,
        addresses=["400d1b37", "400d1c6a", "400d1015"],
        board_target="esp32",
    )


@pytest.fixture
def mock_serial_port() -> ListPortInfo:
    """Mock ListPortInfo for testing detector."""
    info = ListPortInfo("/dev/ttyUSB0")
    info.vid = 0x10C4  # CP2102
    info.pid = 0xEA60
    info.description = "CP2102 USB to UART Bridge Controller"
    return info


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_elf_path(tmp_path: Path) -> Path:
    """Create a dummy ELF file path."""
    elf = tmp_path / "firmware.elf"
    elf.write_bytes(b"\x7fELF")  # Minimal ELF header
    return elf
