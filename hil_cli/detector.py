"""USB board auto-detection for ESP32 and RP2040 families."""

from __future__ import annotations

import re
from dataclasses import dataclass

import serial.tools.list_ports
from serial.tools.list_ports_common import ListPortInfo

# Known USB vendor and product IDs.

ESP32_VIDS: dict[tuple[int, int], str] = {
    (0x10C4, 0xEA60): "ESP32 (Silicon Labs CP2102)",
    (0x10C4, 0xEA70): "ESP32 (Silicon Labs CP2105)",
    (0x1A86, 0x7523): "ESP32 (WCH CH340)",
    (0x1A86, 0x55D4): "ESP32 (WCH CH9102)",
    (0x0403, 0x6001): "ESP32 (FTDI FT232R)",
    (0x0403, 0x6015): "ESP32 (FTDI FT231X)",
    (0x303A, 0x1001): "ESP32-S2 (native USB)",
    (0x303A, 0x1002): "ESP32-S3 (native USB)",
    (0x303A, 0x0002): "ESP32-C3 (native USB)",
}

RP2040_VIDS: dict[tuple[int, int], str] = {
    (0x2E8A, 0x0003): "RP2040 (MicroPython REPL)",
    (0x2E8A, 0x0005): "RP2040 (Pico CDC)",
    (0x2E8A, 0x000A): "RP2040 (Pico SDK CDC)",
    (0x2E8A, 0x000F): "RP2040 (Pico W)",
    (0x2341, 0x005E): "Arduino Nano RP2040 Connect",
    (0x239A, 0x80F4): "Adafruit Feather RP2040",
}

# Fall-through string patterns for boards that don't report a PID we know
_ESP32_DESCRIPTION_RE = re.compile(r"esp32|cp210|ch340|cp2102", re.IGNORECASE)
_RP2040_DESCRIPTION_RE = re.compile(r"rp2040|pico|raspberry pi", re.IGNORECASE)


@dataclass
class DetectedBoard:
    port: str
    description: str
    board_label: str
    family: str  # "esp32" or "rp2040"
    vid: int | None
    pid: int | None

    def __str__(self) -> str:
        vid_pid = f"VID={self.vid:04X} PID={self.pid:04X}" if self.vid else "VID/PID unknown"
        return f"{self.board_label} on {self.port} ({vid_pid})"


def _classify_port(info: ListPortInfo) -> DetectedBoard | None:
    """Return a DetectedBoard for a known device, or None if unrecognised."""
    vid = getattr(info, "vid", None)
    pid = getattr(info, "pid", None)
    desc = info.description or ""

    if vid is not None and pid is not None:
        key = (vid, pid)
        if key in ESP32_VIDS:
            return DetectedBoard(
                port=info.device,
                description=desc,
                board_label=ESP32_VIDS[key],
                family="esp32",
                vid=vid,
                pid=pid,
            )
        if key in RP2040_VIDS:
            return DetectedBoard(
                port=info.device,
                description=desc,
                board_label=RP2040_VIDS[key],
                family="rp2040",
                vid=vid,
                pid=pid,
            )

    # Fall back to description matching when VID/PID tables don't match
    if _ESP32_DESCRIPTION_RE.search(desc):
        return DetectedBoard(
            port=info.device,
            description=desc,
            board_label=f"ESP32-family ({desc})",
            family="esp32",
            vid=vid,
            pid=pid,
        )
    if _RP2040_DESCRIPTION_RE.search(desc):
        return DetectedBoard(
            port=info.device,
            description=desc,
            board_label=f"RP2040-family ({desc})",
            family="rp2040",
            vid=vid,
            pid=pid,
        )
    return None


def detect_boards(family_filter: str | None = None) -> list[DetectedBoard]:
    """
    Scan all USB/serial ports and return detected HIL-capable boards.

    Args:
        family_filter: if given, only return boards whose family matches
                       ("esp32" or "rp2040").
    """
    results: list[DetectedBoard] = []
    for port_info in serial.tools.list_ports.comports():
        board = _classify_port(port_info)
        if board is None:
            continue
        if family_filter and board.family != family_filter:
            continue
        results.append(board)
    return results


def pick_port_for_target(target: str, preferred_port: str | None = None) -> str | None:
    """
    Return the best serial port for the given target chip family.

    Prefers *preferred_port* if explicitly specified and present.
    Otherwise returns the first auto-detected board of the right family.
    """
    if preferred_port:
        return preferred_port

    family = "esp32" if target.startswith("esp32") else "rp2040"
    boards = detect_boards(family_filter=family)
    return boards[0].port if boards else None
