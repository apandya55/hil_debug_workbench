"""Tests for toolchain resolution and binary helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from hil_cli.toolchain import (
    _find_in_pio,
    _find_on_path,
    _guess_package,
    addr2line_version,
    resolve_binary,
)


def test_guess_package_variants():
    assert _guess_package("xtensa-esp32-elf") == "platformio/toolchain-xtensa-esp32"
    assert _guess_package("xtensa-esp32s2-elf") == "platformio/toolchain-xtensa-esp32s2"
    assert _guess_package("xtensa-esp32s3-elf") == "platformio/toolchain-xtensa-esp32s3"
    assert _guess_package("arm-none-eabi") == "platformio/toolchain-gccarmnoneeabi"


def test_find_on_path_matching():
    with patch("shutil.which", return_value="/usr/bin/arm-none-eabi-addr2line"):
        found = _find_on_path("arm-none-eabi", "addr2line")
        assert found == Path("/usr/bin/arm-none-eabi-addr2line")


def test_resolve_binary_from_path():
    with patch("hil_cli.toolchain._find_in_pio", return_value=None), patch(
        "hil_cli.toolchain._find_on_path", return_value=Path("/opt/bin/addr2line")
    ):
        p = resolve_binary("xtensa-esp32-elf", "addr2line")
        assert p == Path("/opt/bin/addr2line")


def test_addr2line_version_output():
    with patch(
        "hil_cli.toolchain.resolve_binary", return_value=Path("/usr/bin/addr2line")
    ), patch(
        "subprocess.run"
    ) as mock_run:
        mock_run.return_value.stdout = "GNU addr2line (GNU Binutils) 2.40\nCopyright (C) 2023"
        ver = addr2line_version("xtensa-esp32-elf")
        assert "2.40" in ver
