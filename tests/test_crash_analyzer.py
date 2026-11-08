"""Tests for crash analysis and addr2line integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from hil_cli.crash_analyzer import (
    CrashReport,
    SourceLocation,
    _run_addr2line,
    analyze_crash,
)
from hil_cli.serial_monitor import CrashEvent, CrashKind


def test_crash_report_readable_backtrace(esp32_crash_event: CrashEvent):
    """Test CrashReport.readable_backtrace() formatting."""
    report = CrashReport(crash=esp32_crash_event)
    report.locations = [
        SourceLocation(
            address="400d1b37",
            function="badFunction",
            file="/src/main.cpp",
            line=42,
        )
    ]
    text = report.readable_backtrace()
    assert "guru_meditation" in text
    assert "badFunction" in text
    assert "main.cpp:42" in text


def test_crash_report_context_for_ai(esp32_crash_event: CrashEvent, tmp_path: Path):
    """Test AI-formatted crash context."""
    src_file = tmp_path / "main.cpp"
    src_file.write_text(
        """
void setup() {}

void badFunction() {
    int* ptr = nullptr;
    *ptr = 42;  // crash here
}

void loop() {
    badFunction();
}
"""
    )

    report = CrashReport(crash=esp32_crash_event)
    report.locations = [
        SourceLocation(
            address="400d1b37",
            function="badFunction",
            file=str(src_file),
            line=6,
        )
    ]

    context = report.context_for_ai()
    assert "## Crash kind" in context
    assert "guru_meditation" in context
    assert "## Source context" in context
    assert "badFunction" in context
    assert "*ptr = 42;" in context


@patch("hil_cli.crash_analyzer.subprocess.run")
@patch("hil_cli.crash_analyzer.resolve_binary")
def test_run_addr2line_success(mock_resolve, mock_run, sample_elf_path: Path):
    """Test successful addr2line call."""
    mock_resolve.return_value = Path("/usr/bin/xtensa-esp32-elf-addr2line")
    mock_run.return_value = MagicMock(stdout="0x400d1b37: badFunction at /src/main.cpp:42\n")

    locations = _run_addr2line(sample_elf_path, ["400d1b37"], "xtensa-esp32-elf")
    assert len(locations) == 1
    assert locations[0].function == "badFunction"
    assert locations[0].file == "/src/main.cpp"
    assert locations[0].line == 42


@patch("hil_cli.crash_analyzer.subprocess.run")
@patch("hil_cli.crash_analyzer.resolve_binary")
def test_run_addr2line_timeout(mock_resolve, mock_run, sample_elf_path: Path):
    """Test addr2line timeout handling."""
    mock_resolve.return_value = Path("/usr/bin/addr2line")
    mock_run.side_effect = TimeoutError()

    locations = _run_addr2line(sample_elf_path, ["400d1b37"], "xtensa-esp32-elf")
    assert locations == []


def test_analyze_crash_no_addresses():
    """Test crash analysis with no addresses extracted."""
    crash = CrashEvent(
        kind=CrashKind.UNKNOWN,
        raw_dump="Some random crash text",
        addresses=[],
        board_target="esp32",
    )
    report = analyze_crash(crash, None, "xtensa-esp32-elf")
    assert report.analysis_error is not None
    assert "No addresses" in report.analysis_error


def test_analyze_crash_no_elf(esp32_crash_event: CrashEvent):
    """Test crash analysis when ELF is missing."""
    report = analyze_crash(esp32_crash_event, None, "xtensa-esp32-elf")
    assert report.analysis_error is not None
    assert "ELF not found" in report.analysis_error
    assert len(report.locations) == 0


@patch("hil_cli.crash_analyzer._run_addr2line")
def test_analyze_crash_with_elf(
    mock_addr2line, esp32_crash_event: CrashEvent, sample_elf_path: Path
):
    """Test successful crash analysis with ELF."""
    mock_addr2line.return_value = [
        SourceLocation(
            address="400d1b37",
            function="badFunction",
            file="/src/main.cpp",
            line=42,
        )
    ]

    report = analyze_crash(esp32_crash_event, sample_elf_path, "xtensa-esp32-elf")
    assert report.elf_path == str(sample_elf_path)
    assert len(report.locations) == 1
    assert report.locations[0].function == "badFunction"
    assert report.analysis_error is None
