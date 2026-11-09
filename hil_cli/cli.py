"""Command-line entry point for HIL Debug Workbench."""

from __future__ import annotations

import asyncio
import sys

import click
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from .config import BoardConfig, HilConfig, load_config
from .detector import detect_boards, pick_port_for_target
from .flasher import flash_firmware
from .heal_loop import HealLoop, HealState
from .serial_monitor import CrashDetected, LogEvent, PortError, SerialMonitor, StableEvent

console = Console()


def _load_cfg(config_path: str) -> HilConfig:
    try:
        return load_config(config_path)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as e:
        console.print(f"[red]Config parse error:[/red] {e}")
        sys.exit(1)


def _pick_board(cfg: HilConfig, board_name: str | None) -> BoardConfig:
    if board_name:
        matches = [b for b in cfg.boards if b.name == board_name]
        if not matches:
            names = ", ".join(b.name for b in cfg.boards)
            console.print(f"[red]Board '{board_name}' not found.[/red] Available: {names}")
            sys.exit(1)
        return matches[0]
    if len(cfg.boards) == 1:
        return cfg.boards[0]
    names = ", ".join(b.name for b in cfg.boards)
    console.print(
        f"[yellow]Multiple boards configured — specify one with --board.[/yellow] ({names})"
    )
    sys.exit(1)


def _resolve_port(board: BoardConfig) -> str:
    port = pick_port_for_target(board.target, board.port)
    if port is None:
        console.print(
            f"[red]No {board.target} board detected.[/red] "
            "Check USB connection or set 'port' in hil.yaml."
        )
        sys.exit(1)
    return port


@click.group()
@click.version_option(package_name="hil-debug-workbench")
def main() -> None:
    """Tools for testing ESP32 and RP2040 firmware on hardware."""


@main.command()
@click.option("--family", type=click.Choice(["esp32", "rp2040"]), help="Filter by chip family")
def detect(family: str | None) -> None:
    """Scan USB ports and list connected HIL-capable boards."""
    boards = detect_boards(family_filter=family)
    if not boards:
        console.print("[yellow]No supported boards detected.[/yellow]")
        return

    table = Table(title="Detected Boards", show_header=True, header_style="bold cyan")
    table.add_column("Port", style="green")
    table.add_column("Board")
    table.add_column("Family", style="dim")
    table.add_column("VID:PID", style="dim")
    for b in boards:
        vid_pid = f"{b.vid:04X}:{b.pid:04X}" if b.vid else "—"
        table.add_row(b.port, b.board_label, b.family, vid_pid)
    console.print(table)


@main.command()
@click.option("--config", "-c", default="hil.yaml", show_default=True, help="Path to hil.yaml")
@click.option("--board", "-b", default=None, help="Board name (from hil.yaml)")
@click.option("--port", "-p", default=None, help="Override serial port")
def flash(config: str, board: str | None, port: str | None) -> None:
    """Build and flash firmware via PlatformIO."""
    cfg = _load_cfg(config)
    brd = _pick_board(cfg, board)
    target_port = port or _resolve_port(brd)

    console.print(
        f"[cyan]Flashing[/cyan] [bold]{brd.name}[/bold] on [green]{target_port}[/green] …"
    )

    async def _run() -> None:
        log_q: asyncio.Queue[str] = asyncio.Queue()

        async def _print_logs() -> None:
            while True:
                line = await log_q.get()
                console.print(f"  [dim]{line}[/dim]")

        log_task = asyncio.create_task(_print_logs())
        result = await flash_firmware(brd.pio_project_dir, brd.pio_env, target_port, log_q)
        log_task.cancel()

        if result.ok:
            console.print(f"[green]✓ Flash complete[/green] ({result.duration_s:.1f}s)")
        else:
            console.print(f"[red]✗ Flash failed[/red]\n{result.error_summary()}")
            sys.exit(1)

    asyncio.run(_run())


@main.command()
@click.option("--config", "-c", default="hil.yaml", show_default=True)
@click.option("--board", "-b", default=None)
@click.option("--port", "-p", default=None)
def monitor(config: str, board: str | None, port: str | None) -> None:
    """Open a live serial monitor (Ctrl-C to exit)."""
    cfg = _load_cfg(config)
    brd = _pick_board(cfg, board)
    target_port = port or _resolve_port(brd)

    console.print(
        f"[cyan]Monitoring[/cyan] {target_port} @ {brd.baud_rate} baud  (Ctrl-C to quit)\n"
    )

    async def _run() -> None:
        event_q: asyncio.Queue = asyncio.Queue()
        mon = SerialMonitor(
            port=target_port,
            baud=brd.baud_rate,
            target=brd.target,
            event_queue=event_q,
            loop=asyncio.get_event_loop(),
            stability_window=float(brd.stability_window),
        )
        mon.start()
        try:
            while True:
                evt = await event_q.get()
                if isinstance(evt, LogEvent):
                    style = "bold red" if evt.line.is_crash_line else ""
                    console.print(evt.line.text, style=style)
                elif isinstance(evt, CrashDetected):
                    console.rule("[red]CRASH DETECTED[/red]")
                    console.print(f"[red]Kind:[/red] {evt.event.kind.value}")
                    console.print(f"[red]Addresses:[/red] {evt.event.addresses}")
                elif isinstance(evt, StableEvent):
                    console.print(f"[green]✓ Stable for {evt.duration_s:.0f}s[/green]")
                elif isinstance(evt, PortError):
                    console.print(f"[red]Port error:[/red] {evt.message}")
                    break
        except asyncio.CancelledError:
            pass
        finally:
            mon.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[dim]Monitor stopped.[/dim]")


@main.command()
@click.option("--config", "-c", default="hil.yaml", show_default=True)
@click.option("--board", "-b", default=None)
@click.option("--port", "-p", default=None)
@click.option("--api-key", envvar="ANTHROPIC_API_KEY", default=None, help="Anthropic API key")
def heal(config: str, board: str | None, port: str | None, api_key: str | None) -> None:
    """
    Run the bounded flash, monitor, and repair loop.

    Upload firmware, watch for crashes, and ask Claude to propose a source edit.
    The command repeats until the board stays stable or reaches the cycle limit.
    """
    cfg = _load_cfg(config)
    brd = _pick_board(cfg, board)
    target_port = port or _resolve_port(brd)

    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY not set.[/red] Pass --api-key or export it.")
        sys.exit(1)

    console.rule(f"[bold cyan]HIL Self-Heal — {brd.name}[/bold cyan]")
    console.print(f"  Port     : [green]{target_port}[/green]")
    console.print(f"  Target   : {brd.target}")
    console.print(f"  Env      : {brd.pio_env}")
    console.print(f"  Stability: {brd.stability_window}s   Max cycles: {brd.max_heal_cycles}")
    console.print()

    loop_obj = HealLoop(
        brd, ai_model=cfg.ai_model, ai_max_tokens=cfg.ai_max_tokens, anthropic_api_key=api_key
    )
    event_q = loop_obj.subscribe()

    STATE_COLORS = {
        HealState.FLASHING: "yellow",
        HealState.MONITORING: "cyan",
        HealState.ANALYZING: "magenta",
        HealState.AI_FIXING: "blue",
        HealState.APPLYING: "white",
        HealState.STABLE: "green",
        HealState.FAILED: "red",
    }

    async def _run() -> None:
        async def _consume_events() -> None:
            while True:
                evt = await event_q.get()
                if evt.kind == "state_change":
                    color = STATE_COLORS.get(HealState(evt.payload), "white")
                    console.print(f"  [{color}]▶ {evt.payload}[/{color}]")
                elif evt.kind == "serial_line":
                    line = evt.payload["text"]
                    if any(k in line for k in ("Error", "panic", "Backtrace", "PANIC")):
                        console.print(f"  [red]{line}[/red]")
                    else:
                        console.print(f"  [dim]{line}[/dim]")
                elif evt.kind == "crash":
                    console.print(f"  [red]Crash: {evt.payload['kind']}[/red]")
                elif evt.kind == "ai_fix":
                    console.print(f"  [blue]Claude: {evt.payload['root_cause'][:120]}[/blue]")
                elif evt.kind == "fix_applied":
                    console.print(f"  [green]✎ Fixed: {', '.join(evt.payload['files'])}[/green]")
                elif evt.kind == "stable":
                    console.print(
                        f"  [bold green]✓ STABLE at cycle {evt.payload['cycle']}[/bold green]"
                    )
                elif evt.kind == "loop_done":
                    return
                elif evt.kind == "port_error":
                    console.print(f"  [red]Port error: {evt.payload}[/red]")

        event_task = asyncio.create_task(_consume_events())
        summary = await loop_obj.run(target_port)
        await event_task

        console.rule()
        if summary.final_state == HealState.STABLE:
            console.print(
                f"[bold green]Firmware stable after {summary.total_cycles} cycle(s)[/bold green]"
            )
        else:
            console.print(f"[bold red]Heal loop ended: {summary.final_state.value}[/bold red]")
        console.print(f"  Duration: {summary.duration_s:.1f}s")

    asyncio.run(_run())


@main.command()
@click.option("--config", "-c", default="hil.yaml", show_default=True)
@click.option("--port", "-p", default=None, help="Dashboard HTTP port (overrides hil.yaml)")
def dashboard(config: str, port: int | None) -> None:
    """Launch the local web dashboard."""
    cfg = _load_cfg(config)
    dash_port = port or cfg.dashboard_port

    try:
        import uvicorn

        from dashboard.server import create_app
    except ImportError:
        console.print(
            "[red]Dashboard dependencies missing.[/red] Run: pip install hil-debug-workbench[dashboard]"
        )
        sys.exit(1)

    app = create_app(cfg)
    console.print(f"[cyan]Dashboard:[/cyan] http://localhost:{dash_port}")
    uvicorn.run(app, host="127.0.0.1", port=dash_port, log_level="warning")


@main.command()
@click.option("--config", "-c", default="hil.yaml", show_default=True)
def tui(config: str) -> None:
    """Launch the full Textual terminal workbench."""
    cfg = _load_cfg(config)
    try:
        from tui.app import HilTuiApp
    except ImportError:
        console.print("[red]TUI dependencies missing.[/red] Run: pip install textual")
        sys.exit(1)
    HilTuiApp(cfg).run()


if __name__ == "__main__":
    main()
