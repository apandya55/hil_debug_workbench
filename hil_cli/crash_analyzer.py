"""Crash dump parser + addr2line resolver for ESP32 and RP2040."""

from __future__ import annotations

import re
import subprocess  # nosec B404
from dataclasses import dataclass, field
from pathlib import Path

from .serial_monitor import CrashEvent
from .toolchain import resolve_binary


@dataclass
class SourceLocation:
    address: str  # hex, no 0x prefix
    function: str
    file: str
    line: int
    column: int = 0
    is_inlined: bool = False

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line}"
        if self.column:
            loc += f":{self.column}"
        return f"0x{self.address}  {self.function}  ({loc})"


@dataclass
class CrashReport:
    crash: CrashEvent
    locations: list[SourceLocation] = field(default_factory=list)
    elf_path: str | None = None
    analysis_error: str | None = None

    # Set by the AI healing loop
    ai_analysis: str = ""
    suggested_fixes: list[dict] = field(default_factory=list)  # {"file", "old", "new"}

    def readable_backtrace(self) -> str:
        lines = [f"Crash kind : {self.crash.kind.value}"]
        lines.append(f"Addresses  : {len(self.crash.addresses)} frames")
        lines.append("")
        if self.locations:
            lines.append("── Backtrace ─────────────────────────────")
            for i, loc in enumerate(self.locations):
                lines.append(f"  #{i:<2} {loc}")
        else:
            lines.append("── Raw addresses (no ELF for addr2line) ──")
            for addr in self.crash.addresses:
                lines.append(f"  0x{addr}")
        lines.append("")
        lines.append("── Raw dump ───────────────────────────────")
        lines.append(self.crash.raw_dump)
        return "\n".join(lines)

    def context_for_ai(self, max_src_lines: int = 40) -> str:
        """Format the report for injection into an LLM prompt."""
        parts: list[str] = []
        parts.append(f"## Crash kind\n{self.crash.kind.value}\n")
        parts.append(f"## Raw crash dump\n```\n{self.crash.raw_dump}\n```\n")
        if self.locations:
            parts.append("## Resolved backtrace")
            for loc in self.locations:
                parts.append(f"- `{loc}`")
            parts.append("")
            # Embed relevant source snippets
            parts.append("## Source context")
            seen_files: set[str] = set()
            for loc in self.locations:
                if loc.file in ("??", "", "<unknown>") or loc.file in seen_files:
                    continue
                seen_files.add(loc.file)
                fp = Path(loc.file)
                if not fp.exists():
                    continue
                try:
                    src_lines = fp.read_text(errors="replace").splitlines()
                    start = max(0, loc.line - max_src_lines // 2 - 1)
                    end = min(len(src_lines), loc.line + max_src_lines // 2)
                    snippet = "\n".join(
                        f"{i + start + 1:4d} | {src_lines[i + start]}" for i in range(end - start)
                    )
                    parts.append(
                        f"\n### {fp.name} (lines {start + 1}–{end})\n```cpp\n{snippet}\n```"
                    )
                except OSError:
                    pass
        return "\n".join(parts)


_A2L_LOC_RE = re.compile(r"^(.*) at (.+):(\d+)(?::(\d+))?$")
_INLINED_PREFIX = " (inlined by) "


def _run_addr2line(
    elf: Path,
    addresses: list[str],
    toolchain_prefix: str,
) -> list[SourceLocation]:
    """
    Call addr2line once for all addresses and parse the output.

    addr2line flags:
      -p  pretty-print (one line per frame)
      -f  show function names
      -i  follow inlined frames
      -a  show address before each result
      -C  demangle C++ names
      -e  ELF file
    """
    try:
        binary = resolve_binary(toolchain_prefix, "addr2line")
    except FileNotFoundError:
        return []

    hex_addrs = [f"0x{a}" for a in addresses]
    try:
        result = subprocess.run(  # nosec B603
            [str(binary), "-pfiaC", "-e", str(elf)] + hex_addrs,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return []

    locations: list[SourceLocation] = []
    current_addr = addresses[0] if addresses else ""
    addr_idx = 0

    for raw_line in output.splitlines():
        # New address block: "0xADDR: func at file:line"
        if raw_line.startswith("0x"):
            addr_match = re.match(r"0x([0-9a-fA-F]+):\s*(.*)", raw_line)
            if addr_match:
                if addr_idx < len(addresses):
                    current_addr = addresses[addr_idx]
                    addr_idx += 1
                raw_line = addr_match.group(2)

        is_inlined = _INLINED_PREFIX in raw_line
        clean = raw_line.replace(_INLINED_PREFIX, " at ")

        m = _A2L_LOC_RE.match(clean.strip())
        if m:
            func = m.group(1).strip()
            fpath = m.group(2).strip()
            lineno = int(m.group(3))
            col = int(m.group(4)) if m.group(4) else 0
            locations.append(
                SourceLocation(
                    address=current_addr,
                    function=func,
                    file=fpath,
                    line=lineno,
                    column=col,
                    is_inlined=is_inlined,
                )
            )

    return locations


def analyze_crash(crash: CrashEvent, elf_path: Path | None, toolchain_prefix: str) -> CrashReport:
    """
    Resolve backtrace addresses to source locations and return a CrashReport.

    Works with or without an ELF (degrades gracefully to raw addresses).
    """
    report = CrashReport(crash=crash, elf_path=str(elf_path) if elf_path else None)

    if not crash.addresses:
        report.analysis_error = "No addresses extracted from crash dump"
        return report

    if elf_path is None or not elf_path.exists():
        report.analysis_error = (
            f"ELF not found at {elf_path}; set firmware_elf in hil.yaml for full backtrace"
        )
        return report

    report.locations = _run_addr2line(elf_path, crash.addresses, toolchain_prefix)
    if not report.locations:
        report.analysis_error = "addr2line returned no results (check toolchain_prefix)"

    return report
