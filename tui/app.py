"""Textual terminal interface for HIL Debug Workbench."""

from __future__ import annotations

import asyncio
import os
from typing import ClassVar

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, Label, ProgressBar, RichLog

from hil_cli.config import BoardConfig, HilConfig
from hil_cli.detector import detect_boards, pick_port_for_target
from hil_cli.flasher import flash_firmware
from hil_cli.heal_loop import HealLoop, HealLoopEvent
from hil_cli.serial_monitor import CrashDetected, LogEvent, PortError, SerialMonitor, StableEvent

CSS = """
Screen {
    background: #0D1117;
}

#layout {
    layout: grid;
    grid-size: 3 2;
    grid-columns: 24 1fr 26;
    grid-rows: 1fr 10;
    height: 100%;
}

/* Pipeline sidebar */
#sidebar {
    background: #161B22;
    border-right: solid #21262D;
    padding: 1 1;
}

PipelineStep {
    height: 3;
    padding: 0 1;
    color: #8B949E;
}
PipelineStep.active {
    color: #388BFD;
    background: #1C2128;
}
PipelineStep.done {
    color: #3FB950;
}
PipelineStep.error {
    color: #F85149;
}

/* Serial log */
#log-panel {
    background: #161B22;
    border-left: solid #21262D;
    border-right: solid #21262D;
}

RichLog {
    background: #0D1117;
    color: #E6EDF3;
}

/* Stats panel */
#stats-panel {
    background: #161B22;
    border-left: solid #21262D;
    padding: 1 1;
}

StatBar {
    height: 3;
    margin-bottom: 1;
}

/* Crash panel */
#crash-panel {
    column-span: 3;
    background: #161B22;
    border-top: solid #21262D;
    padding: 0 1;
    overflow-y: scroll;
}

/* Toolbar */
#toolbar {
    background: #161B22;
    border-bottom: solid #21262D;
    height: 3;
    padding: 0 1;
    layout: horizontal;
    align: left middle;
}

Button {
    margin: 0 1;
    background: #21262D;
    border: tall #30363D;
    color: #E6EDF3;
    min-width: 14;
}
Button:focus { border: tall #388BFD; }
Button.-primary {
    background: #0D419D;
    border: tall #1158C7;
    color: white;
}
Button:hover { background: #30363D; }

#state-label {
    color: #8B949E;
    margin: 0 2;
}
"""


class PipelineStep(Widget):
    """A single pipeline step indicator."""

    DEFAULT_CSS = ""
    step_name: reactive[str] = reactive("")

    def __init__(self, name: str, label: str, number: int) -> None:
        super().__init__(id=f"step-{name}", classes="")
        self.step_name = name
        self._label = label
        self._number = number

    def render(self) -> Text:
        icon = "●" if "active" in self.classes else ("✓" if "done" in self.classes else "○")
        return Text(f" {icon} {self._number}. {self._label}")


class StatBar(Widget):
    """A labeled progress bar for CPU / memory metrics."""

    value: reactive[float] = reactive(0.0)

    def __init__(self, label: str, widget_id: str) -> None:
        super().__init__(id=widget_id)
        self._label = label

    def compose(self) -> ComposeResult:
        yield Label(f"{self._label}", id=f"{self.id}-lbl")
        yield ProgressBar(total=100, id=f"{self.id}-bar", show_eta=False)

    def set_value(self, v: float) -> None:
        self.value = v
        try:
            bar = self.query_one(f"#{self.id}-bar", ProgressBar)
            bar.update(progress=int(v))
        except NoMatches:
            pass


class HilTuiApp(App[None]):
    """HIL Debug Workbench terminal UI."""

    TITLE = "HIL Debug Workbench"
    CSS = CSS
    BINDINGS: ClassVar = [
        Binding("f", "flash", "Flash"),
        Binding("m", "monitor", "Monitor"),
        Binding("h", "heal", "Self-Heal"),
        Binding("s", "stop", "Stop"),
        Binding("c", "clear_log", "Clear"),
        Binding("q", "quit", "Quit"),
    ]

    _state: reactive[str] = reactive("idle")
    _crash_count: reactive[int] = reactive(0)
    _cycle: reactive[int] = reactive(0)
    _cycle_max: reactive[int] = reactive(10)

    def __init__(self, cfg: HilConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self._monitor: SerialMonitor | None = None
        self._heal_loop: HealLoop | None = None
        self._active_board: BoardConfig | None = None
        self._active_port: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="layout"):
            # Sidebar: pipeline
            with Vertical(id="sidebar"):
                yield Label("[b]Pipeline[/b]", markup=True)
                yield PipelineStep("detect", "Detect board", 1)
                yield PipelineStep("flash", "Build & Flash", 2)
                yield PipelineStep("monitor", "Monitor", 3)
                yield PipelineStep("analyze", "Analyze crash", 4)
                yield PipelineStep("ai_fixing", "AI fix", 5)
                yield PipelineStep("applying", "Apply & Flash", 6)
                yield Label("", id="cycle-label")
                yield Label("", id="port-label")

            # Center: serial log
            with Vertical(id="log-panel"):
                with Horizontal(id="toolbar"):
                    yield Button("Flash", id="btn-flash", variant="default")
                    yield Button("Monitor", id="btn-monitor", variant="default")
                    yield Button("Self-Heal", id="btn-heal", variant="primary")
                    yield Button("Stop", id="btn-stop", disabled=True)
                    yield Label("idle", id="state-label")
                yield RichLog(id="serial-log", highlight=True, markup=False)

            # Right: stats
            with Vertical(id="stats-panel"):
                yield Label("[b]System[/b]", markup=True)
                yield StatBar("CPU0", "stat-cpu0")
                yield StatBar("CPU1", "stat-cpu1")
                yield Label("", id="heap-label")
                yield Label("", id="crash-label")

            # Bottom: crash analysis
            with Vertical(id="crash-panel"):
                yield Label("[b]Crash Analysis[/b]", markup=True)
                yield RichLog(id="crash-log", highlight=True, markup=False)

        yield Footer()

    def on_mount(self) -> None:
        self._refresh_boards()
        if self.cfg.boards:
            self._active_board = self.cfg.boards[0]
            self._cycle_max = self.cfg.boards[0].max_heal_cycles

    def _refresh_boards(self) -> None:
        detected = detect_boards()
        port_label = self.query_one("#port-label", Label)
        if detected:
            port_label.update(f"[green]{detected[0].port}[/green]")
        else:
            port_label.update("[yellow]No board detected[/yellow]")

    def _set_state(self, state: str) -> None:
        self._state = state
        lbl = self.query_one("#state-label", Label)
        color_map = {
            "flashing": "yellow",
            "monitoring": "cyan",
            "analyzing": "magenta",
            "ai_fixing": "blue",
            "applying": "white",
            "stable": "green",
            "failed": "red",
            "idle": "dim",
        }
        color = color_map.get(state, "white")
        lbl.update(f"[{color}]{state}[/{color}]")

        # Update pipeline step highlights
        STEPS = ["detect", "flash", "monitor", "analyze", "ai_fixing", "applying"]
        DONE_MAP = {
            "flashing": ["detect"],
            "monitoring": ["detect", "flash"],
            "analyzing": ["detect", "flash", "monitor"],
            "ai_fixing": ["detect", "flash", "monitor", "analyze"],
            "applying": ["detect", "flash", "monitor", "analyze", "ai_fixing"],
            "stable": STEPS,
        }
        done = DONE_MAP.get(state, [])
        for step_name in STEPS:
            try:
                w = self.query_one(f"#step-{step_name}", PipelineStep)
                w.remove_class("active", "done", "error")
                if step_name == state:
                    w.add_class("active")
                elif step_name in done:
                    w.add_class("done")
                if state == "failed" and step_name == "flash":
                    w.add_class("error")
            except NoMatches:
                pass

        # Toggle stop button
        active = state not in ("idle", "stable", "failed")
        self.query_one("#btn-stop", Button).disabled = not active
        self.query_one("#btn-heal", Button).disabled = active
        self.query_one("#btn-flash", Button).disabled = active
        self.query_one("#btn-monitor", Button).disabled = active

    def _append_serial(self, text: str, style: str = "") -> None:
        log = self.query_one("#serial-log", RichLog)
        if style:
            log.write(Text(text, style=style))
        else:
            log.write(text)

    def _update_cycle(self) -> None:
        self.query_one("#cycle-label", Label).update(
            f"Cycle: [b]{self._cycle}[/b] / {self._cycle_max}"
        )

    def _update_crash(self) -> None:
        count = self._crash_count
        color = "red" if count > 0 else "dim"
        self.query_one("#crash-label", Label).update(f"[{color}]Crashes: {count}[/{color}]")

    @on(Button.Pressed, "#btn-flash")
    def handle_flash(self) -> None:
        self._do_flash()

    @on(Button.Pressed, "#btn-monitor")
    def handle_monitor(self) -> None:
        self._start_monitor_only()

    @on(Button.Pressed, "#btn-heal")
    def handle_heal(self) -> None:
        self._do_heal()

    @on(Button.Pressed, "#btn-stop")
    def handle_stop(self) -> None:
        if self._monitor:
            self._monitor.stop()
            self._monitor = None
        self._set_state("idle")

    def action_flash(self) -> None:
        self._do_flash()

    def action_monitor(self) -> None:
        self._start_monitor_only()

    def action_heal(self) -> None:
        self._do_heal()

    def action_stop(self) -> None:
        self.handle_stop()

    def action_clear_log(self) -> None:
        self.query_one("#serial-log", RichLog).clear()

    def _do_flash(self) -> None:
        if not self._active_board:
            return
        port = pick_port_for_target(self._active_board.target, self._active_board.port)
        if not port:
            self._append_serial("No port found — check USB connection", "red")
            return
        self._active_port = port
        self._run_flash_task(port)

    @work(exclusive=True)
    async def _run_flash_task(self, port: str) -> None:
        board = self._active_board
        if not board:
            return
        self._set_state("flashing")
        log_q: asyncio.Queue[str] = asyncio.Queue()

        async def drain() -> None:
            while True:
                line = await log_q.get()
                self._append_serial(line, "dim white")

        drain_task = asyncio.create_task(drain())
        result = await flash_firmware(board.pio_project_dir, board.pio_env, port, log_q)
        drain_task.cancel()

        if result.ok:
            self._append_serial(f"✓ Flash complete ({result.duration_s:.1f}s)", "green")
        else:
            self._append_serial(f"✗ Flash failed\n{result.error_summary()}", "red")
        self._set_state("idle" if result.ok else "failed")

    @work(exclusive=True)
    async def _do_heal(self) -> None:
        board = self._active_board
        if not board:
            return
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            self._append_serial("⚠ ANTHROPIC_API_KEY not set", "red")
            return
        port = pick_port_for_target(board.target, board.port)
        if not port:
            self._append_serial("No port found — check USB connection", "red")
            return
        self._active_port = port
        self._cycle = 0
        self._crash_count = 0

        loop_obj = HealLoop(board, anthropic_api_key=api_key)
        self._heal_loop = loop_obj
        event_q = loop_obj.subscribe()

        async def consume() -> None:
            while True:
                evt: HealLoopEvent = await event_q.get()
                if evt.kind == "state_change":
                    self._set_state(evt.payload)
                elif evt.kind == "serial_line":
                    self._append_serial(evt.payload["text"])
                elif evt.kind == "crash":
                    self._crash_count += 1
                    self._update_crash()
                    self._append_serial(f"💥 CRASH: {evt.payload['kind']}", "bold red")
                elif evt.kind == "cycle_start":
                    self._cycle = evt.payload["cycle"]
                    self._cycle_max = evt.payload["max"]
                    self._update_cycle()
                elif evt.kind == "ai_fix":
                    crash_log = self.query_one("#crash-log", RichLog)
                    crash_log.clear()
                    crash_log.write(evt.payload.get("root_cause", ""))
                elif evt.kind == "fix_applied":
                    files = ", ".join(evt.payload.get("files", []))
                    self._append_serial(f"✎ Fix applied: {files}", "cyan")
                elif evt.kind == "stable":
                    self._append_serial(f"✓ STABLE at cycle {evt.payload['cycle']}", "bold green")
                elif evt.kind == "loop_done":
                    return

        consume_task = asyncio.create_task(consume())
        await loop_obj.run(port)
        await consume_task

    def _start_monitor_only(self) -> None:
        board = self._active_board
        if not board:
            return
        port = pick_port_for_target(board.target, board.port)
        if not port:
            self._append_serial("No port found", "red")
            return
        self._run_monitor_task(port)

    @work
    async def _run_monitor_task(self, port: str) -> None:
        board = self._active_board
        if not board:
            return
        event_q: asyncio.Queue = asyncio.Queue()
        mon = SerialMonitor(
            port=port,
            baud=board.baud_rate,
            target=board.target,
            event_queue=event_q,
            loop=asyncio.get_event_loop(),
            stability_window=float(board.stability_window),
        )
        self._monitor = mon
        self._set_state("monitoring")
        mon.start()
        try:
            while self._monitor is mon:
                evt = await asyncio.wait_for(event_q.get(), timeout=1.0)
                if isinstance(evt, LogEvent):
                    style = "bold red" if evt.line.is_crash_line else ""
                    self._append_serial(evt.line.text, style)
                elif isinstance(evt, CrashDetected):
                    self._crash_count += 1
                    self._update_crash()
                elif isinstance(evt, StableEvent):
                    self._append_serial(f"✓ Stable ({evt.duration_s:.0f}s)", "green")
                elif isinstance(evt, PortError):
                    self._append_serial(f"Port error: {evt.message}", "red")
                    break
        except TimeoutError:
            pass
        finally:
            mon.stop()
            if self._monitor is mon:
                self._monitor = None
                self._set_state("idle")
