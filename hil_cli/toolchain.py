"""PlatformIO and system toolchain binary resolution (addr2line, objdump, etc.)."""

from __future__ import annotations

import shutil
import subprocess  # nosec B404
from pathlib import Path

# Standard PlatformIO package directories
_PIO_PACKAGES = Path.home() / ".platformio" / "packages"

# Package directory lookup patterns
_ESP32_PACKAGES = [
    "toolchain-xtensa-esp32",
    "toolchain-xtensa-esp32s2",
    "toolchain-xtensa-esp32s3",
    "toolchain-xtensa32",
]
_RP2040_PACKAGES = [
    "toolchain-gccarmnoneeabi",
    "toolchain-rp2040-eabi",
    "toolchain-arm-eabi",
]


def _find_in_pio(prefix: str, binary: str) -> Path | None:
    """Look for a toolchain binary inside ~/.platformio/packages."""
    candidates = _ESP32_PACKAGES if "xtensa" in prefix else _RP2040_PACKAGES
    for pkg in candidates:
        pkg_dir = _PIO_PACKAGES / pkg / "bin"
        candidate = pkg_dir / f"{prefix}-{binary}"
        if candidate.exists():
            return candidate
        # Some ARM toolchains omit prefixes in their local bin directory
        candidate_bare = pkg_dir / binary
        if candidate_bare.exists():
            return candidate_bare
    return None


def _find_on_path(prefix: str, binary: str) -> Path | None:
    """Search system PATH with and without the toolchain prefix."""
    full = shutil.which(f"{prefix}-{binary}")
    if full:
        return Path(full)
    bare = shutil.which(binary)
    if bare:
        return Path(bare)
    return None


def resolve_binary(prefix: str, binary: str) -> Path:
    """Resolve a cross-compiler binary from PlatformIO packages or PATH."""
    p = _find_in_pio(prefix, binary)
    if p:
        return p
    p = _find_on_path(prefix, binary)
    if p:
        return p
    raise FileNotFoundError(
        f"Could not find '{prefix}-{binary}' in PlatformIO packages or PATH.\n"
        f"Install it with: pio pkg install --global --tool {_guess_package(prefix)}"
    )


def _guess_package(prefix: str) -> str:
    if "esp32s2" in prefix:
        return "platformio/toolchain-xtensa-esp32s2"
    if "esp32s3" in prefix:
        return "platformio/toolchain-xtensa-esp32s3"
    if "xtensa" in prefix:
        return "platformio/toolchain-xtensa-esp32"
    return "platformio/toolchain-gccarmnoneeabi"


def addr2line_version(prefix: str) -> str:
    """Return addr2line version string for diagnostics."""
    try:
        p = resolve_binary(prefix, "addr2line")
        result = subprocess.run(  # nosec B603
            [str(p), "--version"], check=False, capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip().splitlines()[0] if result.stdout else "unknown"
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return f"error: {exc}"
