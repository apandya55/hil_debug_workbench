"""Local web dashboard backend powered by FastAPI and WebSockets."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from hil_cli.config import BoardConfig, HilConfig
from hil_cli.detector import detect_boards, pick_port_for_target
from hil_cli.heal_loop import HealLoop
from hil_cli.serial_monitor import (
    CrashDetected,
    LogEvent,
    MonitorEvent,
    PortError,
    SerialMonitor,
)

STATIC_DIR = Path(__file__).parent / "static"


class WorkbenchState:
    def __init__(self, cfg: HilConfig) -> None:
        self.cfg = cfg
        self.active_board: BoardConfig | None = None
        self.active_port: str | None = None
        self.heal_loop: HealLoop | None = None
        self.monitor: SerialMonitor | None = None
        self.heal_state: str = "idle"
        self.serial_log: list[dict[str, Any]] = []
        self.crashes: list[dict[str, Any]] = []
        self.cycle_count: int = 0
        self.ws_clients: list[WebSocket] = []

    async def broadcast(self, msg: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in self.ws_clients:
            try:
                await ws.send_json(msg)
            except (OSError, RuntimeError):
                dead.append(ws)
        for ws in dead:
            if ws in self.ws_clients:
                self.ws_clients.remove(ws)


_state: WorkbenchState | None = None


def _get_state() -> WorkbenchState:
    assert _state is not None, "WorkbenchState is uninitialized"
    return _state


def create_app(cfg: HilConfig) -> FastAPI:
    global _state
    _state = WorkbenchState(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield

    app = FastAPI(title="HIL Debug Workbench", lifespan=lifespan)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        state = _get_state()
        boards = detect_boards()
        return {
            "state": state.heal_state,
            "active_board": state.active_board.name if state.active_board else None,
            "active_port": state.active_port,
            "cycle": state.cycle_count,
            "crashes": len(state.crashes),
            "boards_detected": [
                {"port": b.port, "label": b.board_label, "family": b.family} for b in boards
            ],
            "configured_boards": [{"name": b.name, "target": b.target} for b in cfg.boards],
        }

    @app.get("/api/log")
    async def log_history() -> dict[str, Any]:
        state = _get_state()
        return {"lines": state.serial_log[-500:]}

    @app.get("/api/crashes")
    async def crash_history() -> dict[str, Any]:
        state = _get_state()
        return {"crashes": state.crashes}

    @app.post("/api/flash")
    async def trigger_flash(body: dict[str, Any]) -> JSONResponse | dict[str, Any]:
        state = _get_state()
        if state.heal_state not in ("idle", "stable", "failed"):
            return JSONResponse(
                {"error": "A workbench operation is already running"}, status_code=409
            )
        board_name = body.get("board") or (cfg.boards[0].name if cfg.boards else None)
        board = next((b for b in cfg.boards if b.name == board_name), None)
        if board is None:
            return JSONResponse({"error": "Board not found"}, status_code=404)

        port = body.get("port") or pick_port_for_target(board.target, board.port)
        if port is None:
            return JSONResponse({"error": "No port available"}, status_code=400)

        state.active_board = board
        state.active_port = port
        state.heal_state = "flashing"
        asyncio.create_task(_run_flash(board, port))
        return {"status": "flashing", "board": board.name, "port": port}

    @app.post("/api/heal")
    async def trigger_heal(body: dict[str, Any]) -> JSONResponse | dict[str, Any]:
        state = _get_state()
        if state.heal_state not in ("idle", "stable", "failed"):
            return JSONResponse(
                {"error": "A workbench operation is already running"}, status_code=409
            )
        board_name = body.get("board") or (cfg.boards[0].name if cfg.boards else None)
        board = next((b for b in cfg.boards if b.name == board_name), None)
        if board is None:
            return JSONResponse({"error": "Board not found"}, status_code=404)

        api_key = body.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return JSONResponse({"error": "ANTHROPIC_API_KEY required"}, status_code=400)

        port = body.get("port") or pick_port_for_target(board.target, board.port)
        if port is None:
            return JSONResponse({"error": "No port available"}, status_code=400)

        state.active_board = board
        state.active_port = port
        state.cycle_count = 0
        state.heal_state = "flashing"
        asyncio.create_task(_run_heal(board, port, api_key))
        return {"status": "healing", "board": board.name, "port": port}

    @app.post("/api/monitor/start")
    async def start_monitor(body: dict[str, Any]) -> JSONResponse | dict[str, Any]:
        state = _get_state()
        if state.heal_state not in ("idle", "stable", "failed"):
            return JSONResponse(
                {"error": "A workbench operation is already running"}, status_code=409
            )
        board_name = body.get("board") or (cfg.boards[0].name if cfg.boards else None)
        board = next((b for b in cfg.boards if b.name == board_name), None)
        if board is None:
            return JSONResponse({"error": "Board not found"}, status_code=404)
        port = body.get("port") or pick_port_for_target(board.target, board.port)
        if port is None:
            return JSONResponse({"error": "No port available"}, status_code=400)
        state.heal_state = "monitoring"
        asyncio.create_task(_run_monitor_only(board, port))
        return {"status": "monitoring", "port": port}

    @app.post("/api/monitor/stop")
    async def stop_monitor() -> dict[str, Any]:
        state = _get_state()
        if state.monitor:
            state.monitor.stop()
            state.monitor = None
        state.heal_state = "idle"
        return {"status": "idle"}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        state = _get_state()
        await ws.accept()
        state.ws_clients.append(ws)
        await ws.send_json({"type": "log_history", "lines": state.serial_log[-100:]})
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            if ws in state.ws_clients:
                state.ws_clients.remove(ws)

    return app


async def _run_flash(board: BoardConfig, port: str) -> None:
    from hil_cli.flasher import flash_firmware

    state = _get_state()
    log_q: asyncio.Queue[str] = asyncio.Queue()

    async def _drain() -> None:
        while True:
            line = await log_q.get()
            _append_log(line, "flash")
            await state.broadcast({"type": "log", "text": line, "source": "flash"})

    drain_task = asyncio.create_task(_drain())
    try:
        result = await flash_firmware(board.pio_project_dir, board.pio_env, port, log_q)
        state.heal_state = "idle" if result.ok else "failed"
        await state.broadcast(
            {
                "type": "flash_done",
                "ok": result.ok,
                "duration": result.duration_s,
                "error": result.error_summary() if not result.ok else None,
            }
        )
    except Exception as exc:  # noqa: BLE001
        state.heal_state = "failed"
        await state.broadcast({"type": "error", "message": str(exc)})
    finally:
        drain_task.cancel()
        await asyncio.gather(drain_task, return_exceptions=True)


async def _run_heal(board: BoardConfig, port: str, api_key: str) -> None:
    state = _get_state()
    loop_obj = HealLoop(board, anthropic_api_key=api_key)
    event_q = loop_obj.subscribe()

    async def _consume() -> None:
        while True:
            evt = await event_q.get()
            if evt.kind == "state_change":
                state.heal_state = str(evt.payload)
                await state.broadcast({"type": "state_change", "state": evt.payload})
            elif evt.kind == "serial_line":
                text = str(evt.payload["text"])
                _append_log(text, "serial")
                await state.broadcast({"type": "log", "text": text, "source": "serial"})
            elif evt.kind == "crash":
                state.crashes.append({"ts": time.time(), **evt.payload})
                state.cycle_count += 1
                await state.broadcast({"type": "crash", **evt.payload})
            elif evt.kind == "ai_fix":
                await state.broadcast({"type": "ai_fix", **evt.payload})
            elif evt.kind == "fix_applied":
                await state.broadcast({"type": "fix_applied", **evt.payload})
            elif evt.kind == "stable":
                await state.broadcast({"type": "stable", **evt.payload})
            elif evt.kind == "loop_done":
                return

    consume_task = asyncio.create_task(_consume())
    try:
        summary = await loop_obj.run(port)
        await consume_task
        await state.broadcast({"type": "loop_done", "final_state": summary.final_state.value})
    except Exception as exc:  # noqa: BLE001
        state.heal_state = "failed"
        consume_task.cancel()
        await asyncio.gather(consume_task, return_exceptions=True)
        await state.broadcast({"type": "error", "message": str(exc)})


async def _run_monitor_only(board: BoardConfig, port: str) -> None:
    state = _get_state()
    event_q: asyncio.Queue[MonitorEvent] = asyncio.Queue()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    mon = SerialMonitor(
        port=port,
        baud=board.baud_rate,
        target=board.target,
        event_queue=event_q,
        loop=loop,
        stability_window=float(board.stability_window),
    )
    state.monitor = mon
    state.heal_state = "monitoring"
    state.active_board = board
    state.active_port = port
    mon.start()
    try:
        while state.monitor is mon:
            try:
                evt = await asyncio.wait_for(event_q.get(), timeout=1.0)
            except TimeoutError:
                continue
            if isinstance(evt, LogEvent):
                _append_log(evt.line.text, "serial")
                await state.broadcast(
                    {
                        "type": "log",
                        "text": evt.line.text,
                        "source": "serial",
                        "crash": evt.line.is_crash_line,
                    }
                )
            elif isinstance(evt, CrashDetected):
                state.crashes.append({"ts": time.time(), "kind": evt.event.kind.value})
                await state.broadcast({"type": "crash", "kind": evt.event.kind.value})
            elif isinstance(evt, PortError):
                await state.broadcast({"type": "error", "message": evt.message})
                break
    finally:
        mon.stop()
        if state.monitor is mon:
            state.monitor = None
            state.heal_state = "idle"


def _append_log(text: str, source: str) -> None:
    state = _get_state()
    state.serial_log.append({"ts": time.time(), "text": text, "source": source})
    if len(state.serial_log) > 500:
        state.serial_log = state.serial_log[-500:]
