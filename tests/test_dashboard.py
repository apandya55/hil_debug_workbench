import asyncio
from pathlib import Path

import pytest

import dashboard.server as dashboard_server
from hil_cli.config import BoardConfig, HilConfig


@pytest.mark.asyncio
async def test_monitor_waits_through_idle_periods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = BoardConfig(
        name="test-board",
        target="esp32",
        pio_env="test",
        pio_project_dir=str(tmp_path),
    )
    dashboard_server._state = dashboard_server.WorkbenchState(HilConfig(boards=[board]))

    class IdleMonitor:
        started = False
        stopped = False

        def __init__(self, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

    monkeypatch.setattr(dashboard_server, "SerialMonitor", IdleMonitor)
    task = asyncio.create_task(dashboard_server._run_monitor_only(board, "/dev/test"))
    try:
        await asyncio.sleep(1.1)
        assert not task.done()
    finally:
        dashboard_server._state.heal_state = "idle"
        dashboard_server._state.monitor = None
        await asyncio.wait_for(task, timeout=2)

    assert dashboard_server._state.heal_state == "idle"
