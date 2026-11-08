"""Serial port reader with automated crash pattern detection for ESP32 and RP2040."""

from __future__ import annotations

import asyncio
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

import serial

# Xtensa / ESP32 crash patterns
_ESP32_PANIC_RE = re.compile(
    r"(Guru Meditation Error|Backtrace:|Stack smashing|assert failed"
    r"|LoadProhibited|StoreProhibited|IllegalInstruction|InstrFetchProhibited"
    r"|Unhandled debug exception|Watchdog|WDT reset|abort\(\))",
    re.IGNORECASE,
)
_ESP32_BACKTRACE_LINE_RE = re.compile(r"Backtrace:\s*((?:0x[0-9a-fA-F]+:0x[0-9a-fA-F]+\s*)+)")
_ESP32_ADDR_RE = re.compile(r"0x([0-9a-fA-F]+):0x[0-9a-fA-F]+")
_ESP32_REGISTER_RE = re.compile(r"(PC|SP|A\d|MEPC|MSTATUS)\s*:\s*(0x[0-9a-fA-F]+)")

# ARM Cortex-M0+ / RP2040 crash patterns
_RP2040_PANIC_RE = re.compile(
    r"(\*\*\* PANIC \*\*\*|HardFault|assertion.*failed|panic:|ASSERT|"
    r"Unhandled interrupt|Stack overflow|EXCEPTION)",
    re.IGNORECASE,
)
_RP2040_ADDR_RE = re.compile(r"(?:pc|PC)\s*[=:]\s*0x([0-9a-fA-F]+)")

# Watchdog resets (ESP-IDF TG0WDT / TG1WDT / RTCWDT)
_WATCHDOG_RE = re.compile(r"(rst:0x[0-9a-fA-F]+.*WDT|watchdog|reboot reason: WDT)", re.IGNORECASE)


class CrashKind(str, Enum):
    GURU_MEDITATION = "guru_meditation"
    STACK_OVERFLOW = "stack_overflow"
    WATCHDOG = "watchdog"
    ASSERTION = "assertion"
    HARD_FAULT = "hard_fault"
    ABORT = "abort"
    UNKNOWN = "unknown"


@dataclass
class CrashEvent:
    kind: CrashKind
    raw_dump: str
    addresses: list[str]  # hex strings without 0x prefix
    timestamp: float = field(default_factory=time.monotonic)
    board_target: str = "esp32"


@dataclass
class SerialLine:
    text: str
    timestamp: float = field(default_factory=time.monotonic)
    is_crash_line: bool = False


class MonitorEvent:
    pass


@dataclass
class LogEvent(MonitorEvent):
    line: SerialLine


@dataclass
class CrashDetected(MonitorEvent):
    event: CrashEvent


@dataclass
class StableEvent(MonitorEvent):
    duration_s: float


@dataclass
class PortError(MonitorEvent):
    message: str


class SerialMonitor:
    """Background serial port reader that emits events to an asyncio queue."""

    _CRASH_WINDOW = 60  # lines preserved before panic for context
    _CRASH_TIMEOUT = 1.5  # seconds of post-panic silence before flushing crash dump

    def __init__(
        self,
        port: str,
        baud: int,
        target: str,
        event_queue: asyncio.Queue[MonitorEvent],
        loop: asyncio.AbstractEventLoop | None = None,
        stability_window: float = 30.0,
    ) -> None:
        self.port = port
        self.baud = baud
        self.target = target
        self.event_queue = event_queue
        if loop is not None:
            self.loop = loop
        else:
            try:
                self.loop = asyncio.get_running_loop()
            except RuntimeError:
                try:
                    self.loop = asyncio.get_event_loop()
                except RuntimeError:
                    self.loop = asyncio.new_event_loop()
        self.stability_window = stability_window

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._crash_panic_re = _ESP32_PANIC_RE if target.startswith("esp32") else _RP2040_PANIC_RE
        self._addr_re = _ESP32_ADDR_RE if target.startswith("esp32") else _RP2040_ADDR_RE

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="serial-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def _emit(self, event: MonitorEvent) -> None:
        asyncio.run_coroutine_threadsafe(self.event_queue.put(event), self.loop)

    def _run(self) -> None:
        try:
            self._read_loop()
        except (serial.SerialException, OSError) as exc:
            self._emit(PortError(message=str(exc)))

    def _read_loop(self) -> None:
        try:
            ser = serial.Serial(self.port, self.baud, timeout=0.5)
        except serial.SerialException as exc:
            self._emit(PortError(message=f"Cannot open {self.port}: {exc}"))
            return

        rolling: list[str] = []
        in_crash = False
        crash_lines: list[str] = []
        last_crash_time = 0.0
        last_stable_emit = time.monotonic()

        try:
            while not self._stop_event.is_set():
                raw = ser.readline()
                now = time.monotonic()

                if not raw:
                    # Flush crash dump once serial traffic settles after a panic
                    if in_crash and (now - last_crash_time) > self._CRASH_TIMEOUT:
                        crash_event = self._build_crash(crash_lines)
                        self._emit(CrashDetected(event=crash_event))
                        in_crash = False
                        crash_lines = []
                    elif not in_crash and (now - last_stable_emit) >= self.stability_window:
                        self._emit(StableEvent(duration_s=self.stability_window))
                        last_stable_emit = now
                    continue

                line = raw.decode(errors="replace").rstrip()
                serial_line = SerialLine(text=line, timestamp=now)

                rolling.append(line)
                if len(rolling) > self._CRASH_WINDOW:
                    rolling.pop(0)

                is_panic = bool(self._crash_panic_re.search(line))
                is_watchdog = bool(_WATCHDOG_RE.search(line))

                if is_panic or is_watchdog:
                    if not in_crash:
                        in_crash = True
                        crash_lines = list(rolling)
                    last_crash_time = now
                    serial_line.is_crash_line = True
                    last_stable_emit = now

                if in_crash:
                    if line not in crash_lines:
                        crash_lines.append(line)
                    last_crash_time = now

                self._emit(LogEvent(line=serial_line))
        finally:
            ser.close()

    def _build_crash(self, lines: list[str]) -> CrashEvent:
        raw = "\n".join(lines)
        addresses = [m.group(1) for m in self._addr_re.finditer(raw)]

        # Preserve order while stripping duplicates
        seen: set[str] = set()
        unique_addrs: list[str] = []
        for a in addresses:
            if a not in seen:
                seen.add(a)
                unique_addrs.append(a)

        kind = CrashKind.UNKNOWN
        if _WATCHDOG_RE.search(raw):
            kind = CrashKind.WATCHDOG
        elif "Stack smashing" in raw or "stack overflow" in raw.lower():
            kind = CrashKind.STACK_OVERFLOW
        elif "Guru Meditation" in raw:
            kind = CrashKind.GURU_MEDITATION
        elif "assert" in raw.lower():
            kind = CrashKind.ASSERTION
        elif "HardFault" in raw:
            kind = CrashKind.HARD_FAULT
        elif "abort" in raw.lower():
            kind = CrashKind.ABORT

        return CrashEvent(
            kind=kind,
            raw_dump=raw,
            addresses=unique_addrs,
            board_target=self.target,
        )
