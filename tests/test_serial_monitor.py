"""Tests for serial monitor and crash detection."""

from __future__ import annotations

import asyncio

import pytest

from hil_cli.serial_monitor import (
    _ESP32_ADDR_RE,
    _ESP32_PANIC_RE,
    _RP2040_ADDR_RE,
    _RP2040_PANIC_RE,
    CrashKind,
    SerialMonitor,
)


def test_esp32_panic_regex_matches():
    cases = [
        "Guru Meditation Error: Core 0 panic'ed",
        "LoadProhibited exception was unhandled",
        "assert failed: ptr != NULL, file main.cpp, line 42",
        "Stack smashing protect failure",
    ]
    for text in cases:
        assert _ESP32_PANIC_RE.search(text), f"Should match: {text}"


def test_esp32_addr_extraction(esp32_crash_dump: str):
    matches = _ESP32_ADDR_RE.findall(esp32_crash_dump)
    assert len(matches) == 3
    assert "400d1b37" in matches
    assert "400d1c6a" in matches
    assert "400d1015" in matches


def test_rp2040_panic_regex_matches():
    cases = [
        "*** PANIC ***",
        "HardFault at pc=0x10001234",
        "assertion 'ptr != NULL' failed",
        "Unhandled interrupt",
    ]
    for text in cases:
        assert _RP2040_PANIC_RE.search(text), f"Should match: {text}"


def test_rp2040_addr_extraction(rp2040_crash_dump: str):
    match = _RP2040_ADDR_RE.search(rp2040_crash_dump)
    assert match is not None
    assert match.group(1) == "10001234"


def test_crash_event_address_deduplication():
    q = asyncio.Queue()
    monitor = SerialMonitor("/dev/null", 115200, "esp32", q)
    lines = [
        "Guru Meditation Error: Core 0 panic'ed",
        "Backtrace: 0x40081234:0x3ffb 0x40081234:0x3ffc 0x40082000:0x3ffd",
    ]
    event = monitor._build_crash(lines)
    assert event.kind == CrashKind.GURU_MEDITATION
    assert event.addresses == ["40081234", "40082000"]


@pytest.mark.parametrize(
    "line,expected_kind",
    [
        ("Guru Meditation Error: Core 0 panic'ed", CrashKind.GURU_MEDITATION),
        ("Stack smashing protect failure!", CrashKind.STACK_OVERFLOW),
        ("rst:0x8 (TG1WDT_SYS_RESET),boot:0x13", CrashKind.WATCHDOG),
        ("assert failed: heap != NULL", CrashKind.ASSERTION),
        ("abort() was called at PC 0x4008abcd", CrashKind.ABORT),
    ],
)
def test_crash_kind_detection(line: str, expected_kind: CrashKind):
    q = asyncio.Queue()
    monitor = SerialMonitor("/dev/null", 115200, "esp32", q)
    event = monitor._build_crash([line])
    assert event.kind == expected_kind
