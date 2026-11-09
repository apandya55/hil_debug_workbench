"""Automated flash, monitor, crash analysis, and LLM patch application loop."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import anthropic

from .config import BoardConfig
from .crash_analyzer import CrashReport, analyze_crash
from .flasher import FlashResult, flash_firmware
from .serial_monitor import (
    CrashDetected,
    LogEvent,
    MonitorEvent,
    PortError,
    SerialMonitor,
    StableEvent,
)


class HealState(str, Enum):
    IDLE = "idle"
    FLASHING = "flashing"
    MONITORING = "monitoring"
    ANALYZING = "analyzing"
    AI_FIXING = "ai_fixing"
    APPLYING = "applying"
    STABLE = "stable"
    FAILED = "failed"


@dataclass
class HealCycleResult:
    cycle: int
    flash_result: FlashResult | None = None
    crash_report: CrashReport | None = None
    fix_applied: bool = False
    error: str | None = None


@dataclass
class HealSummary:
    board_name: str
    total_cycles: int
    final_state: HealState
    stable_at_cycle: int | None = None
    duration_s: float = 0.0
    cycle_results: list[HealCycleResult] = field(default_factory=list)


EventCallback = Callable[[str, Any], Coroutine[Any, Any, None]]


@dataclass
class HealLoopEvent:
    kind: str
    payload: Any


_FIX_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string"},
        "fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["file", "old_code", "new_code", "explanation"],
                "properties": {
                    "file": {"type": "string"},
                    "old_code": {"type": "string"},
                    "new_code": {"type": "string"},
                    "explanation": {"type": "string"},
                },
            },
        },
    },
    "required": ["root_cause", "fixes"],
}

_SYSTEM_PROMPT = """\
You are an embedded C++ firmware debugger specializing in ESP32 (Xtensa) and RP2040 (ARM Cortex-M0+).
You receive a crash dump with addr2line-resolved backtrace and relevant source context.
Your job: identify the root cause and return a minimal, targeted fix.

Rules:
- Fix only the actual bug. Do not refactor unrelated code.
- Prefer the smallest change that eliminates the crash.
- Return valid JSON conforming exactly to the provided schema.
- old_code must be the verbatim current code (exact match for replacement).
- new_code must be a drop-in replacement for old_code.
- If you cannot determine a fix with confidence, set fixes to an empty array and explain in root_cause.
"""


async def _call_ai_fix(
    report: CrashReport,
    model: str,
    max_tokens: int,
    client: anthropic.AsyncAnthropic,
) -> dict[str, Any]:
    """Query Claude for root-cause analysis and a structured code patch."""
    user_message = f"""Please analyze this firmware crash and provide a fix.

{report.context_for_ai()}

Return your response as JSON matching this schema:
```json
{json.dumps(_FIX_SCHEMA, indent=2)}
```
"""
    message = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = ""
    for block in message.content or []:
        if hasattr(block, "text"):
            raw += block.text

    json_match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    if json_match:
        raw = json_match.group(1)

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return {"root_cause": f"AI response not a JSON dictionary:\n{raw}", "fixes": []}
    except json.JSONDecodeError:
        return {"root_cause": f"AI response not valid JSON:\n{raw}", "fixes": []}


def _apply_fix(fix: dict[str, Any], project_dir: str) -> list[str]:
    """Apply verbatim source replacements proposed by the LLM."""
    modified: list[str] = []
    for patch in fix.get("fixes", []):
        fpath_raw: str = patch.get("file", "")
        old: str = patch.get("old_code", "")
        new: str = patch.get("new_code", "")
        if not fpath_raw or not old:
            continue

        project_root = Path(project_dir).resolve()
        fpath = Path(fpath_raw)
        if not fpath.is_absolute():
            fpath = project_root / fpath

        # Prevent symlink directory escapes
        fpath = fpath.resolve()
        if not fpath.is_relative_to(project_root) or not fpath.is_file():
            continue

        content = fpath.read_text(errors="replace")
        if old not in content:
            continue

        new_content = content.replace(old, new, 1)
        fpath.write_text(new_content, encoding="utf-8")
        modified.append(str(fpath))

    return modified


class HealLoop:
    """Manages iterative flash-monitor-analyze-patch cycles for physical boards."""

    def __init__(
        self,
        board: BoardConfig,
        ai_model: str = "claude-opus-5-5",
        ai_max_tokens: int = 4096,
        anthropic_api_key: str | None = None,
    ) -> None:
        self.board = board
        self.ai_model = ai_model
        self.ai_max_tokens = ai_max_tokens
        self._state = HealState.IDLE
        self._subscribers: list[asyncio.Queue[HealLoopEvent]] = []
        self._ai_client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
        self._monitor: SerialMonitor | None = None
        self._log_q: asyncio.Queue[str] = asyncio.Queue()

    def subscribe(self) -> asyncio.Queue[HealLoopEvent]:
        q: asyncio.Queue[HealLoopEvent] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    async def _emit(self, kind: str, payload: Any = None) -> None:
        evt = HealLoopEvent(kind=kind, payload=payload)
        for q in self._subscribers:
            await q.put(evt)

    async def _set_state(self, state: HealState) -> None:
        self._state = state
        await self._emit("state_change", state.value)

    @property
    def state(self) -> HealState:
        return self._state

    async def run(self, port: str) -> HealSummary:
        t0 = time.monotonic()
        summary = HealSummary(
            board_name=self.board.name, total_cycles=0, final_state=HealState.IDLE
        )

        await self._set_state(HealState.IDLE)

        for cycle in range(1, self.board.max_heal_cycles + 1):
            cycle_result = HealCycleResult(cycle=cycle)
            await self._emit("cycle_start", {"cycle": cycle, "max": self.board.max_heal_cycles})

            # 1. Flash
            await self._set_state(HealState.FLASHING)
            flash_result = await flash_firmware(
                pio_project_dir=self.board.pio_project_dir,
                pio_env=self.board.pio_env,
                port=port,
                log_queue=self._log_q,
            )
            cycle_result.flash_result = flash_result
            await self._emit(
                "flash_done", {"ok": flash_result.ok, "duration": flash_result.duration_s}
            )

            if not flash_result.ok:
                cycle_result.error = flash_result.error_summary()
                await self._emit("flash_error", cycle_result.error)
                summary.cycle_results.append(cycle_result)
                await self._set_state(HealState.FAILED)
                break

            # 2. Monitor
            await self._set_state(HealState.MONITORING)
            crash_event = await self._monitor_until_event(port)

            if crash_event is None:
                await self._emit("stable", {"cycle": cycle})
                await self._set_state(HealState.STABLE)
                summary.stable_at_cycle = cycle
                summary.cycle_results.append(cycle_result)
                break

            await self._emit(
                "crash", {"kind": crash_event.kind.value, "addresses": crash_event.addresses}
            )

            # 3. Analyze
            await self._set_state(HealState.ANALYZING)
            elf = self.board.resolved_elf()
            report = analyze_crash(crash_event, elf, self.board.toolchain_prefix)
            cycle_result.crash_report = report
            await self._emit("analysis_done", {"locations": len(report.locations)})

            # 4. Request fix from LLM
            await self._set_state(HealState.AI_FIXING)
            fix_data = await _call_ai_fix(
                report, self.ai_model, self.ai_max_tokens, self._ai_client
            )
            report.ai_analysis = str(fix_data.get("root_cause", ""))
            report.suggested_fixes = list(fix_data.get("fixes", []))
            await self._emit(
                "ai_fix", {"root_cause": report.ai_analysis, "patches": len(report.suggested_fixes)}
            )

            # 5. Apply fix
            await self._set_state(HealState.APPLYING)
            if report.suggested_fixes:
                modified = _apply_fix(fix_data, self.board.pio_project_dir)
                cycle_result.fix_applied = bool(modified)
                await self._emit("fix_applied", {"files": modified})
            else:
                await self._emit("no_fix", {"reason": report.ai_analysis})

            summary.cycle_results.append(cycle_result)
            summary.total_cycles = cycle

        summary.total_cycles = len(summary.cycle_results)
        summary.final_state = self._state
        summary.duration_s = time.monotonic() - t0
        await self._emit("loop_done", {"state": self._state.value, "cycles": summary.total_cycles})
        return summary

    async def _monitor_until_event(self, port: str) -> Any | None:
        event_q: asyncio.Queue[MonitorEvent] = asyncio.Queue()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        monitor = SerialMonitor(
            port=port,
            baud=self.board.baud_rate,
            target=self.board.target,
            event_queue=event_q,
            loop=loop,
            stability_window=float(self.board.stability_window),
        )
        self._monitor = monitor
        monitor.start()

        try:
            while True:
                evt = await event_q.get()
                if isinstance(evt, LogEvent):
                    await self._emit(
                        "serial_line", {"text": evt.line.text, "ts": evt.line.timestamp}
                    )
                elif isinstance(evt, CrashDetected):
                    return evt.event
                elif isinstance(evt, StableEvent):
                    return None
                elif isinstance(evt, PortError):
                    await self._emit("port_error", evt.message)
                    return None
        finally:
            monitor.stop()
            self._monitor = None
