# Changelog

All notable changes to HIL Debug Workbench will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-09

### Added
- USB device auto-detection identifying ESP32 (CP2102, CH340, FTDI, native S2/S3/C3) and RP2040 (Pico, Pico W, Feather, Nano Connect) boards by VID/PID.
- Declarative `hil.yaml` board specification with Pydantic schema validation.
- Threaded serial monitor with automated regex panic capture across ESP-IDF Guru Meditation, stack overflows, watchdog timeouts, and ARM Cortex-M HardFaults.
- Automatic toolchain resolution finding cross-compiler `addr2line` binaries in PlatformIO packages and system PATH.
- Memory address backtrace resolver formatting crash dumps with source file and line context from firmware ELF binaries.
- Autonomous self-healing loop querying Claude for targeted AST/verbatim source patches and iterating until firmware stability is verified.
- FastAPI web dashboard with live WebSocket serial streaming, pipeline state visualization, and Chart.js metrics.
- Textual terminal workbench providing interactive keyboard navigation, log viewing, and one-touch flash/monitor/heal triggers.
- Multi-platform test harness with mock serial relays and fake toolchain runners.

[0.1.0]: https://github.com/apandya55/hil_debug_workbench/releases/tag/v0.1.0
