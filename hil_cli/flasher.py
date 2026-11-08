"""PlatformIO subprocess helpers for building and uploading firmware."""

from __future__ import annotations

import asyncio
import shutil
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class FlashStatus(str, Enum):
    SUCCESS = "success"
    BUILD_FAILED = "build_failed"
    UPLOAD_FAILED = "upload_failed"
    PIO_NOT_FOUND = "pio_not_found"


@dataclass
class FlashResult:
    status: FlashStatus
    duration_s: float = 0.0
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

    @property
    def ok(self) -> bool:
        return self.status == FlashStatus.SUCCESS

    def error_summary(self) -> str:
        if self.status == FlashStatus.PIO_NOT_FOUND:
            return (
                "PlatformIO (`pio`) not found on PATH. Install it: https://platformio.org/install"
            )
        lines = (self.stderr or self.stdout).splitlines()
        # The final lines usually contain the build or upload error.
        tail = "\n".join(lines[-20:])
        return f"[{self.status}]\n{tail}"


def _find_pio() -> Path | None:
    """Locate the `pio` executable."""
    p = shutil.which("pio")
    if p:
        return Path(p)
    # Common non-PATH install locations
    candidates = [
        Path.home() / ".platformio" / "penv" / "bin" / "pio",
        Path.home() / ".local" / "bin" / "pio",
        Path("/usr/local/bin/pio"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


async def _stream_process(
    cmd: list[str],
    cwd: str,
    log_cb: asyncio.Queue[str] | None,
) -> tuple[int, str, str]:
    """Run cmd, stream stdout/stderr to log_cb queue, return (rc, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    async def drain(stream: asyncio.StreamReader, buf: list[str], prefix: str) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            buf.append(text)
            if log_cb:
                await log_cb.put(f"{prefix}{text}")

    await asyncio.gather(
        drain(proc.stdout, stdout_lines, ""),  # type: ignore[arg-type]
        drain(proc.stderr, stderr_lines, "[stderr] "),  # type: ignore[arg-type]
    )
    rc = await proc.wait()
    return rc, "\n".join(stdout_lines), "\n".join(stderr_lines)


async def flash_firmware(
    pio_project_dir: str,
    pio_env: str,
    port: str | None = None,
    log_queue: asyncio.Queue[str] | None = None,
    extra_flags: list[str] | None = None,
) -> FlashResult:
    """
    Run `pio run -e <env> -t upload` inside *pio_project_dir*.

    Streams build output to *log_queue* (if given) as plain text lines.
    """
    pio = _find_pio()
    if pio is None:
        return FlashResult(status=FlashStatus.PIO_NOT_FOUND)

    cmd: list[str] = [str(pio), "run", "-e", pio_env, "-t", "upload"]
    if port:
        cmd += ["--upload-port", port]
    if extra_flags:
        cmd += extra_flags

    t0 = time.monotonic()
    rc, stdout, stderr = await _stream_process(cmd, cwd=pio_project_dir, log_cb=log_queue)
    elapsed = time.monotonic() - t0

    if rc == 0:
        status = FlashStatus.SUCCESS
    elif "Error" in stderr and "upload" in stderr.lower():
        status = FlashStatus.UPLOAD_FAILED
    else:
        status = FlashStatus.BUILD_FAILED

    return FlashResult(
        status=status,
        duration_s=elapsed,
        stdout=stdout,
        stderr=stderr,
        returncode=rc,
    )


async def build_only(
    pio_project_dir: str,
    pio_env: str,
    log_queue: asyncio.Queue[str] | None = None,
) -> FlashResult:
    """Build firmware without uploading (useful for syntax checks)."""
    pio = _find_pio()
    if pio is None:
        return FlashResult(status=FlashStatus.PIO_NOT_FOUND)

    cmd = [str(pio), "run", "-e", pio_env]
    t0 = time.monotonic()
    rc, stdout, stderr = await _stream_process(cmd, cwd=pio_project_dir, log_cb=log_queue)
    elapsed = time.monotonic() - t0
    status = FlashStatus.SUCCESS if rc == 0 else FlashStatus.BUILD_FAILED
    return FlashResult(
        status=status, duration_s=elapsed, stdout=stdout, stderr=stderr, returncode=rc
    )
